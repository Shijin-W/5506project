from __future__ import annotations

from .time_utils import now_utc_iso


SEVERITY_BY_TYPE = {
    "invalid_payload": "high",
    "unknown_rfid": "high",
    "not_eaten": "high",
    "very_low_intake": "medium",
    "under_target": "low",
    "over_target": "medium",
    "device_config_out_of_sync": "medium",
    "device_health_error": "high",
    "processing_error": "high",
    "scale_sensor_error": "high",
}


def build_alert(alert_type: str, date: str, message: str, cat_id: str = "", cat_name: str = "", suffix: str = "") -> dict:
    safe_suffix = suffix or alert_type.replace("_", "-")
    target = cat_id or "system"
    alert_id = f"alert-{target}-{date}-{safe_suffix}"
    return {
        "PartitionKey": date,
        "RowKey": alert_id,
        "alertId": alert_id,
        "catId": cat_id,
        "catName": cat_name,
        "alertType": alert_type,
        "severity": SEVERITY_BY_TYPE.get(alert_type, "medium"),
        "message": message,
        "createdAtUtc": now_utc_iso(),
        "status": "open",
    }


def status_alert(summary: dict) -> dict | None:
    status = summary.get("todayStatus")
    if status == "normal":
        return None
    date = summary["date"]
    cat_id = summary["catId"]
    cat_name = summary["catName"]
    total = summary["totalIntakeGrams"]
    if status == "not_eaten":
        message = f"{cat_name} has no completed feeding recorded on {date}."
    elif status == "very_low_intake":
        message = f"{cat_name} only consumed {total}g on {date}, which is below the minimum meaningful intake threshold."
    elif status == "under_target":
        message = f"{cat_name} consumed {total}g on {date}, which is below the target daily intake."
    elif status == "over_target":
        message = f"{cat_name} consumed {total}g on {date}, which is above the configured over-target threshold."
    else:
        return None
    return build_alert(status, date, message, cat_id, cat_name, status.replace("_", "-"))
