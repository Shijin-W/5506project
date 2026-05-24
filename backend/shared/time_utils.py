from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def unix_to_utc_iso(timestamp: int | float) -> str:
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_iso_to_datetime(utc_iso: str) -> datetime:
    value = utc_iso
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_iso_to_local_date(utc_iso: str, timezone_name: str) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "Australia/Perth":
            tz = timezone(timedelta(hours=8), name="Australia/Perth")
        else:
            raise
    return utc_iso_to_datetime(utc_iso).astimezone(tz).date().isoformat()
