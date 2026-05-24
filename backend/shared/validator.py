from __future__ import annotations

from typing import Any

REQUIRED_FIELDS = [
    "deviceId",
    "catName",
    "catUID",
    "event",
    "feedingStartTime",
    "feedingEndTime",
    "durationSec",
    "intakeGrams",
]

MIN_VALID_UNIX_TIMESTAMP = 1577836800  # 2020-01-01T00:00:00Z


def validate_feeding_event(payload: dict[str, Any]) -> tuple[list[str], list[str], bool]:
    errors: list[str] = []
    warnings: list[str] = []

    missing_base = [field for field in ["deviceId", "event"] if field not in payload]
    if missing_base:
        errors.append(f"missing required fields: {', '.join(missing_base)}")
        return errors, warnings, False

    if payload.get("event") != "feeding_complete":
        return errors, warnings, True

    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
        return errors, warnings, False

    try:
        start = int(payload["feedingStartTime"])
        end = int(payload["feedingEndTime"])
    except (TypeError, ValueError):
        errors.append("feedingStartTime and feedingEndTime must be Unix timestamps")
        return errors, warnings, False

    if start > end:
        errors.append("feedingStartTime must be less than or equal to feedingEndTime")
    if start < MIN_VALID_UNIX_TIMESTAMP or end < MIN_VALID_UNIX_TIMESTAMP:
        errors.append("feedingStartTime and feedingEndTime must be after 2020-01-01T00:00:00Z")

    try:
        duration = int(payload["durationSec"])
    except (TypeError, ValueError):
        errors.append("durationSec must be numeric")
        duration = None

    if duration is not None and duration != end - start:
        warnings.append(f"durationSec mismatch: expected {end - start}, got {duration}")

    try:
        intake = float(payload["intakeGrams"])
    except (TypeError, ValueError):
        errors.append("intakeGrams must be numeric")
        return errors, warnings, False

    if intake < 0:
        errors.append("intakeGrams must be greater than or equal to 0")

    return errors, warnings, False
