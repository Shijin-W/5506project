from __future__ import annotations

import json

from _bootstrap import ROOT  # noqa: F401
from shared.config import AppConfig
from shared.table_repository import AzureTableRepository
from shared.twin_service import TwinService, build_desired_properties_from_cat_profiles


def main() -> None:
    config = AppConfig.from_env()
    table = AzureTableRepository.from_config(config)
    desired = build_desired_properties_from_cat_profiles(table.list_active_cats(), config)
    TwinService(config).update_device_twin(config.iot_hub_device_id, desired)
    print(json.dumps({"deviceId": config.iot_hub_device_id, "configVersion": desired["configVersion"], "desired": desired}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
