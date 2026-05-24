from __future__ import annotations

from shared.twin_service import TwinService


def test_compare_desired_reported_config_version_includes_online_fields():
    service = object.__new__(TwinService)
    service.get_device_twin = lambda device_id: {
        "deviceId": device_id,
        "connectionState": "Connected",
        "lastActivityTime": "2026-05-16T09:24:54.4491345Z",
        "status": "enabled",
        "properties": {
            "desired": {"configVersion": 2},
            "reported": {
                "configVersionApplied": 2,
                "lastSyncTime": "2026-05-16T09:10:00Z",
                "knownCats": {"cat_a": "B9BD18C9"},
            },
        },
    }

    status = service.compare_desired_reported_config_version("feeder-esp32-01")

    assert status["deviceId"] == "feeder-esp32-01"
    assert status["online"] is True
    assert status["connectionState"] == "Connected"
    assert status["lastActivityTimeUtc"] == "2026-05-16T09:24:54.4491345Z"
    assert status["deviceStatus"] == "enabled"
    assert status["inSync"] is True
    assert status["onlineCheckedAtUtc"].endswith("Z")
