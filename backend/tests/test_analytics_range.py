from __future__ import annotations

import json
from datetime import date

from backend_app import build_analytics_range_response
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


def test_build_analytics_range_response_aggregates_summaries_and_events():
    _, table, _, service = make_service()
    service.process_raw_message(json.dumps(CAT_B_SAMPLE))
    service.process_raw_message(json.dumps(CAT_A_SAMPLE))

    result = build_analytics_range_response(table, date(2026, 5, 7), date(2026, 5, 7))

    assert result["startDate"] == "2026-05-07"
    assert result["endDate"] == "2026-05-07"
    assert result["totals"]["feedingCount"] == 2
    assert result["totals"]["totalIntakeGrams"] == 107.6
    assert len(result["feedingRecords"]) == 2

    by_cat = {item["catId"]: item for item in result["catSummaries"]}
    assert by_cat["cat_a"]["totalIntakeGrams"] == 107.5
    assert by_cat["cat_a"]["feedingCount"] == 1
    assert by_cat["cat_b"]["totalIntakeGrams"] == 0.1
    assert by_cat["cat_b"]["feedingCount"] == 1


def test_build_analytics_range_response_includes_zero_days_for_charts():
    _, table, _, service = make_service()
    service.process_raw_message(json.dumps(CAT_A_SAMPLE))

    result = build_analytics_range_response(table, date(2026, 5, 7), date(2026, 5, 8))

    assert len(result["dailySeries"]) == 4
    zero_day_rows = [item for item in result["dailySeries"] if item["date"] == "2026-05-08"]
    assert {item["catId"] for item in zero_day_rows} == {"cat_a", "cat_b"}
    assert all(item["totalIntakeGrams"] == 0 for item in zero_day_rows)
