from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from typing import Any

from .alert_service import build_alert, status_alert
from .config import AppConfig
from .email_service import AlertNotificationService
from .parser import parse_iothub_message
from .time_utils import now_utc_iso, unix_to_utc_iso, utc_iso_to_datetime, utc_iso_to_local_date
from .twin_service import TwinService, build_desired_properties_from_cat_profiles
from .validator import validate_feeding_event


@dataclass
class ProcessingResult:
    status: str
    event_id: str = ""
    local_date: str = ""
    duplicate: bool = False
    errors: list[str] | None = None
    warnings: list[str] | None = None


def calculate_today_status(total: float, target: float, minimum: float, over_ratio: float) -> str:
    if total == 0:
        return "not_eaten"
    if total < minimum:
        return "very_low_intake"
    if total < target:
        return "under_target"
    if total <= target * over_ratio:
        return "normal"
    return "over_target"


FEEDING_ALERT_TYPES = ["not_eaten", "very_low_intake", "under_target", "over_target"]
DEVICE_HEALTH_CHECK_ALERT_KEY = {
    "rfid": "rfid_ok",
    "tof": "tof_ok",
    "motor": "motor_ok",
    "scale": "scale_ok",
    "load_cell": "load_cell_ok",
}


class StatusService:
    def __init__(self, table_repo, blob_repo, config: AppConfig):
        self.table = table_repo
        self.blob = blob_repo
        self.config = config
        self.alert_notifier = AlertNotificationService(table_repo, config)

    def process_raw_message(self, raw: Any) -> ProcessingResult:
        try:
            parsed = parse_iothub_message(raw)
        except Exception as exc:
            return self._handle_invalid_payload(raw, [f"parse error: {exc}"], {})

        event_type = parsed.payload.get("event")
        if event_type == "heartbeat":
            return self.process_heartbeat(parsed.payload, parsed.metadata)
        if event_type == "scan_status":
            return self.process_scan_status(parsed.payload, parsed.metadata)
        if event_type == "tag_scanned":
            return self.process_tag_scanned(parsed.payload, parsed.metadata)
        if event_type == "feeding_complete" and parsed.payload.get("intakeGrams") is None:
            return self._handle_scale_sensor_error(parsed.raw, parsed.payload, parsed.metadata)

        errors, warnings, unsupported = validate_feeding_event(parsed.payload)
        if unsupported:
            return ProcessingResult(status="ignored_unsupported_event")
        if errors:
            return self._handle_invalid_payload(parsed.raw, errors, parsed.metadata)

        cat_uid = str(parsed.payload["catUID"])
        cat = self.table.get_active_cat_by_uid(cat_uid)
        if not cat:
            return self._handle_unknown_rfid(parsed.raw, parsed.payload, parsed.metadata)

        event = self._normalize_event(parsed.payload, parsed.metadata, cat, warnings)
        return self.process_feeding_complete(event)

    def process_heartbeat(self, payload: dict, metadata: dict) -> ProcessingResult:
        timestamp = payload.get("timestamp")
        try:
            heartbeat_utc = unix_to_utc_iso(int(timestamp))
        except (TypeError, ValueError):
            heartbeat_utc = now_utc_iso()
        local_date = utc_iso_to_local_date(heartbeat_utc, self.config.local_timezone)

        failed_checks = [
            name[:-3]
            for name in ("rfid_ok", "tof_ok", "motor_ok", "scale_ok", "load_cell_ok")
            if payload.get(name) is False
        ]
        recovered_checks = [
            label
            for label, payload_key in DEVICE_HEALTH_CHECK_ALERT_KEY.items()
            if payload.get(payload_key) is True
        ]
        if recovered_checks:
            self._resolve_device_health_alerts(local_date, recovered_checks)
        if failed_checks:
            device_id = str(payload.get("deviceId", metadata.get("connectionDeviceId", "")))
            self._insert_alert(
                build_alert(
                    "device_health_error",
                    local_date,
                    f"Device {device_id} reported failed health checks: {', '.join(failed_checks)}.",
                    suffix=f"device-health-{timestamp or now_utc_iso()}",
                )
            )
        return ProcessingResult(status="heartbeat", local_date=local_date)

    def process_scan_status(self, payload: dict, metadata: dict) -> ProcessingResult:
        operation_id = str(payload.get("operationId", ""))
        status = str(payload.get("status", ""))
        if not operation_id or not status:
            return self._handle_invalid_payload(payload, ["scan_status requires operationId and status"], metadata)
        operation = self.table.get_rfid_operation(operation_id)
        if not operation:
            return ProcessingResult(status="unknown_rfid_operation", event_id=operation_id, errors=["unknown operationId"])
        mapped_status = {
            "armed": "armed",
            "scanned": "scan_received",
            "timeout": "expired",
            "cancelled": "cancelled",
            "failed": "failed",
        }.get(status)
        if not mapped_status:
            return self._handle_invalid_payload(payload, [f"unsupported scan_status: {status}"], metadata)
        updates = {"lastDeviceStatus": status}
        if operation.get("status") not in {"applied", "failed", "expired", "cancelled"}:
            updates["status"] = mapped_status
        if payload.get("reason"):
            updates["statusReason"] = str(payload["reason"])
        self.table.update_rfid_operation(operation_id, updates)
        return ProcessingResult(status=f"scan_status_{status}", event_id=operation_id)

    def process_tag_scanned(self, payload: dict, metadata: dict) -> ProcessingResult:
        operation_id = str(payload.get("operationId", ""))
        uid = str(payload.get("uid", "")).strip().upper()
        if not operation_id or not uid:
            return self._handle_invalid_payload(payload, ["tag_scanned requires operationId and uid"], metadata)

        operation = self.table.get_rfid_operation(operation_id)
        if not operation:
            date = now_utc_iso()[:10]
            self._insert_alert(
                build_alert(
                    "invalid_payload",
                    date,
                    f"RFID scan received for unknown operationId: {operation_id}.",
                    suffix=f"unknown-rfid-operation-{operation_id}",
                )
            )
            return ProcessingResult(status="unknown_rfid_operation", errors=["unknown operationId"])

        expires_at = operation.get("expiresAtUtc")
        if expires_at and utc_iso_to_datetime(expires_at) < utc_iso_to_datetime(now_utc_iso()):
            self.table.update_rfid_operation(operation_id, {"status": "expired", "scannedUID": uid})
            return ProcessingResult(status="rfid_operation_expired", event_id=operation_id, errors=["operation expired"])

        if operation.get("status") not in {"command_sent", "armed", "scan_received"}:
            return ProcessingResult(status="rfid_operation_not_active", event_id=operation_id)

        existing = self.table.get_active_cat_by_uid(uid)
        target_cat_id = operation["targetCatId"]
        if existing and existing.get("catId") != target_cat_id:
            self.table.update_rfid_operation(
                operation_id,
                {
                    "status": "failed",
                    "scannedUID": uid,
                    "failureReason": f"RFID UID already active for {existing.get('catId')}",
                },
            )
            date = now_utc_iso()[:10]
            self._insert_alert(
                build_alert(
                    "invalid_payload",
                    date,
                    f"RFID UID {uid} is already active for {existing.get('catId')}.",
                    suffix=f"rfid-conflict-{uid}",
                )
            )
            return ProcessingResult(status="rfid_uid_conflict", event_id=operation_id, errors=["uid conflict"])

        effective = now_utc_iso()
        result = self.table.update_rfid_mapping(target_cat_id, uid, effective)
        desired = build_desired_properties_from_cat_profiles(self.table.list_active_cats(), self.config)
        twin_status = "skipped"
        if self.config.iot_hub_connection_string:
            try:
                TwinService(self.config).update_device_twin(self.config.iot_hub_device_id, desired)
                twin_status = "updated"
            except Exception as exc:
                twin_status = f"failed: {exc}"

        self.table.update_rfid_operation(
            operation_id,
            {
                "status": "applied",
                "scannedUID": uid,
                "oldCatUID": result["oldCatUID"],
                "newCatUID": result["newCatUID"],
                "configVersion": result["configVersion"],
                "deviceTwinUpdateStatus": twin_status,
                "appliedAtUtc": effective,
            },
        )
        self.update_backend_outputs(utc_iso_to_local_date(effective, self.config.local_timezone))
        return ProcessingResult(status="rfid_rebind_applied", event_id=operation_id)

    def process_feeding_complete(self, event: dict) -> ProcessingResult:
        inserted = self.table.insert_feeding_event_if_not_exists(event)
        self.blob.write_parsed_event(event)
        self.blob.write_feeding_event(event)
        if inserted:
            self.recalculate_daily_summary(event["catId"], event["localDate"])
        self.update_backend_outputs(event["localDate"])
        return ProcessingResult(
            status="processed" if inserted else "duplicate",
            event_id=event["eventId"],
            local_date=event["localDate"],
            duplicate=not inserted,
            warnings=event.get("validationErrors", "").split("; ") if event.get("validationErrors") else [],
        )

    def _normalize_event(self, payload: dict, metadata: dict, cat: dict, warnings: list[str]) -> dict:
        start_ts = int(payload["feedingStartTime"])
        end_ts = int(payload["feedingEndTime"])
        start_iso = unix_to_utc_iso(start_ts)
        end_iso = unix_to_utc_iso(end_ts)
        local_date = utc_iso_to_local_date(end_iso, self.config.local_timezone)
        cat_id = cat["catId"]
        device_id = str(payload["deviceId"])
        event_id = f"{device_id}-{cat_id}-{end_ts}"
        return {
            "PartitionKey": f"{cat_id}_{local_date}",
            "RowKey": event_id,
            "eventId": event_id,
            "deviceId": device_id,
            "catId": cat_id,
            "catName": cat.get("catName", payload.get("catName", "")),
            "catUID": str(payload["catUID"]),
            "eventType": "feeding_complete",
            "feedingStartTimestamp": start_ts,
            "feedingEndTimestamp": end_ts,
            "feedingStartTimeUtc": start_iso,
            "feedingEndTimeUtc": end_iso,
            "localDate": local_date,
            "durationSec": int(payload["durationSec"]),
            "intakeGrams": float(payload["intakeGrams"]),
            "isValid": True,
            "validationErrors": "; ".join(warnings),
            "iotHubEnqueuedTimeUtc": metadata.get("iotHubEnqueuedTimeUtc", ""),
            "connectionDeviceId": metadata.get("connectionDeviceId", ""),
            "ingestedAtUtc": metadata.get("ingestedAtUtc", ""),
            "createdAtUtc": now_utc_iso(),
        }

    def recalculate_daily_summary(self, cat_id: str, local_date: str) -> dict:
        cat = self.table.get_cat_profile(cat_id)
        if not cat:
            raise ValueError(f"Unknown catId: {cat_id}")
        events = self.table.get_feeding_events_for_cat_date(cat_id, local_date)
        events.sort(key=lambda item: item.get("feedingEndTimestamp", 0))
        total = round(sum(float(item.get("intakeGrams", 0)) for item in events), 3)
        target = float(cat.get("targetDailyGrams", self.config.default_target_daily_grams))
        minimum = float(cat.get("minimumMeaningfulIntakeGrams", self.config.default_minimum_meaningful_intake_grams))
        over_ratio = float(cat.get("overTargetRatio", self.config.default_over_target_ratio))
        status = calculate_today_status(total, target, minimum, over_ratio)
        summary = {
            "PartitionKey": cat_id,
            "RowKey": local_date,
            "catId": cat_id,
            "catName": cat["catName"],
            "date": local_date,
            "totalIntakeGrams": total,
            "feedingCount": len(events),
            "firstFeedingCompletedTimeUtc": events[0]["feedingEndTimeUtc"] if events else "",
            "lastFeedingCompletedTimeUtc": events[-1]["feedingEndTimeUtc"] if events else "",
            "targetDailyGrams": target,
            "minimumMeaningfulIntakeGrams": minimum,
            "overTargetRatio": over_ratio,
            "todayStatus": status,
            "updatedAtUtc": now_utc_iso(),
        }
        self.table.upsert_daily_summary(summary)
        self.table.upsert_current_status(self.build_current_status(cat_id, local_date, summary, events))
        self._resolve_feeding_alerts_for_status(cat_id, local_date, status)
        alert = status_alert(summary)
        if alert:
            self._insert_alert(alert)
        return summary

    def build_current_status(self, cat_id: str, local_date: str, summary: dict | None = None, events: list[dict] | None = None) -> dict:
        cat = self.table.get_cat_profile(cat_id)
        if summary is None:
            summary = self.table.get_daily_summary(cat_id, local_date)
        if events is None:
            events = self.table.get_feeding_events_for_cat_date(cat_id, local_date)
            events.sort(key=lambda item: item.get("feedingEndTimestamp", 0))
        last = events[-1] if events else {}
        return {
            "PartitionKey": "CURRENT",
            "RowKey": cat_id,
            "catId": cat_id,
            "catName": cat["catName"],
            "currentCatUID": cat.get("currentCatUID", ""),
            "lastFeedingCompletedTimeUtc": last.get("feedingEndTimeUtc", summary.get("lastFeedingCompletedTimeUtc", "") if summary else ""),
            "lastIntakeGrams": float(last.get("intakeGrams", 0.0)),
            "todayIntakeGrams": float(summary.get("totalIntakeGrams", 0.0)) if summary else 0.0,
            "targetDailyGrams": float(cat.get("targetDailyGrams", self.config.default_target_daily_grams)),
            "todayStatus": summary.get("todayStatus", "not_eaten") if summary else "not_eaten",
            "updatedAtUtc": now_utc_iso(),
        }

    def ensure_daily_status_for_date(self, local_date: str) -> None:
        for cat in self.table.list_active_cats():
            summary = self.table.get_daily_summary(cat["catId"], local_date)
            if not summary:
                target = float(cat.get("targetDailyGrams", self.config.default_target_daily_grams))
                minimum = float(cat.get("minimumMeaningfulIntakeGrams", self.config.default_minimum_meaningful_intake_grams))
                over_ratio = float(cat.get("overTargetRatio", self.config.default_over_target_ratio))
                summary = {
                    "PartitionKey": cat["catId"],
                    "RowKey": local_date,
                    "catId": cat["catId"],
                    "catName": cat["catName"],
                    "date": local_date,
                    "totalIntakeGrams": 0.0,
                    "feedingCount": 0,
                    "firstFeedingCompletedTimeUtc": "",
                    "lastFeedingCompletedTimeUtc": "",
                    "targetDailyGrams": target,
                    "minimumMeaningfulIntakeGrams": minimum,
                    "overTargetRatio": over_ratio,
                    "todayStatus": "not_eaten",
                    "updatedAtUtc": now_utc_iso(),
                }
                self.table.upsert_daily_summary(summary)
            self.table.upsert_current_status(self.build_current_status(cat["catId"], local_date, summary, []))
            self._resolve_feeding_alerts_for_status(cat["catId"], local_date, summary.get("todayStatus", "not_eaten"))
            alert = status_alert(summary)
            if alert:
                self._insert_alert(alert)
        self.update_backend_outputs(local_date)

    def update_backend_outputs(self, local_date: str) -> None:
        current = [self._strip_storage_keys(item) for item in sorted(self.table.list_current_status(), key=lambda row: row["catId"])]
        summaries = [
            self._summary_output(item)
            for item in sorted(self.table.list_daily_summary(local_date), key=lambda row: row["catId"])
        ]
        feedings = [
            self._feeding_output(item)
            for item in sorted(self.table.get_feeding_events_for_date(local_date), key=lambda row: row.get("feedingEndTimestamp", 0))
        ]
        alerts = [self._strip_storage_keys(item) for item in sorted(self.table.list_alerts(local_date), key=lambda row: row["createdAtUtc"], reverse=True)]
        self.blob.write_json_blob(self.config.backend_data_container, "current-status.json", current)
        self.blob.write_json_blob(self.config.backend_data_container, f"daily-summary/{local_date}.json", summaries)
        self.blob.write_json_blob(self.config.backend_data_container, f"recent-feedings/{local_date}.json", feedings)
        self.blob.write_json_blob(self.config.backend_data_container, "alerts/latest.json", alerts[:50])
        self._write_frontend_table_outputs(local_date, current, summaries, feedings, alerts[:50])

    def _write_frontend_table_outputs(
        self,
        local_date: str,
        current: list[dict],
        summaries: list[dict],
        feedings: list[dict],
        alerts: list[dict],
    ) -> None:
        updated_at = now_utc_iso()
        self.table.replace_frontend_partition(
            "current-status",
            [self._frontend_row("current-status", row["catId"], "current-status", row, updated_at) for row in current],
        )
        self.table.replace_frontend_partition(
            f"daily-summary_{local_date}",
            [self._frontend_row(f"daily-summary_{local_date}", row["catId"], "daily-summary", row, updated_at, local_date) for row in summaries],
        )
        self.table.replace_frontend_partition(
            f"recent-feedings_{local_date}",
            [self._frontend_row(f"recent-feedings_{local_date}", row["eventId"], "recent-feeding", row, updated_at, local_date) for row in feedings],
        )
        self.table.replace_frontend_partition(
            "alerts_latest",
            [self._frontend_row("alerts_latest", row["alertId"], "alert", row, updated_at, row.get("PartitionKey", local_date)) for row in alerts],
        )

    @staticmethod
    def _frontend_row(partition_key: str, row_key: str, data_type: str, payload: dict, updated_at: str, date: str = "") -> dict:
        clean = {key: value for key, value in payload.items() if key not in {"etag", "Timestamp"}}
        row = {
            "PartitionKey": partition_key,
            "RowKey": row_key,
            "dataType": data_type,
            "date": date,
            "payloadJson": json.dumps(clean, ensure_ascii=False, sort_keys=True),
            "updatedAtUtc": updated_at,
        }
        for key, value in clean.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                row[key] = value
        return row

    def _handle_invalid_payload(self, raw: Any, errors: list[str], metadata: dict) -> ProcessingResult:
        date = now_utc_iso()[:10]
        raw_fingerprint = hashlib.sha256(json.dumps(raw, default=str, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        error_id = f"invalid-{date}-{raw_fingerprint}"
        self.blob.write_error_blob(
            {
                "errorId": error_id,
                "errorType": "invalid_payload",
                "errors": errors,
                "metadata": metadata,
                "raw": raw,
                "createdAtUtc": now_utc_iso(),
            },
            date,
        )
        self._insert_alert(build_alert("invalid_payload", date, f"Invalid feeding payload: {'; '.join(errors)}", suffix=error_id))
        return ProcessingResult(status="invalid_payload", errors=errors)

    def _handle_unknown_rfid(self, raw: Any, payload: dict, metadata: dict) -> ProcessingResult:
        date = now_utc_iso()[:10]
        cat_uid = str(payload.get("catUID", ""))
        error_id = f"unknown-rfid-{cat_uid}-{date}"
        self.blob.write_error_blob(
            {
                "errorId": error_id,
                "errorType": "unknown_rfid",
                "catUID": cat_uid,
                "metadata": metadata,
                "raw": raw,
                "createdAtUtc": now_utc_iso(),
            },
            date,
        )
        self._insert_alert(build_alert("unknown_rfid", date, f"Unknown RFID UID received: {cat_uid}.", suffix=f"unknown-rfid-{cat_uid}"))
        return ProcessingResult(status="unknown_rfid")

    def _handle_scale_sensor_error(self, raw: Any, payload: dict, metadata: dict) -> ProcessingResult:
        try:
            event_utc = unix_to_utc_iso(int(payload.get("feedingEndTime")))
        except (TypeError, ValueError):
            event_utc = now_utc_iso()
        local_date = utc_iso_to_local_date(event_utc, self.config.local_timezone)
        cat_uid = str(payload.get("catUID", ""))
        cat = self.table.get_active_cat_by_uid(cat_uid) if cat_uid else None
        cat_id = cat.get("catId", "") if cat else ""
        cat_name = cat.get("catName", payload.get("catName", "")) if cat else str(payload.get("catName", ""))
        timestamp = payload.get("feedingEndTime") or now_utc_iso()
        error_id = f"scale-sensor-error-{cat_id or 'unknown'}-{local_date}-{timestamp}"
        self.blob.write_error_blob(
            {
                "errorId": error_id,
                "errorType": "scale_sensor_error",
                "catId": cat_id,
                "catName": cat_name,
                "catUID": cat_uid,
                "metadata": metadata,
                "raw": raw,
                "createdAtUtc": now_utc_iso(),
            },
            local_date,
        )
        self._insert_alert(
            build_alert(
                "scale_sensor_error",
                local_date,
                f"Scale sensor error for {cat_name or cat_uid or 'unknown cat'}: intakeGrams was null.",
                cat_id,
                cat_name,
                suffix=f"scale-sensor-error-{timestamp}",
            )
        )
        return ProcessingResult(status="scale_sensor_error", local_date=local_date, errors=["intakeGrams is null"])

    def _insert_alert(self, alert: dict) -> None:
        self.table.insert_alert(alert)
        self.alert_notifier.notify_alert(alert)

    def _resolve_feeding_alerts_for_status(self, cat_id: str, local_date: str, status: str) -> None:
        if status == "normal":
            self.table.resolve_open_alerts(local_date, FEEDING_ALERT_TYPES, cat_id, "auto_feeding_normal")

    def _resolve_device_health_alerts(self, local_date: str, recovered_checks: list[str]) -> None:
        for alert in self.table.list_alerts(local_date):
            if alert.get("status") != "open" or alert.get("alertType") != "device_health_error":
                continue
            message = str(alert.get("message", "")).lower()
            if any(check in message for check in recovered_checks):
                self.table.update_alert_status(local_date, alert["alertId"], "resolved", "auto_device_health_recovered")

    @staticmethod
    def _strip_storage_keys(entity: dict) -> dict:
        return {key: value for key, value in entity.items() if key not in {"PartitionKey", "RowKey", "etag", "Timestamp"}}

    def _summary_output(self, entity: dict) -> dict:
        clean = self._strip_storage_keys(entity)
        return {
            "catId": clean["catId"],
            "catName": clean["catName"],
            "date": clean["date"],
            "totalIntakeGrams": clean["totalIntakeGrams"],
            "feedingCount": clean["feedingCount"],
            "lastFeedingCompletedTimeUtc": clean.get("lastFeedingCompletedTimeUtc", ""),
            "targetDailyGrams": clean["targetDailyGrams"],
            "todayStatus": clean["todayStatus"],
        }

    def _feeding_output(self, entity: dict) -> dict:
        clean = self._strip_storage_keys(entity)
        return {
            "eventId": clean["eventId"],
            "catId": clean["catId"],
            "catName": clean["catName"],
            "catUID": clean["catUID"],
            "feedingStartTimeUtc": clean["feedingStartTimeUtc"],
            "feedingEndTimeUtc": clean["feedingEndTimeUtc"],
            "durationSec": clean["durationSec"],
            "intakeGrams": clean["intakeGrams"],
        }
