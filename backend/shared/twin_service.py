from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

from .config import AppConfig
from .time_utils import now_utc_iso


def build_desired_properties_from_cat_profiles(cat_profiles: list[dict], config: AppConfig) -> dict:
    version = max([int(cat.get("configVersion", 1)) for cat in cat_profiles] or [1])
    cats = {
        cat["catId"]: {
            "catName": cat["catName"],
            "catUID": cat["currentCatUID"],
            "targetDailyGrams": float(cat.get("targetDailyGrams", config.default_target_daily_grams)),
            "minimumMeaningfulIntakeGrams": float(
                cat.get("minimumMeaningfulIntakeGrams", config.default_minimum_meaningful_intake_grams)
            ),
        }
        for cat in cat_profiles
    }
    return {
        "configVersion": version,
        "cats": cats,
        "feedingRules": {
            "minFeedingIntervalHours": config.min_feeding_interval_hours,
            "allowUnknownRfid": config.allow_unknown_rfid,
        },
    }


class TwinService:
    def __init__(self, config: AppConfig):
        self.config = config
        if not config.iot_hub_connection_string:
            raise RuntimeError("IOT_HUB_CONNECTION_STRING is required for device twin operations")
        self.parts = self._parse_connection_string(config.iot_hub_connection_string)
        self.host = self.parts["HostName"]

    def update_device_twin(self, device_id: str, desired_properties: dict) -> dict:
        return self._request(
            "PATCH",
            f"https://{self.host}/twins/{urllib.parse.quote(device_id)}?api-version=2021-04-12",
            {"properties": {"desired": desired_properties}},
            {"If-Match": "*"},
        )

    def get_device_twin(self, device_id: str) -> dict:
        return self._request(
            "GET",
            f"https://{self.host}/twins/{urllib.parse.quote(device_id)}?api-version=2021-04-12",
        )

    def send_c2d_message(self, device_id: str, message: dict) -> dict:
        return self._request(
            "POST",
            f"https://{self.host}/devices/{urllib.parse.quote(device_id)}/messages/devicebound?api-version=2021-04-12",
            message,
            {"iothub-ack": "none"},
        )

    def compare_desired_reported_config_version(self, device_id: str) -> dict:
        twin = self.get_device_twin(device_id)
        props = twin.get("properties", {})
        desired = props.get("desired", {})
        reported = props.get("reported", {})
        desired_version = desired.get("configVersion")
        reported_version = reported.get("configVersionApplied")
        connection_state = twin.get("connectionState", "Unknown")
        last_activity_time = twin.get("lastActivityTime")
        return {
            "deviceId": device_id,
            "online": str(connection_state).lower() == "connected",
            "connectionState": connection_state,
            "lastActivityTimeUtc": last_activity_time,
            "deviceStatus": twin.get("status", "unknown"),
            "onlineCheckedAtUtc": now_utc_iso(),
            "desiredConfigVersion": desired_version,
            "reportedConfigVersionApplied": reported_version,
            "inSync": desired_version == reported_version,
            "lastSyncTime": reported.get("lastSyncTime"),
            "knownCats": reported.get("knownCats", {}),
        }

    @staticmethod
    def _parse_connection_string(connection_string: str) -> dict[str, str]:
        parts = {}
        for item in connection_string.split(";"):
            if "=" in item:
                key, value = item.split("=", 1)
                parts[key] = value
        required = {"HostName", "SharedAccessKeyName", "SharedAccessKey"}
        missing = required - set(parts)
        if missing:
            raise ValueError(f"IoT Hub connection string is missing: {', '.join(sorted(missing))}")
        return parts

    def _sas_token(self) -> str:
        expiry = int(time.time()) + 3600
        resource_uri = self.host.lower()
        encoded_uri = urllib.parse.quote(resource_uri, safe="")
        string_to_sign = f"{encoded_uri}\n{expiry}".encode("utf-8")
        key = base64.b64decode(self.parts["SharedAccessKey"])
        signature = base64.b64encode(hmac.new(key, string_to_sign, hashlib.sha256).digest())
        encoded_signature = urllib.parse.quote(signature)
        return (
            f"SharedAccessSignature sr={encoded_uri}&sig={encoded_signature}"
            f"&se={expiry}&skn={self.parts['SharedAccessKeyName']}"
        )

    def _request(self, method: str, url: str, body: dict | None = None, headers: dict | None = None) -> dict:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        req_headers = {
            "Authorization": self._sas_token(),
            "Content-Type": "application/json",
        }
        if headers:
            req_headers.update(headers)
        request = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else {}
