from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

try:
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import BlobServiceClient
except ImportError:
    ResourceExistsError = None
    BlobServiceClient = None

from .config import AppConfig
from .time_utils import now_utc_iso


def _json_default(value: Any):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


class AzureBlobRepository:
    def __init__(self, connection_string: str, config: AppConfig):
        if BlobServiceClient is None:
            raise RuntimeError("azure-storage-blob is not installed")
        self.service = BlobServiceClient.from_connection_string(connection_string)
        self.config = config

    @classmethod
    def from_config(cls, config: AppConfig) -> "AzureBlobRepository":
        return cls(config.storage_connection_string, config)

    def create_containers_if_missing(self) -> None:
        for name in [
            self.config.parsed_container,
            self.config.feeding_container,
            self.config.backend_data_container,
            self.config.error_container,
        ]:
            try:
                self.service.create_container(name)
            except Exception as exc:
                if ResourceExistsError and isinstance(exc, ResourceExistsError):
                    continue
                raise

    def write_json_blob(self, container: str, path: str, data: Any) -> None:
        client = self.service.get_blob_client(container=container, blob=path)
        client.upload_blob(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
            overwrite=True,
            content_type="application/json",
        )

    def read_text_blob(self, container: str, path: str) -> str:
        return self.service.get_blob_client(container=container, blob=path).download_blob().readall().decode("utf-8")

    def list_blob_names(self, container: str) -> list[str]:
        return [blob.name for blob in self.service.get_container_client(container).list_blobs()]

    def write_error_blob(self, error_payload: dict, local_date: str | None = None) -> None:
        date = local_date or now_utc_iso()[:10]
        path = f"year={date[:4]}/month={date[5:7]}/day={date[8:10]}/{error_payload['errorId']}.json"
        self.write_json_blob(self.config.error_container, path, error_payload)

    def write_parsed_event(self, event: dict) -> None:
        date = event["localDate"]
        path = f"year={date[:4]}/month={date[5:7]}/day={date[8:10]}/catId={event['catId']}/{event['eventId']}.json"
        self.write_json_blob(self.config.parsed_container, path, event)

    def write_feeding_event(self, event: dict) -> None:
        date = event["localDate"]
        path = f"year={date[:4]}/month={date[5:7]}/day={date[8:10]}/catId={event['catId']}/{event['eventId']}.json"
        self.write_json_blob(self.config.feeding_container, path, event)


class InMemoryBlobRepository:
    def __init__(self, config: AppConfig):
        self.config = config
        self.blobs: dict[tuple[str, str], Any] = {}

    def create_containers_if_missing(self) -> None:
        return None

    def write_json_blob(self, container: str, path: str, data: Any) -> None:
        self.blobs[(container, path)] = deepcopy(data)

    def read_text_blob(self, container: str, path: str) -> str:
        value = self.blobs[(container, path)]
        return json.dumps(value) if not isinstance(value, str) else value

    def list_blob_names(self, container: str) -> list[str]:
        return [path for blob_container, path in self.blobs if blob_container == container]

    write_error_blob = AzureBlobRepository.write_error_blob
    write_parsed_event = AzureBlobRepository.write_parsed_event
    write_feeding_event = AzureBlobRepository.write_feeding_event
