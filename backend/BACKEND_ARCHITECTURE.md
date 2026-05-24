# Multicat Feeder Backend Architecture

本文档整理当前 `multicatfeeder` 项目的后端框架、Azure Functions 入口、数据存储设计、IoT 消息处理流程、告警逻辑、Device Twin 同步、邮件通知和前端数据接口。

## 1. Overall Architecture

后端是 Azure Functions Python 项目，使用经典 `function.json` 目录结构，而不是 Python v2 decorator 模式。

每个 Function 文件夹包含：

- `function.json`: Azure Functions binding 配置
- `__init__.py`: Function 入口，通常只转发到 `backend_app.py`

真实业务逻辑集中在：

- `backend_app.py`
- `shared/status_service.py`
- `shared/table_repository.py`
- `shared/blob_repository.py`
- `shared/parser.py`
- `shared/validator.py`
- `shared/alert_service.py`
- `shared/email_service.py`
- `shared/twin_service.py`
- `shared/time_utils.py`

当前后端使用：

- Azure Functions
- Azure IoT Hub Event Hub compatible endpoint
- Azure Table Storage
- Azure Blob Storage
- Azure IoT Hub Device Twin
- Azure IoT Hub Cloud-to-Device messages
- Azure Communication Email or SMTP, optional

## 2. Deployed Azure Resources

当前部署资源：

| Resource | Value |
|---|---|
| Resource group | `IOT-Group17` |
| Function App | `multicatfeeder-func-24417624` |
| IoT Hub | `multicatfeeder` |
| IoT Hub device | `feeder-esp32-01` |
| Project data storage account | `multicatproject` |
| Function runtime storage account | `mcfbackend24417624` |

项目数据和 Function runtime storage 是分开的。Table、Blob、前端静态站点数据主要在 `multicatproject`。

## 3. Runtime and Dependencies

`host.json` 使用 Azure Functions runtime v4 extension bundle:

```json
{
  "version": "2.0",
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.0.0, 5.0.0)"
  }
}
```

Python dependencies:

```txt
azure-functions==1.24.0
azure-data-tables
azure-storage-blob
azure-communication-email
tzdata
```

## 4. Configuration

配置类是 `AppConfig`，从环境变量读取。

Required settings:

| Setting | Purpose |
|---|---|
| `AzureWebJobsStorage` | Azure Functions runtime storage |
| `STORAGE_CONNECTION_STRING` | Project data storage connection string |
| `IOT_HUB_EVENTHUB_CONNECTION` | IoT Hub Event Hub compatible connection |
| `IOT_HUB_EVENTHUB_NAME` | IoT Hub Event Hub compatible name |
| `IOT_HUB_CONNECTION_STRING` | IoT Hub service connection string for twin/C2D |
| `IOT_HUB_NAME` | IoT Hub name |
| `IOT_HUB_DEVICE_ID` | Target feeder device id |
| `RAW_CONTAINER` | Raw IoT data container |

Business defaults:

| Setting | Default | Purpose |
|---|---:|---|
| `LOCAL_TIMEZONE` | `Australia/Perth` | Local date calculation |
| `DEFAULT_TARGET_DAILY_GRAMS` | `60` | Default cat daily target |
| `DEFAULT_MINIMUM_MEANINGFUL_INTAKE_GRAMS` | `2` | Very-low threshold |
| `DEFAULT_OVER_TARGET_RATIO` | `1.3` | Over-target threshold multiplier |
| `MIN_FEEDING_INTERVAL_HOURS` | `8` | Device feeding rule |
| `ALLOW_UNKNOWN_RFID` | `False` | Device feeding rule |

Email settings:

| Setting | Purpose |
|---|---|
| `ACS_CONNECTION_STRING` | Azure Communication Email connection |
| `ACS_SENDER_EMAIL` | ACS sender email |
| `SMTP_HOST` | SMTP server |
| `SMTP_PORT` | SMTP port |
| `SMTP_USERNAME` | SMTP username |
| `SMTP_PASSWORD` | SMTP password |
| `SMTP_FROM_EMAIL` | SMTP sender |
| `SMTP_USE_TLS` | SMTP TLS toggle |

## 5. Backend Layering

### 5.1 Trigger Layer

Function folders define Azure trigger bindings:

- HTTP trigger
- Timer trigger
- Event Hub trigger

The `__init__.py` files call functions in `backend_app.py`.

### 5.2 API / Orchestration Layer

`backend_app.py` handles:

- HTTP parameter parsing
- route parameter parsing
- JSON response formatting
- range validation
- calling repository/service functions
- alert insertion with notification
- Device Twin sync orchestration

### 5.3 Business Service Layer

`shared/status_service.py` handles:

- IoT message processing
- event validation and normalization
- feeding event persistence
- daily summary recalculation
- current status update
- alert generation and auto-resolution
- heartbeat health check handling
- RFID scan/rebind processing
- frontend output refresh

### 5.4 Repository Layer

`shared/table_repository.py` wraps Azure Table Storage.

`shared/blob_repository.py` wraps Azure Blob Storage.

Both modules also have in-memory variants for local unit tests.

### 5.5 Helper Layer

| Module | Responsibility |
|---|---|
| `parser.py` | Parse direct JSON or IoT Hub wrapper body |
| `validator.py` | Validate feeding event payload |
| `alert_service.py` | Build alerts and map severity |
| `email_service.py` | Email subscription and alert notification |
| `twin_service.py` | Device Twin, desired config, C2D messages |
| `time_utils.py` | UTC ISO, Unix timestamp, local date conversion |

## 6. Azure Functions

| Function | Trigger | Route / Schedule | Purpose |
|---|---|---|---|
| `process_iothub_feeding_event` | EventHub | IoT Hub Event Hub compatible endpoint | Process ESP32 telemetry |
| `check_daily_feeding_status` | Timer | `0 50 15 * * *` | Daily feeding status check |
| `health` | HTTP anonymous | `GET /api/health` | Health check |
| `get_current_status` | HTTP function key | `GET /api/current-status` | Current cat status |
| `get_daily_summary` | HTTP function key | `GET /api/daily-summary?date=YYYY-MM-DD` | Daily summary by date |
| `get_recent_feedings` | HTTP function key | `GET /api/recent-feedings?date=YYYY-MM-DD` | Feeding records by date |
| `get_analytics_range` | HTTP function key | `GET /api/analytics/range?startDate=&endDate=` | Range analytics |
| `get_alerts` | HTTP function key | `GET /api/alerts?date=YYYY-MM-DD` | Alerts by date |
| `get_alert_history` | HTTP function key | `GET /api/alerts/history?startDate=&endDate=` | Alert history range |
| `resolve_alert` | HTTP function key | `POST /api/alerts/{alertId}/resolve?date=` | Resolve alert |
| `get_frontend_data` | HTTP function key | `GET /api/frontend-data?partition=` | Frontend cache data |
| `alert_subscriptions` | HTTP function key | `GET/POST /api/alert-subscriptions` | Email subscriptions |
| `get_device_config_status` | HTTP function key | `GET /api/device-config-status` | Device Twin sync status |
| `admin_update_cat_rfid` | HTTP function key | `POST /api/cats/{catId}/rfid` | Update cat RFID |
| `admin_update_cat_profile` | HTTP function key | `POST/PATCH /api/cats/{catId}/profile` | Update cat profile |
| `admin_start_rfid_rebind_scan` | HTTP function key | `POST /api/cats/{catId}/rfid/rebind-scan` | Start RFID scan via C2D |
| `admin_sync_device_twin_config` | HTTP function key | `POST /api/device-twin/sync` | Manually sync desired config |

## 7. Azure Table Storage Model

The backend uses these tables:

| Table | Purpose |
|---|---|
| `CatProfiles` | Active cat profile master data |
| `RfidMap` | Active RFID UID to cat mapping |
| `RfidHistory` | RFID mapping history |
| `FeedingEvents` | Normalized feeding events |
| `DailySummary` | Per-cat daily totals/status |
| `CurrentStatus` | Current dashboard status per cat |
| `Alerts` | Open/resolved alerts |
| `FrontendData` | Precomputed frontend cache rows |
| `RfidOperations` | RFID rebind operation state |
| `EmailSubscriptions` | Email alert subscribers |
| `AlertEmailNotifications` | Alert email delivery state |

Initial cats:

| catId | catName | currentCatUID | targetDailyGrams |
|---|---|---|---:|
| `cat_a` | `CatA` | `B9BD18C9` | `60` |
| `cat_b` | `CatB` | `0420D6BAFD1691` | `60` |

## 8. Blob Storage Outputs

Blob containers:

| Container | Purpose |
|---|---|
| `parsed-events` | Normalized event archive |
| `feeding-events` | Feeding event archive |
| `backend-data` | JSON outputs for frontend/debugging |
| `error-events` | Invalid payloads and sensor/RFID errors |

Path patterns:

```txt
parsed-events/year=YYYY/month=MM/day=DD/catId={catId}/{eventId}.json
feeding-events/year=YYYY/month=MM/day=DD/catId={catId}/{eventId}.json
error-events/year=YYYY/month=MM/day=DD/{errorId}.json
```

`backend-data` outputs:

```txt
current-status.json
daily-summary/{localDate}.json
recent-feedings/{localDate}.json
alerts/latest.json
```

## 9. IoT Message Processing

Entry point:

```txt
process_iothub_feeding_event(events)
```

Main flow:

1. Event Hub trigger receives one or more IoT Hub events.
2. Each event body is passed to `StatusService.process_raw_message`.
3. `parse_iothub_message` parses either direct JSON or IoT Hub wrapper JSON.
4. The payload is routed by `payload["event"]`.
5. Supported events:
   - `feeding_complete`
   - `heartbeat`
   - `scan_status`
   - `tag_scanned`
6. Unsupported events are ignored.
7. Valid feeding events are normalized, persisted, summarized, and published to frontend outputs.
8. Invalid events generate error blobs and alerts.

Supported message formats:

Direct JSON:

```json
{
  "deviceId": "FEEDER-01",
  "event": "feeding_complete"
}
```

IoT Hub wrapper:

```json
{
  "Body": "base64-encoded-json",
  "SystemProperties": {
    "connectionDeviceId": "feeder-esp32-01"
  }
}
```

Extracted metadata:

- `ingestedAtUtc`
- `iotHubEnqueuedTimeUtc`
- `connectionDeviceId`

## 10. Feeding Event Validation

Required fields:

```txt
deviceId
catName
catUID
event
feedingStartTime
feedingEndTime
durationSec
intakeGrams
```

Validation rules:

- `event` must be `feeding_complete`.
- `feedingStartTime` and `feedingEndTime` must be Unix timestamps.
- timestamps must be after `2020-01-01T00:00:00Z`.
- start time must be earlier than or equal to end time.
- `durationSec` must be numeric.
- if `durationSec != feedingEndTime - feedingStartTime`, a warning is recorded but the event is still accepted.
- `intakeGrams` must be numeric.
- `intakeGrams` must be greater than or equal to `0`.

Special case:

- If `event == feeding_complete` but `intakeGrams is null`, the backend treats it as a scale sensor error instead of a valid feeding event.

## 11. Feeding Event Normalization

Normalized event keys:

```txt
PartitionKey = {catId}_{localDate}
RowKey = {deviceId}-{catId}-{feedingEndTimestamp}
```

Normalized fields:

```txt
eventId
deviceId
catId
catName
catUID
eventType = feeding_complete
feedingStartTimestamp
feedingEndTimestamp
feedingStartTimeUtc
feedingEndTimeUtc
localDate
durationSec
intakeGrams
isValid
validationErrors
iotHubEnqueuedTimeUtc
connectionDeviceId
ingestedAtUtc
createdAtUtc
```

`localDate` is calculated from `feedingEndTimeUtc` using `LOCAL_TIMEZONE`, currently `Australia/Perth`.

Deduplication:

- `FeedingEvents` uses `PartitionKey + RowKey`.
- Duplicate inserts return `duplicate`.
- Duplicate events do not recalculate daily totals again.

## 12. Daily Summary

Daily summary is recalculated after a new feeding event is inserted:

```txt
recalculate_daily_summary(catId, localDate)
```

The service:

1. Loads cat profile.
2. Loads all feeding events for that cat/date.
3. Sorts events by `feedingEndTimestamp`.
4. Calculates total intake.
5. Calculates feeding count.
6. Sets first/last feeding timestamps.
7. Calculates `todayStatus`.
8. Upserts `DailySummary`.
9. Upserts `CurrentStatus`.
10. Resolves old feeding alerts if status is normal.
11. Inserts a new status alert if needed.

Daily summary fields:

```txt
PartitionKey = catId
RowKey = localDate

catId
catName
date
totalIntakeGrams
feedingCount
firstFeedingCompletedTimeUtc
lastFeedingCompletedTimeUtc
targetDailyGrams
minimumMeaningfulIntakeGrams
overTargetRatio
todayStatus
updatedAtUtc
```

Status calculation:

```txt
total == 0                         -> not_eaten
total < minimum                    -> very_low_intake
total < target                     -> under_target
total <= target * overTargetRatio  -> normal
otherwise                          -> over_target
```

## 13. Current Status

`CurrentStatus` stores one row per active cat.

Keys:

```txt
PartitionKey = CURRENT
RowKey = catId
```

Fields:

```txt
catId
catName
currentCatUID
lastFeedingCompletedTimeUtc
lastIntakeGrams
todayIntakeGrams
targetDailyGrams
todayStatus
updatedAtUtc
```

This table is a primary data source for Dashboard and Cat Management.

## 14. Daily Timer

Function:

```txt
check_daily_feeding_status
```

Schedule:

```txt
0 50 15 * * *
```

This runs at 15:50 UTC, which is 23:50 in Perth.

Purpose:

1. Determine current Perth local date.
2. Iterate all active cats.
3. Create a 0g daily summary if no summary exists.
4. Update `CurrentStatus`.
5. Generate feeding-status alerts, such as `not_eaten`.
6. Refresh backend Blob outputs and `FrontendData`.

## 15. Alert System

Alerts are stored in the `Alerts` table.

Keys:

```txt
PartitionKey = localDate
RowKey = alertId
```

Alert fields:

```txt
alertId
catId
catName
alertType
severity
message
createdAtUtc
status
resolvedAtUtc
resolvedBy
updatedAtUtc
```

Alert id format:

```txt
alert-{catId or system}-{date}-{suffix}
```

Supported alert types:

| alertType | severity |
|---|---|
| `invalid_payload` | `high` |
| `unknown_rfid` | `high` |
| `not_eaten` | `high` |
| `very_low_intake` | `medium` |
| `under_target` | `low` |
| `over_target` | `medium` |
| `device_config_out_of_sync` | `medium` |
| `device_health_error` | `high` |
| `processing_error` | `high` |
| `scale_sensor_error` | `high` |

Feeding status alert messages:

- `not_eaten`: no completed feeding recorded.
- `very_low_intake`: total intake below minimum meaningful threshold.
- `under_target`: total intake below daily target.
- `over_target`: total intake above configured over-target threshold.

Auto-resolution:

- If a cat's daily status becomes `normal`, open feeding alerts for that cat/date are resolved.
- Resolved alert types:
  - `not_eaten`
  - `very_low_intake`
  - `under_target`
  - `over_target`
- `resolvedBy = auto_feeding_normal`

Manual resolution:

```txt
POST /api/alerts/{alertId}/resolve?date=YYYY-MM-DD
```

Manual resolution sets:

```txt
status = resolved
resolvedAtUtc = now
resolvedBy = manual
updatedAtUtc = now
```

## 16. Heartbeat Handling

If payload event is `heartbeat`, the backend reads:

```txt
timestamp
deviceId
rfid_ok
tof_ok
motor_ok
scale_ok
load_cell_ok
```

Failed checks generate `device_health_error` alerts.

Recovered checks can auto-resolve matching same-day device health alerts.

Health check labels:

| Payload key | Alert label |
|---|---|
| `rfid_ok` | `rfid` |
| `tof_ok` | `tof` |
| `motor_ok` | `motor` |
| `scale_ok` | `scale` |
| `load_cell_ok` | `load_cell` |

## 17. Error Handling

### 17.1 Invalid Payload

Invalid payload flow:

1. Create `invalid_payload` error id based on payload hash.
2. Write error blob.
3. Insert `invalid_payload` alert.
4. Return processing result `invalid_payload`.

### 17.2 Unknown RFID

Unknown RFID flow:

1. Extract `catUID`.
2. Write error blob.
3. Insert `unknown_rfid` alert.
4. Do not write feeding event.

### 17.3 Scale Sensor Error

Scale sensor error flow:

1. Triggered when `feeding_complete` has `intakeGrams = null`.
2. Resolve local date from feeding end time when possible.
3. Try to identify cat by RFID.
4. Write error blob.
5. Insert `scale_sensor_error` alert.
6. Do not write feeding event.

### 17.4 Processing Exception

Unhandled processing exceptions in EventHub trigger:

1. Are logged.
2. Generate `processing_error` alert.

## 18. FrontendData Cache

`update_backend_outputs(localDate)` writes both Blob JSON and `FrontendData` table partitions.

FrontendData partitions:

```txt
current-status
daily-summary_{localDate}
recent-feedings_{localDate}
alerts_latest
```

Generic row structure:

```txt
PartitionKey
RowKey
dataType
date
payloadJson
updatedAtUtc
```

The backend also flattens simple payload fields into the row for direct frontend use.

Important note:

`alerts_latest` is generated when a specific local date is refreshed. It may not represent the actual global latest alert history. Dashboard should use `/api/alerts/history` for recent alerts.

## 19. Analytics Range API

Endpoint:

```txt
GET /api/analytics/range?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
```

Validation:

- `startDate` is required.
- `endDate` is required.
- `startDate <= endDate`.
- Date range cannot exceed 366 days.

Response:

```txt
startDate
endDate
catSummaries
dailySeries
feedingRecords
totals
```

`catSummaries`:

```txt
catId
catName
totalIntakeGrams
feedingCount
averageIntakeGrams
targetDailyGrams
daysWithData
```

`dailySeries`:

```txt
date
catId
catName
totalIntakeGrams
feedingCount
```

`feedingRecords`:

```txt
eventId
catId
catName
catUID
feedingStartTimeUtc
feedingEndTimeUtc
durationSec
intakeGrams
localDate
```

`totals`:

```txt
totalIntakeGrams
feedingCount
averageIntakeGrams
```

## 20. Alert History API

Endpoint:

```txt
GET /api/alerts/history?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
```

Validation:

- `startDate` is required.
- `endDate` is required.
- `startDate <= endDate`.
- Date range cannot exceed 366 days.

Logic:

1. Iterate each date in the range.
2. Query `Alerts` by `PartitionKey = date`.
3. Strip Azure Table internal fields.
4. Ensure `date` is present.
5. Sort by `createdAtUtc` and `alertId` descending.
6. Count open and resolved alerts.

Response:

```txt
startDate
endDate
alerts
totals.alertCount
totals.openCount
totals.resolvedCount
```

## 21. Device Twin

`TwinService` uses IoT Hub REST API with SAS token.

Supported operations:

- `update_device_twin`
- `get_device_twin`
- `send_c2d_message`
- `compare_desired_reported_config_version`

Desired properties are built from active cat profiles:

```json
{
  "configVersion": 1,
  "cats": {
    "cat_a": {
      "catName": "CatA",
      "catUID": "B9BD18C9",
      "targetDailyGrams": 60,
      "minimumMeaningfulIntakeGrams": 2
    }
  },
  "feedingRules": {
    "minFeedingIntervalHours": 8,
    "allowUnknownRfid": false
  }
}
```

`configVersion` is the max `configVersion` among active cat profiles.

`GET /api/device-config-status`:

1. Reads Device Twin.
2. Compares desired `configVersion` with reported `configVersionApplied`.
3. Returns online state, connection state, last activity time, known cats and config sync state.
4. If not in sync, inserts a `device_config_out_of_sync` alert.

Returned fields include:

```txt
deviceId
online
connectionState
lastActivityTimeUtc
deviceStatus
onlineCheckedAtUtc
desiredConfigVersion
reportedConfigVersionApplied
inSync
lastSyncTime
knownCats
```

## 22. Cat Profile Update

Endpoint:

```txt
PATCH /api/cats/{catId}/profile
POST /api/cats/{catId}/profile
```

Body:

```json
{
  "catName": "New Name",
  "targetDailyGrams": 70
}
```

Rules:

- At least `catName` or `targetDailyGrams` is required.
- `catName` cannot be empty.
- `targetDailyGrams` must be greater than 0.

Update flow:

1. Load cat profile.
2. Update `catName` and/or `targetDailyGrams`.
3. Increment `configVersion`.
4. Upsert `CatProfiles`.
5. Update `CurrentStatus`.
6. Update active `RfidMap`.
7. Update active `RfidHistory`.
8. If today's `DailySummary` exists, update its cat name and target.
9. Refresh backend outputs for today's local date.
10. Rebuild Device Twin desired properties.
11. Patch Device Twin.

Response:

```txt
catId
catName
currentCatUID
targetDailyGrams
configVersion
deviceTwinUpdateStatus
```

## 23. RFID Update

Endpoint:

```txt
POST /api/cats/{catId}/rfid
```

Body:

```json
{
  "newCatUID": "A1B2C3D4",
  "effectiveTimeUtc": "2026-05-18T10:00:00Z"
}
```

Flow:

1. Validate cat exists.
2. Validate new UID is not active for another cat.
3. Mark old `RfidMap` inactive.
4. Mark old active `RfidHistory` rows inactive.
5. Insert new active `RfidMap`.
6. Insert new active `RfidHistory`.
7. Update `CatProfiles.currentCatUID`.
8. Increment `configVersion`.
9. Update `CurrentStatus.currentCatUID`.
10. Rebuild and patch Device Twin desired config.

Response:

```txt
catId
oldCatUID
newCatUID
configVersion
deviceTwinUpdateStatus
```

## 24. RFID Rebind Scan

Endpoint:

```txt
POST /api/cats/{catId}/rfid/rebind-scan
```

Body:

```json
{
  "timeoutSec": 120,
  "operationId": "optional"
}
```

Tray mapping:

| catId | trayIndex |
|---|---:|
| `cat_a` | `0` |
| `cat_b` | `1` |

Flow:

1. Validate cat exists.
2. Validate tray mapping exists.
3. Create RFID operation in `RfidOperations`.
4. Build C2D command.
5. Send command to device.
6. Update operation status to `command_sent` or `failed`.

C2D command:

```json
{
  "action": "start_scan",
  "operationId": "...",
  "trayIndex": 0,
  "timeoutSec": 120
}
```

Operation fields:

```txt
PartitionKey = RFID_REBIND
RowKey = operationId

operationId
operationType = rebind_rfid
status
targetCatId
targetCatName
oldCatUID
trayIndex
timeoutSec
createdAtUtc
updatedAtUtc
expiresAtUtc
commandJson
commandSentAtUtc
failureReason
```

Supported device follow-up events:

- `scan_status`
- `tag_scanned`

`scan_status` mappings:

| Device status | Operation status |
|---|---|
| `armed` | `armed` |
| `scanned` | `scan_received` |
| `timeout` | `expired` |
| `cancelled` | `cancelled` |
| `failed` | `failed` |

`tag_scanned` flow:

1. Validate `operationId` and `uid`.
2. Load RFID operation.
3. Reject expired operation.
4. Reject non-active operation status.
5. Reject UID already active for another cat.
6. Apply `update_rfid_mapping`.
7. Patch Device Twin desired config.
8. Mark operation as `applied`.
9. Refresh backend outputs.

## 25. Email Notification

Endpoint:

```txt
GET /api/alert-subscriptions
GET /api/alert-subscriptions?email=user@example.com
POST /api/alert-subscriptions
```

POST body:

```json
{
  "email": "user@example.com",
  "action": "subscribe"
}
```

Supported actions:

```txt
subscribe
unsubscribe
toggle
active
inactive
```

Subscription row:

```txt
PartitionKey = EMAIL_SUBS
RowKey = sha256(normalizedEmail)

email
emailHash
status
minSeverity
createdAtUtc
updatedAtUtc
```

Notification rules:

- Only alerts with severity >= `medium` are sent.
- Each subscriber can have its own `minSeverity`.
- Low alerts are not sent by default.
- `AlertEmailNotifications` prevents duplicate sends.
- New active subscribers receive recent open medium/high backlog alerts, max 4.

Delivery providers:

1. Azure Communication Email, if `ACS_CONNECTION_STRING` and `ACS_SENDER_EMAIL` are configured.
2. SMTP, if SMTP settings are configured.
3. Otherwise notification status becomes `email_not_configured`.

Notification row:

```txt
PartitionKey = alertId
RowKey = emailHash

alertId
emailHash
email
severity
status
createdAtUtc
updatedAtUtc
sentAtUtc
error
```

## 26. Frontend-Facing API Summary

Main frontend APIs:

```txt
GET /api/frontend-data?partition=current-status
GET /api/frontend-data?partition=daily-summary_YYYY-MM-DD
GET /api/frontend-data?partition=recent-feedings_YYYY-MM-DD
GET /api/analytics/range?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
GET /api/alerts/history?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
GET /api/device-config-status
PATCH /api/cats/{catId}/profile
POST /api/alerts/{alertId}/resolve?date=YYYY-MM-DD
GET /api/alert-subscriptions
POST /api/alert-subscriptions
```

Current frontend usage:

- Dashboard uses current status, analytics range, alert history and device config status.
- Feeding Records uses analytics range.
- Alert page uses alert history and resolve alert.
- Cat Management uses current status and cat profile update.
- Email subscription UI uses alert subscription APIs.

## 27. Testing

Tests are in `tests/`.

Covered areas:

- parser
- validator
- status service
- analytics range
- alert history
- RFID update
- Device Twin service
- email notification

The tests use in-memory repositories where possible, avoiding live Azure dependencies.

## 28. Deployment

Deploy command:

```powershell
func azure functionapp publish multicatfeeder-func-24417624 --python
```

When adding a new HTTP Function, ensure its function-specific key is configured to match the frontend key, otherwise the frontend receives `401`.

Known functions that were added later and need valid function keys:

- `get_alert_history`
- `admin_update_cat_profile`

## 29. Important Implementation Notes

- Runtime entry module is `backend_app.py`.
- The project intentionally uses classic `function.json` folders because a root `function_app.py` can cause Azure's Python v2 worker indexing path to take over.
- `localDate` is based on backend timezone conversion, not browser time.
- Feeding event deduplication is based on `{deviceId}-{catId}-{feedingEndTimestamp}`.
- `alerts_latest` is not a reliable global history source; use `alerts/history` for recent or historical alert displays.
- Cat name updates propagate to `CatProfiles`, `CurrentStatus`, active RFID mapping/history, today's summary, frontend outputs and Device Twin desired config.
- Device Twin sync status can itself generate `device_config_out_of_sync` alerts.
- Email alert sending is best-effort; delivery failure is recorded in `AlertEmailNotifications`.

