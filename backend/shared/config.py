from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class AppConfig:
    azure_web_jobs_storage: str
    storage_connection_string: str
    iot_hub_eventhub_connection: str
    iot_hub_eventhub_name: str
    iot_hub_connection_string: str
    iot_hub_name: str
    iot_hub_device_id: str
    storage_account_name: str
    raw_container: str
    parsed_container: str
    feeding_container: str
    backend_data_container: str
    error_container: str
    local_timezone: str
    default_target_daily_grams: float
    default_minimum_meaningful_intake_grams: float
    default_over_target_ratio: float
    min_feeding_interval_hours: int
    allow_unknown_rfid: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from_email: str
    smtp_use_tls: bool
    acs_connection_string: str
    acs_sender_email: str

    @classmethod
    def from_env(cls, require_secrets: bool = True) -> "AppConfig":
        storage = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage") or ""
        cfg = cls(
            azure_web_jobs_storage=os.getenv("AzureWebJobsStorage", ""),
            storage_connection_string=storage,
            iot_hub_eventhub_connection=os.getenv("IOT_HUB_EVENTHUB_CONNECTION", ""),
            iot_hub_eventhub_name=os.getenv("IOT_HUB_EVENTHUB_NAME", ""),
            iot_hub_connection_string=os.getenv("IOT_HUB_CONNECTION_STRING", ""),
            iot_hub_name=os.getenv("IOT_HUB_NAME", ""),
            iot_hub_device_id=os.getenv("IOT_HUB_DEVICE_ID", "feeder-esp32-01"),
            storage_account_name=os.getenv("STORAGE_ACCOUNT_NAME", ""),
            raw_container=os.getenv("RAW_CONTAINER", ""),
            parsed_container=os.getenv("PARSED_CONTAINER", "parsed-events"),
            feeding_container=os.getenv("FEEDING_CONTAINER", "feeding-events"),
            backend_data_container=os.getenv("BACKEND_DATA_CONTAINER", "backend-data"),
            error_container=os.getenv("ERROR_CONTAINER", "error-events"),
            local_timezone=os.getenv("LOCAL_TIMEZONE", "Australia/Perth"),
            default_target_daily_grams=float(os.getenv("DEFAULT_TARGET_DAILY_GRAMS", "60")),
            default_minimum_meaningful_intake_grams=float(os.getenv("DEFAULT_MINIMUM_MEANINGFUL_INTAKE_GRAMS", "2")),
            default_over_target_ratio=float(os.getenv("DEFAULT_OVER_TARGET_RATIO", "1.3")),
            min_feeding_interval_hours=int(os.getenv("MIN_FEEDING_INTERVAL_HOURS", "8")),
            allow_unknown_rfid=_bool_env("ALLOW_UNKNOWN_RFID", False),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_from_email=os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USERNAME", "")),
            smtp_use_tls=_bool_env("SMTP_USE_TLS", True),
            acs_connection_string=os.getenv("ACS_CONNECTION_STRING", ""),
            acs_sender_email=os.getenv("ACS_SENDER_EMAIL", ""),
        )
        if require_secrets:
            missing = []
            for name, value in {
                "STORAGE_CONNECTION_STRING or AzureWebJobsStorage": cfg.storage_connection_string,
                "IOT_HUB_EVENTHUB_CONNECTION": cfg.iot_hub_eventhub_connection,
                "IOT_HUB_EVENTHUB_NAME": cfg.iot_hub_eventhub_name,
                "IOT_HUB_NAME": cfg.iot_hub_name,
                "RAW_CONTAINER": cfg.raw_container,
            }.items():
                if not value:
                    missing.append(name)
            if missing:
                raise RuntimeError(f"Missing required app settings: {', '.join(missing)}")
        return cfg
