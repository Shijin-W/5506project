from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

try:
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    from azure.data.tables import TableServiceClient, UpdateMode
except ImportError:  # Allows local unit tests without Azure SDK installed.
    ResourceExistsError = ResourceNotFoundError = None
    TableServiceClient = UpdateMode = None

from .config import AppConfig
from .time_utils import now_utc_iso


TABLE_NAMES = [
    "CatProfiles",
    "RfidMap",
    "RfidHistory",
    "FeedingEvents",
    "DailySummary",
    "CurrentStatus",
    "Alerts",
    "FrontendData",
    "RfidOperations",
    "EmailSubscriptions",
    "AlertEmailNotifications",
]


INITIAL_CATS = [
    {
        "catId": "cat_a",
        "catName": "CatA",
        "currentCatUID": "B9BD18C9",
        "targetDailyGrams": 60.0,
        "minimumMeaningfulIntakeGrams": 2.0,
        "overTargetRatio": 1.3,
        "status": "active",
    },
    {
        "catId": "cat_b",
        "catName": "CatB",
        "currentCatUID": "0420D6BAFD1691",
        "targetDailyGrams": 60.0,
        "minimumMeaningfulIntakeGrams": 2.0,
        "overTargetRatio": 1.3,
        "status": "active",
    },
]


class AzureTableRepository:
    def __init__(self, connection_string: str):
        if TableServiceClient is None:
            raise RuntimeError("azure-data-tables is not installed")
        self.service = TableServiceClient.from_connection_string(connection_string)

    @classmethod
    def from_config(cls, config: AppConfig) -> "AzureTableRepository":
        return cls(config.storage_connection_string)

    def table(self, name: str):
        return self.service.get_table_client(name)

    def create_tables_if_missing(self) -> None:
        for name in TABLE_NAMES:
            self.service.create_table_if_not_exists(name)

    def upsert(self, table: str, entity: dict) -> None:
        self.table(table).upsert_entity(entity=entity, mode=UpdateMode.MERGE)

    def get(self, table: str, partition_key: str, row_key: str) -> dict | None:
        try:
            return dict(self.table(table).get_entity(partition_key, row_key))
        except Exception as exc:
            if ResourceNotFoundError and isinstance(exc, ResourceNotFoundError):
                return None
            raise

    def query(self, table: str, filter_query: str) -> list[dict]:
        return [dict(item) for item in self.table(table).query_entities(filter_query)]

    def seed_cat_profiles(self, valid_from_utc: str = "2026-05-01T00:00:00Z") -> None:
        for cat in INITIAL_CATS:
            profile = {"PartitionKey": "CAT", "RowKey": cat["catId"], **cat, "configVersion": 1}
            self.upsert("CatProfiles", profile)
            self.upsert(
                "RfidMap",
                {
                    "PartitionKey": "ACTIVE",
                    "RowKey": cat["currentCatUID"],
                    "catUID": cat["currentCatUID"],
                    "catId": cat["catId"],
                    "catName": cat["catName"],
                    "isActive": True,
                    "validFromUtc": valid_from_utc,
                    "validToUtc": "",
                },
            )
            self.upsert(
                "RfidHistory",
                {
                    "PartitionKey": cat["catId"],
                    "RowKey": f"{valid_from_utc}_{cat['currentCatUID']}",
                    "catId": cat["catId"],
                    "catName": cat["catName"],
                    "catUID": cat["currentCatUID"],
                    "isActive": True,
                    "validFromUtc": valid_from_utc,
                    "validToUtc": "",
                },
            )
            self.upsert(
                "CurrentStatus",
                {
                    "PartitionKey": "CURRENT",
                    "RowKey": cat["catId"],
                    "catId": cat["catId"],
                    "catName": cat["catName"],
                    "currentCatUID": cat["currentCatUID"],
                    "lastFeedingCompletedTimeUtc": "",
                    "lastIntakeGrams": 0.0,
                    "todayIntakeGrams": 0.0,
                    "targetDailyGrams": cat["targetDailyGrams"],
                    "todayStatus": "not_eaten",
                    "updatedAtUtc": now_utc_iso(),
                },
            )

    def get_active_cat_by_uid(self, cat_uid: str) -> dict | None:
        row = self.get("RfidMap", "ACTIVE", cat_uid)
        if not row or not row.get("isActive"):
            return None
        return self.get_cat_profile(row["catId"]) or row

    def get_cat_profile(self, cat_id: str) -> dict | None:
        return self.get("CatProfiles", "CAT", cat_id)

    def list_active_cats(self) -> list[dict]:
        return self.query("CatProfiles", "PartitionKey eq 'CAT' and status eq 'active'")

    def insert_feeding_event_if_not_exists(self, event: dict) -> bool:
        try:
            self.table("FeedingEvents").create_entity(entity=event)
            return True
        except Exception as exc:
            if ResourceExistsError and isinstance(exc, ResourceExistsError):
                return False
            raise

    def get_feeding_event(self, cat_id: str, local_date: str, event_id: str) -> dict | None:
        return self.get("FeedingEvents", f"{cat_id}_{local_date}", event_id)

    def get_feeding_events_for_cat_date(self, cat_id: str, local_date: str) -> list[dict]:
        return self.query("FeedingEvents", f"PartitionKey eq '{cat_id}_{local_date}'")

    def get_feeding_events_for_date(self, local_date: str) -> list[dict]:
        events: list[dict] = []
        for cat in self.list_active_cats():
            events.extend(self.get_feeding_events_for_cat_date(cat["catId"], local_date))
        return events

    def upsert_daily_summary(self, summary: dict) -> None:
        self.upsert("DailySummary", summary)

    def get_daily_summary(self, cat_id: str, local_date: str) -> dict | None:
        return self.get("DailySummary", cat_id, local_date)

    def list_daily_summary(self, local_date: str) -> list[dict]:
        return self.query("DailySummary", f"RowKey eq '{local_date}'")

    def upsert_current_status(self, status: dict) -> None:
        self.upsert("CurrentStatus", status)

    def list_current_status(self) -> list[dict]:
        return self.query("CurrentStatus", "PartitionKey eq 'CURRENT'")

    def insert_alert(self, alert: dict) -> None:
        self.upsert("Alerts", alert)

    def get_alert(self, date: str, alert_id: str) -> dict | None:
        return self.get("Alerts", date, alert_id)

    def list_alerts(self, date: str) -> list[dict]:
        return self.query("Alerts", f"PartitionKey eq '{date}'")

    def update_alert_status(self, date: str, alert_id: str, status: str, resolved_by: str = "") -> dict:
        alert = self.get_alert(date, alert_id)
        if not alert:
            raise ValueError(f"Unknown alertId: {alert_id}")
        alert["status"] = status
        alert["resolvedAtUtc"] = now_utc_iso() if status == "resolved" else ""
        alert["resolvedBy"] = resolved_by
        alert["updatedAtUtc"] = now_utc_iso()
        self.upsert("Alerts", alert)
        return alert

    def resolve_open_alerts(self, date: str, alert_types: list[str], cat_id: str = "", resolved_by: str = "auto") -> int:
        count = 0
        type_set = set(alert_types)
        for alert in self.list_alerts(date):
            if alert.get("status") != "open":
                continue
            if alert.get("alertType") not in type_set:
                continue
            if cat_id and alert.get("catId") != cat_id:
                continue
            self.update_alert_status(date, alert["alertId"], "resolved", resolved_by)
            count += 1
        return count

    def upsert_email_subscription(self, subscription: dict) -> None:
        self.upsert("EmailSubscriptions", subscription)

    def get_email_subscription(self, email_hash: str) -> dict | None:
        return self.get("EmailSubscriptions", "EMAIL_SUBS", email_hash)

    def list_active_email_subscriptions(self) -> list[dict]:
        return self.query("EmailSubscriptions", "PartitionKey eq 'EMAIL_SUBS' and status eq 'active'")

    def get_alert_email_notification(self, alert_id: str, email_hash: str) -> dict | None:
        return self.get("AlertEmailNotifications", alert_id, email_hash)

    def upsert_alert_email_notification(self, notification: dict) -> None:
        self.upsert("AlertEmailNotifications", notification)

    def replace_frontend_partition(self, partition_key: str, rows: list[dict]) -> None:
        table = self.table("FrontendData")
        for existing in self.query("FrontendData", f"PartitionKey eq '{partition_key}'"):
            try:
                table.delete_entity(existing["PartitionKey"], existing["RowKey"])
            except Exception as exc:
                if ResourceNotFoundError and isinstance(exc, ResourceNotFoundError):
                    continue
                raise
        for row in rows:
            self.upsert("FrontendData", row)

    def list_frontend_data(self, partition_key: str) -> list[dict]:
        return self.query("FrontendData", f"PartitionKey eq '{partition_key}'")

    def update_rfid_mapping(self, cat_id: str, new_cat_uid: str, effective_time_utc: str) -> dict:
        profile = self.get_cat_profile(cat_id)
        if not profile:
            raise ValueError(f"Unknown catId: {cat_id}")
        existing = self.get_active_cat_by_uid(new_cat_uid)
        if existing and existing.get("catId") != cat_id:
            raise ValueError(f"RFID UID {new_cat_uid} is already active for {existing.get('catId')}")

        old_uid = profile.get("currentCatUID", "")
        old_map = self.get("RfidMap", "ACTIVE", old_uid) if old_uid else None
        if old_map:
            old_map["isActive"] = False
            old_map["validToUtc"] = effective_time_utc
            self.upsert("RfidMap", old_map)

        for hist in self.query("RfidHistory", f"PartitionKey eq '{cat_id}' and isActive eq true"):
            hist["isActive"] = False
            hist["validToUtc"] = effective_time_utc
            self.upsert("RfidHistory", hist)

        self.upsert(
            "RfidMap",
            {
                "PartitionKey": "ACTIVE",
                "RowKey": new_cat_uid,
                "catUID": new_cat_uid,
                "catId": cat_id,
                "catName": profile["catName"],
                "isActive": True,
                "validFromUtc": effective_time_utc,
                "validToUtc": "",
            },
        )
        self.upsert(
            "RfidHistory",
            {
                "PartitionKey": cat_id,
                "RowKey": f"{effective_time_utc}_{new_cat_uid}",
                "catId": cat_id,
                "catName": profile["catName"],
                "catUID": new_cat_uid,
                "isActive": True,
                "validFromUtc": effective_time_utc,
                "validToUtc": "",
            },
        )
        config_version = int(profile.get("configVersion", 1)) + 1
        profile["currentCatUID"] = new_cat_uid
        profile["configVersion"] = config_version
        self.upsert("CatProfiles", profile)
        current = self.get("CurrentStatus", "CURRENT", cat_id)
        if current:
            current["currentCatUID"] = new_cat_uid
            current["updatedAtUtc"] = now_utc_iso()
            self.upsert("CurrentStatus", current)
        return {"catId": cat_id, "oldCatUID": old_uid, "newCatUID": new_cat_uid, "configVersion": config_version}

    def update_cat_profile(self, cat_id: str, updates: dict) -> dict:
        profile = self.get_cat_profile(cat_id)
        if not profile:
            raise ValueError(f"Unknown catId: {cat_id}")

        if "catName" in updates:
            cat_name = str(updates["catName"]).strip()
            if not cat_name:
                raise ValueError("catName cannot be empty")
            profile["catName"] = cat_name

        if "targetDailyGrams" in updates:
            target = float(updates["targetDailyGrams"])
            if target <= 0:
                raise ValueError("targetDailyGrams must be greater than 0")
            profile["targetDailyGrams"] = target

        profile["configVersion"] = int(profile.get("configVersion", 1)) + 1
        self.upsert("CatProfiles", profile)

        current = self.get("CurrentStatus", "CURRENT", cat_id)
        if current:
            current["catName"] = profile["catName"]
            current["targetDailyGrams"] = float(profile["targetDailyGrams"])
            current["updatedAtUtc"] = now_utc_iso()
            self.upsert("CurrentStatus", current)

        active_map = self.get("RfidMap", "ACTIVE", profile.get("currentCatUID", ""))
        if active_map:
            active_map["catName"] = profile["catName"]
            self.upsert("RfidMap", active_map)

        for hist in self.query("RfidHistory", f"PartitionKey eq '{cat_id}' and isActive eq true"):
            hist["catName"] = profile["catName"]
            self.upsert("RfidHistory", hist)

        return profile

    def upsert_rfid_operation(self, operation: dict) -> None:
        self.upsert("RfidOperations", operation)

    def get_rfid_operation(self, operation_id: str) -> dict | None:
        return self.get("RfidOperations", "RFID_REBIND", operation_id)

    def update_rfid_operation(self, operation_id: str, updates: dict) -> dict:
        operation = self.get_rfid_operation(operation_id)
        if not operation:
            raise ValueError(f"Unknown RFID operation: {operation_id}")
        operation.update(updates)
        operation["updatedAtUtc"] = now_utc_iso()
        self.upsert_rfid_operation(operation)
        return operation


class InMemoryTableRepository:
    def __init__(self):
        self.tables: dict[str, dict[tuple[str, str], dict[str, Any]]] = defaultdict(dict)
        self.create_tables_if_missing()

    def create_tables_if_missing(self) -> None:
        for name in TABLE_NAMES:
            self.tables[name] = self.tables[name]

    def upsert(self, table: str, entity: dict) -> None:
        self.tables[table][(entity["PartitionKey"], entity["RowKey"])] = deepcopy(entity)

    def get(self, table: str, partition_key: str, row_key: str) -> dict | None:
        row = self.tables[table].get((partition_key, row_key))
        return deepcopy(row) if row else None

    def query(self, table: str, filter_query: str) -> list[dict]:
        rows = [deepcopy(row) for row in self.tables[table].values()]
        parts = [part.strip() for part in filter_query.split(" and ")]
        for part in parts:
            if " eq " not in part:
                continue
            field, value = [item.strip() for item in part.split(" eq ", 1)]
            if value.lower() == "true":
                target: Any = True
            elif value.lower() == "false":
                target = False
            else:
                target = value.strip("'")
            rows = [row for row in rows if row.get(field) == target]
        return rows

    seed_cat_profiles = AzureTableRepository.seed_cat_profiles
    get_active_cat_by_uid = AzureTableRepository.get_active_cat_by_uid
    get_cat_profile = AzureTableRepository.get_cat_profile
    list_active_cats = AzureTableRepository.list_active_cats
    get_feeding_event = AzureTableRepository.get_feeding_event
    get_feeding_events_for_cat_date = AzureTableRepository.get_feeding_events_for_cat_date
    get_feeding_events_for_date = AzureTableRepository.get_feeding_events_for_date
    upsert_daily_summary = AzureTableRepository.upsert_daily_summary
    get_daily_summary = AzureTableRepository.get_daily_summary
    list_daily_summary = AzureTableRepository.list_daily_summary
    upsert_current_status = AzureTableRepository.upsert_current_status
    list_current_status = AzureTableRepository.list_current_status
    insert_alert = AzureTableRepository.insert_alert
    get_alert = AzureTableRepository.get_alert
    list_alerts = AzureTableRepository.list_alerts
    update_alert_status = AzureTableRepository.update_alert_status
    resolve_open_alerts = AzureTableRepository.resolve_open_alerts
    upsert_email_subscription = AzureTableRepository.upsert_email_subscription
    get_email_subscription = AzureTableRepository.get_email_subscription
    list_active_email_subscriptions = AzureTableRepository.list_active_email_subscriptions
    get_alert_email_notification = AzureTableRepository.get_alert_email_notification
    upsert_alert_email_notification = AzureTableRepository.upsert_alert_email_notification
    update_rfid_mapping = AzureTableRepository.update_rfid_mapping
    update_cat_profile = AzureTableRepository.update_cat_profile
    upsert_rfid_operation = AzureTableRepository.upsert_rfid_operation
    get_rfid_operation = AzureTableRepository.get_rfid_operation
    update_rfid_operation = AzureTableRepository.update_rfid_operation

    def insert_feeding_event_if_not_exists(self, event: dict) -> bool:
        key = (event["PartitionKey"], event["RowKey"])
        if key in self.tables["FeedingEvents"]:
            return False
        self.tables["FeedingEvents"][key] = deepcopy(event)
        return True

    def replace_frontend_partition(self, partition_key: str, rows: list[dict]) -> None:
        for key in [key for key in self.tables["FrontendData"] if key[0] == partition_key]:
            del self.tables["FrontendData"][key]
        for row in rows:
            self.upsert("FrontendData", row)

    def list_frontend_data(self, partition_key: str) -> list[dict]:
        return self.query("FrontendData", f"PartitionKey eq '{partition_key}'")
