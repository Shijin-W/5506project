from __future__ import annotations

from datetime import date

from backend_app import build_alert_history_response
from shared.alert_service import build_alert
from shared.table_repository import InMemoryTableRepository


def test_build_alert_history_response_includes_open_and_resolved_alerts():
    table = InMemoryTableRepository()
    open_alert = build_alert("not_eaten", "2026-05-17", "CatA has not eaten.", "cat_a", "CatA", "not-eaten")
    resolved_alert = build_alert(
        "over_target",
        "2026-05-16",
        "CatB ate above target.",
        "cat_b",
        "CatB",
        "over-target",
    )

    table.insert_alert(open_alert)
    table.insert_alert(resolved_alert)
    table.update_alert_status("2026-05-16", resolved_alert["alertId"], "resolved", "manual")

    result = build_alert_history_response(table, date(2026, 5, 16), date(2026, 5, 17))

    assert result["startDate"] == "2026-05-16"
    assert result["endDate"] == "2026-05-17"
    assert result["totals"]["alertCount"] == 2
    assert result["totals"]["openCount"] == 1
    assert result["totals"]["resolvedCount"] == 1

    by_id = {alert["alertId"]: alert for alert in result["alerts"]}
    assert by_id[open_alert["alertId"]]["status"] == "open"
    assert by_id[resolved_alert["alertId"]]["status"] == "resolved"
    assert by_id[resolved_alert["alertId"]]["resolvedBy"] == "manual"
    assert by_id[resolved_alert["alertId"]]["date"] == "2026-05-16"
