# Smart Multi-Cat Feeder Hardware

This folder contains the ESP32 firmware and hardware assets for the feeder prototype.

## Contents

| Path | Purpose |
|---|---|
| `code/IOTProject` | PlatformIO firmware project for the ESP32 |
| `3d` | STL files for feeder mechanical parts |
| `images` | Hardware reference images |
| `ESP32_DEVICE_TWIN_SETUP.md` | Azure IoT Hub telemetry and Device Twin integration guide |

## Firmware Setup

1. Install Visual Studio Code and PlatformIO.
2. Open `hardware/code/IOTProject`.
3. Review hardware pin settings in `include/config.h`.
4. Fill local WiFi and IoT Hub values in `include/azure_config.h`.
5. Build and upload the firmware to the DFRobot FireBeetle 2 ESP32-E board.

Required local values:

```cpp
#define WIFI_SSID       "<wifi ssid>"
#define WIFI_PASSWORD   "<wifi password>"
#define IOT_HUB_HOST    "<iot hub host>"
#define DEVICE_ID       "<device id>"
#define DEVICE_KEY      "<device primary key base64>"
```

Do not commit real WiFi passwords or IoT Hub device keys.

## Main Firmware Flow

1. Distance sensor detects an object at the feeding entrance.
2. RFID reader identifies the cat tag.
3. Stepper motor opens the matching bowl position.
4. Load cell records food weight before and after feeding.
5. ESP32 sends `feeding_complete` telemetry to Azure IoT Hub.
6. Backend updates summaries, alerts, and frontend data.
