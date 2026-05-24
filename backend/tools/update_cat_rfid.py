from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT  # noqa: F401
from shared.config import AppConfig
from shared.table_repository import AzureTableRepository
from shared.time_utils import now_utc_iso
from shared.twin_service import TwinService, build_desired_properties_from_cat_profiles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cat-id", required=True)
    parser.add_argument("--new-cat-uid", required=True)
    parser.add_argument("--effective-time-utc", default=now_utc_iso())
    args = parser.parse_args()

    config = AppConfig.from_env()
    table = AzureTableRepository.from_config(config)
    result = table.update_rfid_mapping(args.cat_id, args.new_cat_uid, args.effective_time_utc)
    desired = build_desired_properties_from_cat_profiles(table.list_active_cats(), config)
    result["deviceTwinUpdateStatus"] = "skipped"
    if config.iot_hub_connection_string:
        TwinService(config).update_device_twin(config.iot_hub_device_id, desired)
        result["deviceTwinUpdateStatus"] = "updated"
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
