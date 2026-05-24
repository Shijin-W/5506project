from __future__ import annotations

import json

from _bootstrap import ROOT  # noqa: F401
from shared.blob_repository import AzureBlobRepository
from shared.config import AppConfig
from shared.table_repository import AzureTableRepository
from shared.twin_service import TwinService, build_desired_properties_from_cat_profiles


def main() -> None:
    config = AppConfig.from_env()
    table = AzureTableRepository.from_config(config)
    blob = AzureBlobRepository.from_config(config)
    table.create_tables_if_missing()
    blob.create_containers_if_missing()
    table.seed_cat_profiles()
    result = {"tablesSeeded": True, "containersReady": True, "deviceTwinUpdateStatus": "skipped"}

    if config.iot_hub_connection_string:
        desired = build_desired_properties_from_cat_profiles(table.list_active_cats(), config)
        TwinService(config).update_device_twin(config.iot_hub_device_id, desired)
        result["deviceTwinUpdateStatus"] = "updated"
        result["configVersion"] = desired["configVersion"]

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
