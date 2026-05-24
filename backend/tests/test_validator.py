from __future__ import annotations

from shared.validator import validate_feeding_event


def sample():
    return {
        "deviceId": "feeder-esp32-01",
        "catName": "CatA",
        "catUID": "B9BD18C9",
        "event": "feeding_complete",
        "feedingEndTime": 1778152085,
        "feedingStartTime": 1778152060,
        "durationSec": 25,
        "intakeGrams": 107.5,
    }


def test_valid_payload():
    errors, warnings, unsupported = validate_feeding_event(sample())
    assert errors == []
    assert warnings == []
    assert unsupported is False


def test_minor_duration_mismatch_is_warning():
    payload = sample()
    payload["durationSec"] = 24
    errors, warnings, unsupported = validate_feeding_event(payload)
    assert errors == []
    assert warnings
    assert unsupported is False


def test_negative_intake_is_error():
    payload = sample()
    payload["intakeGrams"] = -1
    errors, _, _ = validate_feeding_event(payload)
    assert "intakeGrams must be greater than or equal to 0" in errors


def test_unsynced_device_timestamp_is_error():
    payload = sample()
    payload["feedingStartTime"] = 41
    payload["feedingEndTime"] = 55
    errors, _, _ = validate_feeding_event(payload)
    assert "feedingStartTime and feedingEndTime must be after 2020-01-01T00:00:00Z" in errors
