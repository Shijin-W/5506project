from __future__ import annotations

import json
from datetime import timedelta

from shared.blob_repository import InMemoryBlobRepository
from shared.config import AppConfig
from shared.status_service import StatusService
from shared.table_repository import InMemoryTableRepository
from shared.time_utils import now_utc_iso, utc_iso_to_datetime
from shared.twin_service import build_desired_properties_from_cat_profiles


def _active_operation_times() -> dict[str, str]:
    now = utc_iso_to_datetime(now_utc_iso())
    return {
        "createdAtUtc": (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
        "updatedAtUtc": (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
        "expiresAtUtc": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    }


def test_rfid_update_preserves_history_and_changes_active_mapping():
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    InMemoryBlobRepository(config)
    table.seed_cat_profiles()

    result = table.update_rfid_mapping("cat_a", "A1B2C3D4", "2026-05-20T10:00:00Z")

    assert result["oldCatUID"] == "B9BD18C9"
    assert table.get_active_cat_by_uid("B9BD18C9") is None
    assert table.get_active_cat_by_uid("A1B2C3D4")["catId"] == "cat_a"
    history = table.query("RfidHistory", "PartitionKey eq 'cat_a'")
    assert len(history) == 2
    assert any(row["catUID"] == "B9BD18C9" and row["validToUtc"] == "2026-05-20T10:00:00Z" for row in history)


def test_device_twin_desired_properties_include_both_cats():
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    table.seed_cat_profiles()

    desired = build_desired_properties_from_cat_profiles(table.list_active_cats(), config)

    assert desired["cats"]["cat_a"]["catUID"] == "B9BD18C9"
    assert desired["cats"]["cat_b"]["catUID"] == "0420D6BAFD1691"
    assert desired["feedingRules"]["allowUnknownRfid"] is False


def test_update_cat_profile_updates_profile_status_and_rfid_mapping():
    table = InMemoryTableRepository()
    table.seed_cat_profiles()

    profile = table.update_cat_profile("cat_a", {"catName": "Luna", "targetDailyGrams": 55})

    assert profile["catName"] == "Luna"
    assert profile["targetDailyGrams"] == 55
    assert table.get_cat_profile("cat_a")["catName"] == "Luna"
    assert table.get("CurrentStatus", "CURRENT", "cat_a")["catName"] == "Luna"
    assert table.get("CurrentStatus", "CURRENT", "cat_a")["targetDailyGrams"] == 55
    assert table.get_active_cat_by_uid("B9BD18C9")["catName"] == "Luna"


def test_tag_scanned_rebinds_selected_cat_from_pending_operation():
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    blob = InMemoryBlobRepository(config)
    table.seed_cat_profiles()
    service = StatusService(table, blob, config)
    table.upsert_rfid_operation(
        {
            "PartitionKey": "RFID_REBIND",
            "RowKey": "rfid-op-test",
            "operationId": "rfid-op-test",
            "operationType": "rebind_rfid",
            "status": "command_sent",
            "targetCatId": "cat_a",
            "targetCatName": "CatA",
            "oldCatUID": "B9BD18C9",
            "trayIndex": 0,
            "timeoutSec": 120,
            **_active_operation_times(),
        }
    )

    result = service.process_raw_message(
        json.dumps(
            {
                "deviceId": "feeder-esp32-01",
                "event": "tag_scanned",
                "operationId": "rfid-op-test",
                "uid": "a1b2c3d4",
                "timestamp": 1779271200,
            }
        )
    )

    operation = table.get_rfid_operation("rfid-op-test")
    assert result.status == "rfid_rebind_applied"
    assert table.get_active_cat_by_uid("B9BD18C9") is None
    assert table.get_active_cat_by_uid("A1B2C3D4")["catId"] == "cat_a"
    assert operation["status"] == "applied"
    assert operation["newCatUID"] == "A1B2C3D4"
    assert table.get("FrontendData", "current-status", "cat_a")["currentCatUID"] == "A1B2C3D4"


def test_scan_status_does_not_downgrade_applied_operation():
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    blob = InMemoryBlobRepository(config)
    table.seed_cat_profiles()
    service = StatusService(table, blob, config)
    table.upsert_rfid_operation(
        {
            "PartitionKey": "RFID_REBIND",
            "RowKey": "rfid-op-test",
            "operationId": "rfid-op-test",
            "operationType": "rebind_rfid",
            "status": "applied",
            "targetCatId": "cat_b",
            "targetCatName": "CatB",
            "oldCatUID": "0420D6BAFD1691",
            "newCatUID": "0418BBFA3F7481",
            "trayIndex": 1,
            "timeoutSec": 120,
            **_active_operation_times(),
        }
    )

    result = service.process_raw_message(
        json.dumps(
            {
                "deviceId": "feeder-esp32-01",
                "event": "scan_status",
                "operationId": "rfid-op-test",
                "status": "scanned",
                "timestamp": 1779271200,
            }
        )
    )

    operation = table.get_rfid_operation("rfid-op-test")
    assert result.status == "scan_status_scanned"
    assert operation["status"] == "applied"
    assert operation["lastDeviceStatus"] == "scanned"


def test_tag_scanned_rejects_uid_already_bound_to_other_cat():
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    blob = InMemoryBlobRepository(config)
    table.seed_cat_profiles()
    service = StatusService(table, blob, config)
    table.upsert_rfid_operation(
        {
            "PartitionKey": "RFID_REBIND",
            "RowKey": "rfid-op-test",
            "operationId": "rfid-op-test",
            "operationType": "rebind_rfid",
            "status": "command_sent",
            "targetCatId": "cat_a",
            "targetCatName": "CatA",
            "oldCatUID": "B9BD18C9",
            "trayIndex": 0,
            "timeoutSec": 120,
            **_active_operation_times(),
        }
    )

    result = service.process_raw_message(
        json.dumps(
            {
                "deviceId": "feeder-esp32-01",
                "event": "tag_scanned",
                "operationId": "rfid-op-test",
                "uid": "0420D6BAFD1691",
                "timestamp": 1779271200,
            }
        )
    )

    operation = table.get_rfid_operation("rfid-op-test")
    assert result.status == "rfid_uid_conflict"
    assert table.get_active_cat_by_uid("B9BD18C9")["catId"] == "cat_a"
    assert operation["status"] == "failed"
