# Smart Multi-Cat Feeder Azure Backend

Backend-only Azure Functions implementation for IoT Hub feeding messages.

## Deployed Azure Resources

- Resource group: `IOT-Group17`
- IoT Hub: `multicatfeeder`
- IoT Hub device: `feeder-esp32-01`
- Existing data storage account: `multicatproject`
- Existing raw container: `raw-iot-data`
- Deployed Function App: `multicatfeeder-func-24417624`
- Function runtime storage account: `mcfbackend24417624`

The Function runtime storage account is separate from the existing project data storage. Backend tables, raw data, and backend JSON outputs remain in `multicatproject`.

## What Is Implemented

- IoT Hub/Event Hub-triggered processing for `feeding_complete`
- Direct JSON and IoT Hub wrapper `Body` base64 parsing
- Azure Table Storage models:
  - `CatProfiles`
  - `RfidMap`
  - `RfidHistory`
  - `FeedingEvents`
  - `DailySummary`
  - `CurrentStatus`
  - `Alerts`
- Blob outputs:
  - `backend-data/current-status.json`
  - `backend-data/daily-summary/YYYY-MM-DD.json`
  - `backend-data/recent-feedings/YYYY-MM-DD.json`
  - `backend-data/alerts/latest.json`
- Backfill tool for existing raw blobs
- RFID update script and protected admin API
- Device Twin desired-property sync
- Backend testing APIs only; no frontend UI

Note: the runtime entry module is `backend_app.py`. The project uses classic `function.json` folders for Azure Functions indexing because a root `function_app.py` file causes Azure's Python v2 worker indexing path to take over.

## Local Setup

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
Copy-Item local.settings.template.json local.settings.json
```

Fill `local.settings.json` with real Azure values. Do not commit it.

Required settings:

- `AzureWebJobsStorage`
- `STORAGE_CONNECTION_STRING`
- `IOT_HUB_EVENTHUB_CONNECTION`
- `IOT_HUB_EVENTHUB_NAME`
- `IOT_HUB_CONNECTION_STRING`
- `IOT_HUB_NAME`
- `IOT_HUB_DEVICE_ID`
- `RAW_CONTAINER`
- `LOCAL_TIMEZONE`

## Azure Inspection

Run these in a shell where Azure CLI is available:

```powershell
az account show
az group list -o table
az iot hub list -o table
az storage account list -o table
az functionapp list -o table
az storage container list --account-name <storage-account-name> -o table
```

## Seed Initial Data

```powershell
$env:AzureWebJobsStorage="<storage connection string>"
$env:STORAGE_CONNECTION_STRING="<storage connection string>"
$env:IOT_HUB_CONNECTION_STRING="<IoT Hub service connection string>"
$env:IOT_HUB_NAME="<hub name>"
$env:IOT_HUB_DEVICE_ID="feeder-esp32-01"
$env:RAW_CONTAINER="<raw container>"
python tools/seed_cat_profiles.py
```

## Run Sample Backend Test Script

```powershell
python tools/test_with_sample_events.py
```

## Backfill Existing Raw Blobs

```powershell
python tools/reprocess_raw_blobs.py
```

The tool is idempotent. It uses:

```text
{deviceId}-{catId}-{feedingEndTime}
```

as the feeding event key.

## RFID Update

```powershell
python tools/update_cat_rfid.py --cat-id cat_a --new-cat-uid A1B2C3D4 --effective-time-utc 2026-05-20T10:00:00Z
```

This preserves old RFID history, updates `CatProfiles.currentCatUID`, increments `configVersion`, and pushes Device Twin desired properties when `IOT_HUB_CONNECTION_STRING` is configured.

## Deploy

After Azure CLI and Azure Functions Core Tools are available:

```powershell
func azure functionapp publish <function-app-name>
```

Then configure Function App settings with the values from `local.settings.template.json`.
