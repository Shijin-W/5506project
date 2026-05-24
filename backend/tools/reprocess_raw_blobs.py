from __future__ import annotations

import json

from _bootstrap import ROOT  # noqa: F401
from shared.blob_repository import AzureBlobRepository
from shared.config import AppConfig
from shared.status_service import StatusService
from shared.table_repository import AzureTableRepository


def iter_raw_messages(text: str):
    stripped = text.strip()
    if not stripped:
        return
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        for line in stripped.splitlines():
            line = line.strip()
            if line:
                yield line
        return

    if isinstance(parsed, list):
        for item in parsed:
            yield item
        return
    if isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
        for item in parsed["records"]:
            yield item
        return
    yield parsed


def main() -> None:
    config = AppConfig.from_env()
    if not config.raw_container:
        raise RuntimeError("RAW_CONTAINER is required")
    table = AzureTableRepository.from_config(config)
    blob = AzureBlobRepository.from_config(config)
    service = StatusService(table, blob, config)
    table.create_tables_if_missing()
    blob.create_containers_if_missing()

    summary = {
        "rawBlobsScanned": 0,
        "messagesParsed": 0,
        "validEventsProcessed": 0,
        "duplicatesSkipped": 0,
        "invalidPayloads": 0,
        "unknownRfidEvents": 0,
        "currentStatusUpdated": False,
        "backendJsonGenerated": False,
    }
    touched_dates: set[str] = set()

    for name in blob.list_blob_names(config.raw_container):
        summary["rawBlobsScanned"] += 1
        text = blob.read_text_blob(config.raw_container, name)
        for message in iter_raw_messages(text):
            result = service.process_raw_message(message)
            if result.status not in {"invalid_payload"}:
                summary["messagesParsed"] += 1
            if result.status == "processed":
                summary["validEventsProcessed"] += 1
            elif result.status == "duplicate":
                summary["duplicatesSkipped"] += 1
            elif result.status == "invalid_payload":
                summary["invalidPayloads"] += 1
            elif result.status == "unknown_rfid":
                summary["unknownRfidEvents"] += 1
            if result.local_date:
                touched_dates.add(result.local_date)

    for local_date in sorted(touched_dates):
        for cat in table.list_active_cats():
            service.recalculate_daily_summary(cat["catId"], local_date)
        service.update_backend_outputs(local_date)
    summary["currentStatusUpdated"] = bool(touched_dates)
    summary["backendJsonGenerated"] = bool(touched_dates)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
