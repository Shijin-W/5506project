from __future__ import annotations

import json

from _bootstrap import ROOT  # noqa: F401
from shared.blob_repository import InMemoryBlobRepository
from shared.config import AppConfig
from shared.status_service import StatusService
from shared.table_repository import InMemoryTableRepository
from shared.twin_service import build_desired_properties_from_cat_profiles


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


def main() -> None:
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    blob = InMemoryBlobRepository(config)
    table.seed_cat_profiles()
    service = StatusService(table, blob, config)

    results = [
        service.process_raw_message(json.dumps(CAT_A_SAMPLE)),
        service.process_raw_message(json.dumps(CAT_B_SAMPLE)),
        service.process_raw_message(json.dumps({**CAT_A_SAMPLE, "catUID": "UNKNOWN"})),
        service.process_raw_message(json.dumps({**CAT_A_SAMPLE, "feedingStartTime": 1778152090})),
        service.process_raw_message(json.dumps({**CAT_A_SAMPLE, "intakeGrams": -1})),
        service.process_raw_message(json.dumps(CAT_A_SAMPLE)),
    ]
    rfid_update = table.update_rfid_mapping("cat_a", "A1B2C3D4", "2026-05-20T10:00:00Z")
    desired = build_desired_properties_from_cat_profiles(table.list_active_cats(), config)

    current = sorted(
        [{k: v for k, v in row.items() if k not in {"PartitionKey", "RowKey"}} for row in table.list_current_status()],
        key=lambda row: row["catId"],
    )
    output = {
        "results": [result.status for result in results],
        "currentStatus": current,
        "dailySummary": table.list_daily_summary("2026-05-07"),
        "alerts": table.list_alerts(next(iter(table.tables["Alerts"].keys()))[0]) if table.tables["Alerts"] else [],
        "rfidUpdate": rfid_update,
        "desiredProperties": desired,
        "currentStatusHasIsEating": any("isEating" in row for row in current),
        "backendCurrentStatusBlobGenerated": (config.backend_data_container, "current-status.json") in blob.blobs,
        "backendDailySummaryBlobGenerated": (config.backend_data_container, "daily-summary/2026-05-07.json") in blob.blobs,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
