from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from .time_utils import now_utc_iso


@dataclass
class ParsedMessage:
    payload: dict[str, Any]
    metadata: dict[str, Any]
    raw: Any


def _decode_bytes(value: bytes) -> str:
    return value.decode("utf-8")


def _parse_json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = _decode_bytes(value)
    if isinstance(value, str):
        return json.loads(value)
    raise ValueError(f"Unsupported message type: {type(value).__name__}")


def parse_iothub_message(raw: Any) -> ParsedMessage:
    original = raw
    wrapper = _parse_json_payload(raw)
    metadata = {"ingestedAtUtc": now_utc_iso()}

    if "EnqueuedTimeUtc" in wrapper:
        metadata["iotHubEnqueuedTimeUtc"] = wrapper.get("EnqueuedTimeUtc")
    system_props = wrapper.get("SystemProperties") or wrapper.get("systemProperties") or {}
    if isinstance(system_props, dict):
        metadata["connectionDeviceId"] = system_props.get("connectionDeviceId") or system_props.get("iothub-connection-device-id")
        metadata["iotHubEnqueuedTimeUtc"] = metadata.get("iotHubEnqueuedTimeUtc") or system_props.get("enqueuedTime")

    if "Body" in wrapper:
        body = wrapper["Body"]
        if isinstance(body, bytes):
            body = _decode_bytes(body)
        if not isinstance(body, str):
            raise ValueError("IoT Hub wrapper Body must be a base64 string")
        decoded = base64.b64decode(body).decode("utf-8")
        payload = _parse_json_payload(decoded)
        return ParsedMessage(payload=payload, metadata=metadata, raw=original)

    return ParsedMessage(payload=wrapper, metadata=metadata, raw=original)
