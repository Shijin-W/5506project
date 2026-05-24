from __future__ import annotations

import base64
import json

from shared.parser import parse_iothub_message
from shared.time_utils import unix_to_utc_iso


def test_parse_direct_json():
    payload = {"deviceId": "feeder-esp32-01", "catUID": "B9BD18C9", "event": "feeding_complete"}
    parsed = parse_iothub_message(json.dumps(payload))
    assert parsed.payload == payload


def test_parse_iothub_wrapper_body():
    inner = {"deviceId": "feeder-esp32-01", "catUID": "B9BD18C9", "event": "feeding_complete"}
    wrapper = {
        "EnqueuedTimeUtc": "2026-05-07T11:08:06Z",
        "SystemProperties": {"connectionDeviceId": "feeder-esp32-01"},
        "Body": base64.b64encode(json.dumps(inner).encode("utf-8")).decode("utf-8"),
    }
    parsed = parse_iothub_message(wrapper)
    assert parsed.payload == inner
    assert parsed.metadata["connectionDeviceId"] == "feeder-esp32-01"


def test_known_timestamp_conversion():
    assert unix_to_utc_iso(1778152085) == "2026-05-07T11:08:05Z"
