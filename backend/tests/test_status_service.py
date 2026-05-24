from __future__ import annotations

import json
import base64

from shared.blob_repository import InMemoryBlobRepository
from shared.config import AppConfig
from shared.status_service import StatusService
from shared.table_repository import InMemoryTableRepository


CAT_B_SAMPLE = {
    "deviceId": "feeder-esp32-01",
    "catName": "CatB",
    "catUID": "0420D6BAFD1691",
    "event": "feeding_complete",
    "feedingEndTime": 1778152042,
    "feedingStartTime": 1778152028,
    "durationSec": 14,
    "intakeGrams": 0.1,
}

CAT_A_SAMPLE = {
    "deviceId": "feeder-esp32-01",
    "catName": "CatA",
    "catUID": "B9BD18C9",
    "event": "feeding_complete",
    "feedingEndTime": 1778152085,
    "feedingStartTime": 1778152060,
    "durationSec": 25,
    "intakeGrams": 107.5,
}


def make_service():
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    blob = InMemoryBlobRepository(config)
    table.seed_cat_profiles()
    return config, table, blob, StatusService(table, blob, config)


def test_process_samples_updates_status_and_outputs():
    config, table, blob, service = make_service()
    service.process_raw_message(json.dumps(CAT_B_SAMPLE))
    service.process_raw_message(json.dumps(CAT_A_SAMPLE))

    cat_a = table.get("CurrentStatus", "CURRENT", "cat_a")
    cat_b = table.get("CurrentStatus", "CURRENT", "cat_b")
    assert cat_a["lastFeedingCompletedTimeUtc"] == "2026-05-07T11:08:05Z"
    assert cat_a["todayStatus"] == "over_target"
    assert cat_b["lastFeedingCompletedTimeUtc"] == "2026-05-07T11:07:22Z"
    assert cat_b["todayStatus"] == "very_low_intake"
    assert "isEating" not in cat_a
    assert (config.backend_data_container, "current-status.json") in blob.blobs
    assert (config.backend_data_container, "daily-summary/2026-05-07.json") in blob.blobs
    assert (config.backend_data_container, "recent-feedings/2026-05-07.json") in blob.blobs
    assert (config.backend_data_container, "alerts/latest.json") in blob.blobs
    assert len(table.list_frontend_data("current-status")) == 2
    assert len(table.list_frontend_data("daily-summary_2026-05-07")) == 2
    assert len(table.list_frontend_data("recent-feedings_2026-05-07")) == 2
    assert table.get("FrontendData", "current-status", "cat_a")["todayStatus"] == "over_target"


def test_duplicate_does_not_double_count():
    _, table, _, service = make_service()
    first = service.process_raw_message(json.dumps(CAT_A_SAMPLE))
    second = service.process_raw_message(json.dumps(CAT_A_SAMPLE))
    summary = table.get_daily_summary("cat_a", "2026-05-07")
    assert first.status == "processed"
    assert second.status == "duplicate"
    assert summary["feedingCount"] == 1
    assert summary["totalIntakeGrams"] == 107.5


def test_unknown_rfid_creates_alert_and_no_summary():
    _, table, _, service = make_service()
    result = service.process_raw_message(json.dumps({**CAT_A_SAMPLE, "catUID": "UNKNOWN"}))
    assert result.status == "unknown_rfid"
    assert table.get_daily_summary("cat_a", "2026-05-07") is None
    assert table.tables["Alerts"]


def test_heartbeat_with_ok_checks_is_not_invalid_payload():
    _, table, _, service = make_service()
    result = service.process_raw_message(
        json.dumps(
            {
                "deviceId": "feeder-esp32-01",
                "event": "heartbeat",
                "timestamp": 1778152085,
                "rfid_ok": True,
                "tof_ok": True,
                "motor_ok": True,
            }
        )
    )
    assert result.status == "heartbeat"
    assert table.tables["Alerts"] == {}


def test_heartbeat_with_failed_check_creates_device_health_alert():
    _, table, _, service = make_service()
    result = service.process_raw_message(
        json.dumps(
            {
                "deviceId": "feeder-esp32-01",
                "event": "heartbeat",
                "timestamp": 1778152085,
                "rfid_ok": True,
                "tof_ok": False,
                "motor_ok": True,
            }
        )
    )
    alerts = list(table.tables["Alerts"].values())
    assert result.status == "heartbeat"
    assert alerts[0]["alertType"] == "device_health_error"
    assert "tof" in alerts[0]["message"]


def test_heartbeat_with_recovered_check_resolves_device_health_alert():
    _, table, _, service = make_service()
    service.process_raw_message(
        json.dumps(
            {
                "deviceId": "feeder-esp32-01",
                "event": "heartbeat",
                "timestamp": 1778152085,
                "rfid_ok": True,
                "tof_ok": False,
                "motor_ok": True,
            }
        )
    )

    service.process_raw_message(
        json.dumps(
            {
                "deviceId": "feeder-esp32-01",
                "event": "heartbeat",
                "timestamp": 1778152095,
                "rfid_ok": True,
                "tof_ok": True,
                "motor_ok": True,
            }
        )
    )

    alerts = list(table.tables["Alerts"].values())
    assert alerts[0]["status"] == "resolved"
    assert alerts[0]["resolvedBy"] == "auto_device_health_recovered"


def test_normal_feeding_status_resolves_open_feeding_alerts():
    _, table, _, service = make_service()
    service.process_raw_message(json.dumps({**CAT_A_SAMPLE, "intakeGrams": 0.5}))
    first_alert = list(table.tables["Alerts"].values())[0]
    assert first_alert["alertType"] == "very_low_intake"
    assert first_alert["status"] == "open"

    service.process_raw_message(
        json.dumps(
            {
                **CAT_A_SAMPLE,
                "feedingStartTime": CAT_A_SAMPLE["feedingStartTime"] + 100,
                "feedingEndTime": CAT_A_SAMPLE["feedingEndTime"] + 100,
                "intakeGrams": 60,
            }
        )
    )

    updated_alert = table.get_alert("2026-05-07", first_alert["alertId"])
    assert updated_alert["status"] == "resolved"
    assert updated_alert["resolvedBy"] == "auto_feeding_normal"


def test_null_intake_creates_scale_sensor_error_and_no_summary():
    config, table, blob, service = make_service()
    result = service.process_raw_message(json.dumps({**CAT_B_SAMPLE, "intakeGrams": None}))
    alerts = list(table.tables["Alerts"].values())
    assert result.status == "scale_sensor_error"
    assert table.get_daily_summary("cat_b", "2026-05-07") is None
    assert alerts[0]["alertType"] == "scale_sensor_error"
    assert any(container == config.error_container for container, _ in blob.blobs)


def test_null_intake_from_iothub_wrapper_bytes_is_serializable():
    config, table, blob, service = make_service()
    payload = json.dumps({**CAT_B_SAMPLE, "intakeGrams": None}).encode("utf-8")
    wrapped = json.dumps(
        {
            "EnqueuedTimeUtc": "2026-05-07T11:07:22.0000000Z",
            "SystemProperties": {"connectionDeviceId": "feeder-esp32-01"},
            "Body": base64.b64encode(payload).decode("utf-8"),
        }
    ).encode("utf-8")

    result = service.process_raw_message(wrapped)

    assert result.status == "scale_sensor_error"
    assert table.get_daily_summary("cat_b", "2026-05-07") is None
    assert any(container == config.error_container for container, _ in blob.blobs)
