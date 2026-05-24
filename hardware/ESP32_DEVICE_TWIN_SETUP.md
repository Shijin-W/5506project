# ESP32 Azure IoT Hub Device Twin Setup

This document is for the ESP32 firmware developer. It explains how the ESP32 should connect to Azure IoT Hub, read Device Twin configuration, apply RFID changes, and report configuration sync status.

## Device Connection

IoT Hub host:

```text
multicatfeeder.azure-devices.net
```

IoT Hub name:

```text
multicatfeeder
```

Device ID:

```text
feeder-esp32-01
```

Device connection string:

```text
HostName=<iot-hub-host>;DeviceId=feeder-esp32-01;SharedAccessKey=<device-primary-key>
```

Use the device connection string only on the ESP32/device side. Do not use backend service connection strings, Azure Storage connection strings, Function App keys, or Azure CLI user credentials in firmware.

## Required Device Twin Behavior

The ESP32 must not hard-code cat RFID UIDs in firmware.

On startup, the ESP32 should:

1. Connect to Azure IoT Hub using the device connection string.
2. Read Device Twin `properties.desired`.
3. Build a local RFID mapping from `cats`.
4. Store the applied `configVersion`.
5. Report the applied configuration through Device Twin `properties.reported`.

While running, the ESP32 should:

1. Listen for desired property patch updates.
2. Check whether the received `configVersion` is newer than the currently applied version.
3. If newer, refresh the local RFID mapping.
4. Report the new applied version after the update succeeds.

## Current Desired Twin Configuration

The ESP32 should read this structure from Device Twin `properties.desired`:

```json
{
  "configVersion": 1,
  "cats": {
    "cat_a": {
      "catName": "CatA",
      "catUID": "B9BD18C9",
      "minimumMeaningfulIntakeGrams": 2.0,
      "targetDailyGrams": 60.0
    },
    "cat_b": {
      "catName": "CatB",
      "catUID": "0420D6BAFD1691",
      "minimumMeaningfulIntakeGrams": 2.0,
      "targetDailyGrams": 60.0
    }
  },
  "feedingRules": {
    "allowUnknownRfid": false,
    "minFeedingIntervalHours": 8
  }
}
```

Fields the ESP32 must support:

```text
configVersion
cats.<catId>.catName
cats.<catId>.catUID
cats.<catId>.targetDailyGrams
cats.<catId>.minimumMeaningfulIntakeGrams
feedingRules.allowUnknownRfid
feedingRules.minFeedingIntervalHours
```

The current cat IDs are:

```text
cat_a
cat_b
```

RFID UID values should be treated as exact string IDs. Recommended firmware handling:

```text
uppercase
no spaces
no separators unless the RFID reader library requires them internally
```

## Reported Twin Properties

After applying desired configuration, the ESP32 should update Device Twin `properties.reported`.

Use this format:

```json
{
  "configVersionApplied": 1,
  "knownCats": {
    "cat_a": "B9BD18C9",
    "cat_b": "0420D6BAFD1691"
  },
  "lastSyncTime": "2026-05-16T08:00:00Z"
}
```

Required reported fields:

```text
configVersionApplied
knownCats
lastSyncTime
```

`lastSyncTime` should be UTC ISO 8601 time.

The backend uses `configVersionApplied` to check whether the ESP32 has applied the latest RFID configuration. If this field is missing or old, the backend may report the device config as out of sync.

## RFID Change Flow

RFID changes are made from the backend/admin side, not by changing ESP32 firmware.

For the current implementation, the frontend user must choose both:

```text
action: rebind RFID
target cat: cat_a or cat_b
```

The backend does not need to infer which cat should be updated in this flow.

This is not an `add_cat` or `remove_cat` flow. It is a rebind flow for one existing cat:

```text
same cat
same bowl
same catName
old RFID UID replaced by new RFID UID
```

One-off scan commands should be sent to the ESP32 as Cloud-to-Device messages. Device Twin desired properties should remain the source of truth for the final persistent cat RFID configuration.

### Start RFID Rebind Scan Command

When the user clicks `Rebind RFID` for a selected cat, the backend records the selected cat in the pending operation and sends this simple C2D command to the ESP32:

```json
{
  "action": "start_scan",
  "operationId": "rfid-op-20260516-001",
  "trayIndex": 0,
  "timeoutSec": 120
}
```

Required command fields:

```text
action must be start_scan
operationId uniquely identifies this scan operation
trayIndex identifies which tray/bowl belongs to the selected cat
timeoutSec is the scan timeout in seconds
```

Current tray mapping:

```text
cat_a -> trayIndex 0
cat_b -> trayIndex 1
```

ESP32 behavior after receiving this command:

1. Enter a dedicated RFID scan mode.
2. Use a 2-minute timeout unless `timeoutSec` says otherwise.
3. Use `trayIndex` if the scan flow requires moving or indicating the selected tray.
4. Do not treat the scanned tag as a feeding attempt.
5. Read the next RFID UID, even if it is not in the local whitelist.
6. Send a `tag_scanned` telemetry message to the backend.
7. Exit scan mode after a successful scan, timeout, or cancel command.

This scan mode is separate from the normal feeding state. In the current hardware logic, unknown RFID tags do not enter `FEEDING`, so the ESP32 must send a separate scan event when it reads a new tag during rebind mode.

The backend already knows which cat the user selected. The ESP32 does not need to decide whether the new UID belongs to `cat_a` or `cat_b`. `trayIndex` is provided so the ESP32 knows which tray/bowl is associated with the selected cat.

### Tag Scanned Telemetry

After the ESP32 scans the new RFID tag, it should send this telemetry:

```json
{
  "deviceId": "feeder-esp32-01",
  "event": "tag_scanned",
  "operationId": "rfid-op-20260516-001",
  "uid": "NEW_UID_HERE",
  "timestamp": 1778918400
}
```

Required scan telemetry fields:

```text
event must be tag_scanned
operationId must match the start_scan command
uid is the newly scanned RFID UID
timestamp is a Unix timestamp in seconds
```

Recommended UID formatting:

```text
uppercase
no spaces
no separators
```

Example:

```json
{
  "deviceId": "feeder-esp32-01",
  "event": "tag_scanned",
  "operationId": "rfid-op-20260516-001",
  "uid": "04A1B2C3D4",
  "timestamp": 1778918400
}
```

### RFID Scan Status

The ESP32 may also send status telemetry during the scan flow:

```json
{
  "deviceId": "feeder-esp32-01",
  "event": "scan_status",
  "operationId": "rfid-op-20260516-001",
  "status": "armed",
  "timestamp": 1778918380
}
```

Allowed status values:

```text
armed
scanned
timeout
cancelled
failed
```

If the scan times out:

```json
{
  "deviceId": "feeder-esp32-01",
  "event": "scan_status",
  "operationId": "rfid-op-20260516-001",
  "status": "timeout",
  "reason": "no_tag_detected",
  "timestamp": 1778918700
}
```

### Cancel RFID Scan Command

If the user cancels the operation, the backend sends:

```json
{
  "action": "cancel_scan",
  "operationId": "rfid-op-20260516-001"
}
```

ESP32 should exit RFID scan mode and return to normal idle/feeding detection.

### Backend Update After Scan

After receiving valid `tag_scanned` telemetry, the backend will:

1. Verify that `operationId` is still active.
2. Look up the selected cat from the pending operation created by the frontend.
3. Check that the new `uid` is not already assigned to another cat.
4. Update the selected cat's RFID mapping.
5. Preserve old RFID history.
6. Increment `configVersion`.
7. Push updated persistent configuration through Device Twin desired properties.

The ESP32 should then receive the Device Twin desired change, update its local whitelist, save it to NVS, and report the applied version through reported properties.

When a cat RFID changes, the backend will:

1. Update the cat profile.
2. Preserve old RFID history.
3. Increment `configVersion`.
4. Push new Device Twin desired properties.

The ESP32 should then receive the desired property update, apply the new `catUID`, and report the new `configVersionApplied`.

Example desired twin after changing `cat_a` RFID:

```json
{
  "configVersion": 2,
  "cats": {
    "cat_a": {
      "catName": "CatA",
      "catUID": "NEW_UID_HERE",
      "minimumMeaningfulIntakeGrams": 2.0,
      "targetDailyGrams": 60.0
    },
    "cat_b": {
      "catName": "CatB",
      "catUID": "0420D6BAFD1691",
      "minimumMeaningfulIntakeGrams": 2.0,
      "targetDailyGrams": 60.0
    }
  },
  "feedingRules": {
    "allowUnknownRfid": false,
    "minFeedingIntervalHours": 8
  }
}
```

Expected reported twin after applying it:

```json
{
  "configVersionApplied": 2,
  "knownCats": {
    "cat_a": "NEW_UID_HERE",
    "cat_b": "0420D6BAFD1691"
  },
  "lastSyncTime": "2026-05-16T08:05:00Z"
}
```

## Feeding Complete Telemetry

After recognizing a cat and completing a feeding measurement, the ESP32 should send telemetry to IoT Hub using this JSON format:

```json
{
  "deviceId": "feeder-esp32-01",
  "catName": "CatA",
  "catUID": "B9BD18C9",
  "event": "feeding_complete",
  "feedingStartTime": 1778918400,
  "feedingEndTime": 1778918700,
  "durationSec": 300,
  "intakeGrams": 12.5
}
```

Telemetry requirements:

```text
event must be feeding_complete
feedingStartTime is a Unix timestamp in seconds
feedingEndTime is a Unix timestamp in seconds
durationSec should equal feedingEndTime - feedingStartTime
intakeGrams should be numeric and must not be negative when the scale is working
intakeGrams may be null only when the weight/scale sensor failed
catUID must match one of the Device Twin desired catUID values
deviceId should be feeder-esp32-01
```

If the weight/scale sensor fails during a feeding attempt, send `intakeGrams` as JSON `null`:

```json
{
  "deviceId": "feeder-esp32-01",
  "catName": "CatB",
  "catUID": "0420D6BAFD1691",
  "event": "feeding_complete",
  "feedingStartTime": 1778918400,
  "feedingEndTime": 1778918700,
  "durationSec": 300,
  "intakeGrams": null
}
```

The backend treats `intakeGrams: null` as a scale sensor failure. It will create a `scale_sensor_error` alert and will not count the event toward the cat's daily intake total.

## Heartbeat Telemetry

The ESP32 may send heartbeat telemetry with hardware health checks:

```json
{
  "deviceId": "feeder-esp32-01",
  "event": "heartbeat",
  "timestamp": 1778918400,
  "rfid_ok": true,
  "tof_ok": true,
  "motor_ok": true
}
```

Heartbeat fields:

```text
timestamp is a Unix timestamp in seconds
rfid_ok reports RFID reader health
tof_ok reports time-of-flight sensor health
motor_ok reports motor health
```

If any health check is `false`, the backend treats it as a device health issue and creates a `device_health_error` alert.

## Handling Unknown RFID

Current cloud setting:

```text
feedingRules.allowUnknownRfid = false
```

Recommended ESP32 behavior:

1. If scanned RFID matches a configured `catUID`, proceed with normal feeding logic.
2. If scanned RFID is unknown and `allowUnknownRfid` is `false`, do not treat it as a known cat.
3. Optionally send diagnostic telemetry/logging for unknown RFID, but do not send a normal `feeding_complete` event as if it belonged to CatA or CatB.

## Acceptance Checklist

The integration is working when:

```text
ESP32 connects to IoT Hub as feeder-esp32-01
ESP32 reads Device Twin desired properties
ESP32 applies cat_a and cat_b RFID UIDs from desired twin
ESP32 reports configVersionApplied
ESP32 reports knownCats
ESP32 updates reported properties again after desired configVersion changes
ESP32 sends feeding_complete telemetry with the configured catUID
```

## Security Notes

The device connection string contains the ESP32 device key.

Do not share real keys publicly.
Do not commit real keys to a public repository.
Do not put backend/admin connection strings into ESP32 firmware.
If the key is leaked, regenerate the device key in Azure IoT Hub and update the ESP32 firmware/config.
