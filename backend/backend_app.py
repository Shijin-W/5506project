from __future__ import annotations

import json
import logging
import uuid
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

import azure.functions as func

from shared.alert_service import build_alert
from shared.blob_repository import AzureBlobRepository
from shared.config import AppConfig
from shared.email_service import AlertNotificationService, build_email_subscription, email_hash, mask_email, validate_email
from shared.status_service import StatusService
from shared.table_repository import AzureTableRepository
from shared.time_utils import utc_iso_to_local_date
from shared.twin_service import TwinService, build_desired_properties_from_cat_profiles


TRAY_INDEX_BY_CAT_ID = {
    "cat_a": 0,
    "cat_b": 1,
}


def _services(require_secrets: bool = True) -> tuple[AppConfig, AzureTableRepository, AzureBlobRepository, StatusService]:
    config = AppConfig.from_env(require_secrets=require_secrets)
    table = AzureTableRepository.from_config(config)
    blob = AzureBlobRepository.from_config(config)
    return config, table, blob, StatusService(table, blob, config)


def _email_delivery_configured(config: AppConfig) -> bool:
    return bool(
        (config.acs_connection_string and config.acs_sender_email)
        or (config.smtp_host and config.smtp_from_email)
    )


def _json_response(data, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        status_code=status_code,
        mimetype="application/json",
    )


def _insert_alert_with_notifications(table: AzureTableRepository, config: AppConfig, alert: dict) -> None:
    table.insert_alert(alert)
    AlertNotificationService(table, config).notify_alert(alert)


def _strip_storage_keys(entity: dict) -> dict:
    return {
        key: value
        for key, value in entity.items()
        if key not in {"PartitionKey", "RowKey", "etag", "Timestamp"}
    }


def _parse_iso_date_param(value: str | None, name: str) -> date_cls:
    if not value:
        raise ValueError(f"{name}=YYYY-MM-DD is required")
    try:
        return date_cls.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD") from exc


def _iter_iso_dates(start_date: date_cls, end_date: date_cls):
    for offset in range((end_date - start_date).days + 1):
        yield (start_date + timedelta(days=offset)).isoformat()


def build_analytics_range_response(table: AzureTableRepository, start_date: date_cls, end_date: date_cls) -> dict:
    active_cats = sorted(table.list_active_cats(), key=lambda row: row["catId"])
    cat_totals = {
        cat["catId"]: {
            "catId": cat["catId"],
            "catName": cat["catName"],
            "totalIntakeGrams": 0.0,
            "feedingCount": 0,
            "averageIntakeGrams": 0.0,
            "targetDailyGrams": float(cat.get("targetDailyGrams", 0.0)),
            "daysWithData": 0,
        }
        for cat in active_cats
    }
    daily_series: list[dict] = []
    feeding_records: list[dict] = []

    for local_date in _iter_iso_dates(start_date, end_date):
        summaries = {item["catId"]: item for item in table.list_daily_summary(local_date)}

        for cat in active_cats:
            cat_id = cat["catId"]
            summary = summaries.get(cat_id, {})
            total = round(float(summary.get("totalIntakeGrams", 0.0)), 3)
            count = int(summary.get("feedingCount", 0) or 0)

            cat_totals[cat_id]["totalIntakeGrams"] = round(cat_totals[cat_id]["totalIntakeGrams"] + total, 3)
            cat_totals[cat_id]["feedingCount"] += count
            if summary:
                cat_totals[cat_id]["daysWithData"] += 1

            daily_series.append(
                {
                    "date": local_date,
                    "catId": cat_id,
                    "catName": cat["catName"],
                    "totalIntakeGrams": total,
                    "feedingCount": count,
                }
            )

        for event in sorted(table.get_feeding_events_for_date(local_date), key=lambda row: row.get("feedingEndTimestamp", 0)):
            clean = _strip_storage_keys(event)
            feeding_records.append(
                {
                    "eventId": clean.get("eventId", ""),
                    "catId": clean.get("catId", ""),
                    "catName": clean.get("catName", ""),
                    "catUID": clean.get("catUID", ""),
                    "feedingStartTimeUtc": clean.get("feedingStartTimeUtc", ""),
                    "feedingEndTimeUtc": clean.get("feedingEndTimeUtc", ""),
                    "durationSec": int(clean.get("durationSec", 0) or 0),
                    "intakeGrams": round(float(clean.get("intakeGrams", 0.0) or 0.0), 3),
                    "localDate": clean.get("localDate", local_date),
                }
            )

    cat_summaries = []
    for summary in cat_totals.values():
        count = summary["feedingCount"]
        summary["averageIntakeGrams"] = round(summary["totalIntakeGrams"] / count, 3) if count else 0.0
        cat_summaries.append(summary)

    total_intake = round(sum(item["totalIntakeGrams"] for item in cat_summaries), 3)
    feeding_count = sum(item["feedingCount"] for item in cat_summaries)

    return {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "catSummaries": cat_summaries,
        "dailySeries": daily_series,
        "feedingRecords": feeding_records,
        "totals": {
            "totalIntakeGrams": total_intake,
            "feedingCount": feeding_count,
            "averageIntakeGrams": round(total_intake / feeding_count, 3) if feeding_count else 0.0,
        },
    }


def build_alert_history_response(table: AzureTableRepository, start_date: date_cls, end_date: date_cls) -> dict:
    alerts: list[dict] = []

    for local_date in _iter_iso_dates(start_date, end_date):
        for alert in table.list_alerts(local_date):
            clean = _strip_storage_keys(alert)
            clean["date"] = clean.get("date") or alert.get("PartitionKey", local_date)
            alerts.append(clean)

    alerts.sort(
        key=lambda row: (
            str(row.get("createdAtUtc", "")),
            str(row.get("alertId", row.get("RowKey", ""))),
        ),
        reverse=True,
    )

    open_count = sum(1 for alert in alerts if alert.get("status") == "open")
    resolved_count = sum(1 for alert in alerts if alert.get("status") == "resolved")

    return {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "alerts": alerts,
        "totals": {
            "alertCount": len(alerts),
            "openCount": open_count,
            "resolvedCount": resolved_count,
        },
    }


def _recent_open_medium_alerts(table: AzureTableRepository, days: int = 7, max_alerts: int = 4) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    alerts: list[dict] = []

    for offset in range(days):
        local_date = (today - timedelta(days=offset)).isoformat()
        alerts.extend(table.list_alerts(local_date))

    eligible = [
        alert
        for alert in alerts
        if alert.get("status") == "open" and alert.get("severity", "medium").lower() in {"medium", "high", "critical"}
    ]
    return sorted(eligible, key=lambda row: row.get("createdAtUtc", ""), reverse=True)[:max_alerts]


def process_iothub_feeding_event(events: list[func.EventHubEvent]):
    config, table, blob, service = _services()
    table.create_tables_if_missing()
    blob.create_containers_if_missing()
    for event in events:
        try:
            body = event.get_body()
            result = service.process_raw_message(body)
            logging.info(
                "IoT message processed status=%s eventId=%s duplicate=%s localDate=%s",
                result.status,
                result.event_id,
                result.duplicate,
                result.local_date,
            )
        except Exception as exc:
            logging.exception("Processing error")
            date = datetime.now(timezone.utc).date().isoformat()
            _insert_alert_with_notifications(
                table,
                config,
                build_alert("processing_error", date, f"Processing error: {exc}", suffix="processing-error"),
            )


def check_daily_feeding_status(timer: func.TimerRequest):
    config, table, blob, service = _services()
    table.create_tables_if_missing()
    blob.create_containers_if_missing()
    local_date = utc_iso_to_local_date(datetime.now(timezone.utc).isoformat(), config.local_timezone)
    service.ensure_daily_status_for_date(local_date)
    logging.info("Daily feeding status checked for %s", local_date)


def get_current_status(req: func.HttpRequest) -> func.HttpResponse:
    _, table, _, _ = _services()
    rows = [{k: v for k, v in item.items() if k not in {"PartitionKey", "RowKey", "etag", "Timestamp"}} for item in table.list_current_status()]
    return _json_response(sorted(rows, key=lambda row: row["catId"]))


def get_daily_summary(req: func.HttpRequest) -> func.HttpResponse:
    date = req.params.get("date")
    if not date:
        return _json_response({"error": "date=YYYY-MM-DD is required"}, 400)
    _, table, _, _ = _services()
    rows = [{k: v for k, v in item.items() if k not in {"PartitionKey", "RowKey", "etag", "Timestamp"}} for item in table.list_daily_summary(date)]
    return _json_response(sorted(rows, key=lambda row: row["catId"]))


def get_recent_feedings(req: func.HttpRequest) -> func.HttpResponse:
    date = req.params.get("date")
    if not date:
        return _json_response({"error": "date=YYYY-MM-DD is required"}, 400)
    _, table, _, _ = _services()
    rows = [{k: v for k, v in item.items() if k not in {"PartitionKey", "RowKey", "etag", "Timestamp"}} for item in table.get_feeding_events_for_date(date)]
    return _json_response(sorted(rows, key=lambda row: row.get("feedingEndTimestamp", 0)))


def get_analytics_range(req: func.HttpRequest) -> func.HttpResponse:
    try:
        start_date = _parse_iso_date_param(req.params.get("startDate"), "startDate")
        end_date = _parse_iso_date_param(req.params.get("endDate"), "endDate")
    except ValueError as exc:
        return _json_response({"error": str(exc)}, 400)

    if start_date > end_date:
        return _json_response({"error": "startDate must be earlier than or equal to endDate"}, 400)
    if (end_date - start_date).days > 366:
        return _json_response({"error": "Date range cannot exceed 366 days"}, 400)

    _, table, _, _ = _services()
    return _json_response(build_analytics_range_response(table, start_date, end_date))


def get_alerts(req: func.HttpRequest) -> func.HttpResponse:
    date = req.params.get("date")
    if not date:
        return _json_response({"error": "date=YYYY-MM-DD is required"}, 400)
    _, table, _, _ = _services()
    rows = [{k: v for k, v in item.items() if k not in {"PartitionKey", "RowKey", "etag", "Timestamp"}} for item in table.list_alerts(date)]
    return _json_response(sorted(rows, key=lambda row: row["createdAtUtc"], reverse=True))


def get_alert_history(req: func.HttpRequest) -> func.HttpResponse:
    try:
        start_date = _parse_iso_date_param(req.params.get("startDate"), "startDate")
        end_date = _parse_iso_date_param(req.params.get("endDate"), "endDate")
    except ValueError as exc:
        return _json_response({"error": str(exc)}, 400)

    if start_date > end_date:
        return _json_response({"error": "startDate must be earlier than or equal to endDate"}, 400)
    if (end_date - start_date).days > 366:
        return _json_response({"error": "Date range cannot exceed 366 days"}, 400)

    _, table, _, _ = _services()
    return _json_response(build_alert_history_response(table, start_date, end_date))


def resolve_alert(req: func.HttpRequest) -> func.HttpResponse:
    alert_id = req.route_params.get("alertId")
    date = req.params.get("date")
    if not alert_id:
        return _json_response({"error": "alertId is required"}, 400)
    if not date:
        return _json_response({"error": "date=YYYY-MM-DD is required"}, 400)

    _, table, _, service = _services()
    try:
        alert = table.update_alert_status(date, alert_id, "resolved", "manual")
    except ValueError as exc:
        return _json_response({"error": str(exc)}, 404)

    service.update_backend_outputs(date)
    return _json_response(_strip_storage_keys(alert))


def alert_subscriptions(req: func.HttpRequest) -> func.HttpResponse:
    config, table, _, _ = _services()
    table.create_tables_if_missing()

    if req.method == "GET":
        email_param = req.params.get("email")
        if email_param:
            try:
                email = validate_email(email_param)
            except ValueError as exc:
                return _json_response({"error": str(exc)}, 400)
            subscription = table.get_email_subscription(email_hash(email))
            is_active = bool(subscription and subscription.get("status") == "active")
            return _json_response(
                {
                    "email": mask_email(email),
                    "emailHash": email_hash(email),
                    "subscribed": is_active,
                    "status": subscription.get("status", "inactive") if subscription else "inactive",
                    "minSeverity": subscription.get("minSeverity", "medium") if subscription else "medium",
                    "emailDeliveryConfigured": _email_delivery_configured(config),
                }
            )

        subscribers = [
            {
                "emailHash": item.get("emailHash", item.get("RowKey", "")),
                "email": mask_email(item.get("email", "")),
                "status": item.get("status", ""),
                "minSeverity": item.get("minSeverity", "medium"),
                "createdAtUtc": item.get("createdAtUtc", ""),
                "updatedAtUtc": item.get("updatedAtUtc", ""),
            }
            for item in sorted(table.list_active_email_subscriptions(), key=lambda row: row.get("createdAtUtc", ""))
        ]
        return _json_response(
            {
                "subscribers": subscribers,
                "subscriberCount": len(subscribers),
                "emailDeliveryConfigured": _email_delivery_configured(config),
                "minSeverity": "medium",
            }
        )

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    try:
        email = validate_email(body.get("email", ""))
    except ValueError as exc:
        return _json_response({"error": str(exc)}, 400)

    action = str(body.get("action", "subscribe")).strip().lower()
    subscription = table.get_email_subscription(email_hash(email))
    was_active = bool(subscription and subscription.get("status") == "active")
    if not subscription:
        subscription = build_email_subscription(email, "medium")

    if action == "toggle":
        next_status = "inactive" if subscription.get("status") == "active" else "active"
    elif action in {"unsubscribe", "inactive"}:
        next_status = "inactive"
    elif action in {"subscribe", "active", ""}:
        next_status = "active"
    else:
        return _json_response({"error": "action must be subscribe, unsubscribe, or toggle"}, 400)

    subscription["email"] = email
    subscription["emailHash"] = email_hash(email)
    subscription["status"] = next_status
    subscription["minSeverity"] = "medium"
    subscription["updatedAtUtc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    table.upsert_email_subscription(subscription)
    backlogNotificationCount = 0

    if next_status == "active" and not was_active:
        backlogNotificationCount = AlertNotificationService(table, config).notify_subscription_backlog(
            subscription,
            _recent_open_medium_alerts(table),
            max_alerts=4,
        )

    return _json_response(
        {
            "emailHash": subscription["emailHash"],
            "email": mask_email(subscription["email"]),
            "subscribed": subscription["status"] == "active",
            "status": subscription["status"],
            "minSeverity": subscription["minSeverity"],
            "emailDeliveryConfigured": _email_delivery_configured(config),
            "backlogNotificationCount": backlogNotificationCount,
        },
        201,
    )


def get_device_config_status(req: func.HttpRequest) -> func.HttpResponse:
    config = AppConfig.from_env()
    status = TwinService(config).compare_desired_reported_config_version(config.iot_hub_device_id)
    if not status["inSync"]:
        _, table, _, _ = _services()
        date = datetime.now(timezone.utc).date().isoformat()
        _insert_alert_with_notifications(
            table,
            config,
            build_alert(
                "device_config_out_of_sync",
                date,
                f"Device config out of sync: desired={status['desiredConfigVersion']} reported={status['reportedConfigVersionApplied']}.",
                suffix="device-config-out-of-sync",
            ),
        )
    return _json_response(status)


def get_frontend_data(req: func.HttpRequest) -> func.HttpResponse:
    partition = req.params.get("partition")
    if not partition:
        return _json_response({"error": "partition is required"}, 400)
    _, table, _, _ = _services()
    rows = [
        {k: v for k, v in item.items() if k not in {"etag", "Timestamp"}}
        for item in table.list_frontend_data(partition)
    ]
    return _json_response(sorted(rows, key=lambda row: row.get("RowKey", "")))


def update_cat_rfid(req: func.HttpRequest) -> func.HttpResponse:
    cat_id = req.route_params.get("catId")
    body = req.get_json()
    new_uid = body.get("newCatUID")
    effective = body.get("effectiveTimeUtc") or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not new_uid:
        return _json_response({"error": "newCatUID is required"}, 400)
    config, table, _, _ = _services()
    result = table.update_rfid_mapping(cat_id, new_uid, effective)
    desired = build_desired_properties_from_cat_profiles(table.list_active_cats(), config)
    try:
        TwinService(config).update_device_twin(config.iot_hub_device_id, desired)
        result["deviceTwinUpdateStatus"] = "updated"
    except Exception as exc:
        logging.exception("Device twin update failed")
        result["deviceTwinUpdateStatus"] = f"failed: {exc}"
    return _json_response(result)


def update_cat_profile(req: func.HttpRequest) -> func.HttpResponse:
    cat_id = req.route_params.get("catId")
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    updates = {}
    if "catName" in body:
        updates["catName"] = body.get("catName")
    if "targetDailyGrams" in body:
        updates["targetDailyGrams"] = body.get("targetDailyGrams")

    if not updates:
        return _json_response({"error": "catName or targetDailyGrams is required"}, 400)

    config, table, _, service = _services()
    try:
        profile = table.update_cat_profile(cat_id, updates)
    except ValueError as exc:
        return _json_response({"error": str(exc)}, 400)

    local_date = utc_iso_to_local_date(datetime.now(timezone.utc).isoformat(), config.local_timezone)
    summary = table.get_daily_summary(cat_id, local_date)
    if summary:
        summary["catName"] = profile["catName"]
        summary["targetDailyGrams"] = float(profile["targetDailyGrams"])
        table.upsert_daily_summary(summary)
    service.update_backend_outputs(local_date)

    desired = build_desired_properties_from_cat_profiles(table.list_active_cats(), config)
    try:
        TwinService(config).update_device_twin(config.iot_hub_device_id, desired)
        device_twin_update_status = "updated"
    except Exception as exc:
        logging.exception("Device twin update failed")
        device_twin_update_status = f"failed: {exc}"

    return _json_response(
        {
            "catId": profile["catId"],
            "catName": profile["catName"],
            "currentCatUID": profile.get("currentCatUID", ""),
            "targetDailyGrams": float(profile["targetDailyGrams"]),
            "configVersion": int(profile.get("configVersion", 1)),
            "deviceTwinUpdateStatus": device_twin_update_status,
        }
    )


def start_rfid_rebind_scan(req: func.HttpRequest) -> func.HttpResponse:
    cat_id = req.route_params.get("catId")
    try:
        body = req.get_json()
    except ValueError:
        body = {}
    timeout_sec = int(body.get("timeoutSec", 120))
    if timeout_sec <= 0:
        return _json_response({"error": "timeoutSec must be greater than 0"}, 400)

    config, table, _, _ = _services()
    table.create_tables_if_missing()
    cat = table.get_cat_profile(cat_id)
    if not cat:
        return _json_response({"error": f"Unknown catId: {cat_id}"}, 404)
    if cat_id not in TRAY_INDEX_BY_CAT_ID:
        return _json_response({"error": f"No tray mapping configured for catId: {cat_id}"}, 400)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    created_at = now.isoformat().replace("+00:00", "Z")
    expires_at = (now + timedelta(seconds=timeout_sec)).isoformat().replace("+00:00", "Z")
    operation_id = body.get("operationId") or f"rfid-op-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    command = {
        "action": "start_scan",
        "operationId": operation_id,
        "trayIndex": TRAY_INDEX_BY_CAT_ID[cat_id],
        "timeoutSec": timeout_sec,
    }
    operation = {
        "PartitionKey": "RFID_REBIND",
        "RowKey": operation_id,
        "operationId": operation_id,
        "operationType": "rebind_rfid",
        "status": "created",
        "targetCatId": cat_id,
        "targetCatName": cat["catName"],
        "oldCatUID": cat.get("currentCatUID", ""),
        "trayIndex": TRAY_INDEX_BY_CAT_ID[cat_id],
        "timeoutSec": timeout_sec,
        "createdAtUtc": created_at,
        "updatedAtUtc": created_at,
        "expiresAtUtc": expires_at,
    }
    table.upsert_rfid_operation(operation)

    try:
        TwinService(config).send_c2d_message(config.iot_hub_device_id, command)
        operation = table.update_rfid_operation(
            operation_id,
            {
                "status": "command_sent",
                "commandJson": json.dumps(command, sort_keys=True),
                "commandSentAtUtc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            },
        )
        c2d_status = "sent"
    except Exception as exc:
        logging.exception("RFID scan C2D command failed")
        operation = table.update_rfid_operation(operation_id, {"status": "failed", "failureReason": f"C2D send failed: {exc}"})
        c2d_status = f"failed: {exc}"

    return _json_response(
        {
            "operationId": operation_id,
            "targetCatId": cat_id,
            "targetCatName": cat["catName"],
            "oldCatUID": cat.get("currentCatUID", ""),
            "trayIndex": TRAY_INDEX_BY_CAT_ID[cat_id],
            "timeoutSec": timeout_sec,
            "expiresAtUtc": expires_at,
            "status": operation["status"],
            "c2dStatus": c2d_status,
            "command": command,
        },
        202 if c2d_status == "sent" else 502,
    )


def sync_device_twin_config(req: func.HttpRequest) -> func.HttpResponse:
    config, table, _, _ = _services()
    desired = build_desired_properties_from_cat_profiles(table.list_active_cats(), config)
    TwinService(config).update_device_twin(config.iot_hub_device_id, desired)
    return _json_response({"deviceId": config.iot_hub_device_id, "configVersion": desired["configVersion"], "desired": desired})
