# Smart Cat Feeder — Firmware (ESP32)

This directory contains the firmware for the Smart Cat Feeder, running on a DFRobot FireBeetle 2 ESP32-E. The system identifies cats via RFID, rotates a turntable to present the correct food bowl, measures food intake with load cells, and reports all data to Azure IoT Hub.

## Hardware Setup

### Components Required

| Component             | Model                        | Quantity | Interface       |
| --------------------- | ---------------------------- | -------- | --------------- |
| Microcontroller       | DFRobot FireBeetle 2 ESP32-E | 1        | —               |
| RFID Reader           | MFRC522 (Piico I2C version)  | 1        | I2C (addr 0x2C) |
| Distance Sensor       | VL53L1X Time-of-Flight       | 1        | I2C (addr 0x29) |
| Stepper Motor         | 28BYJ-48 + ULN2003 driver    | 1        | GPIO            |
| Load Cell + Amplifier | HX711                        | 2        | GPIO            |
| RFID Tags             | 13.56 MHz passive tags       | per cat  | —               |
| Power Supply          | 5V USB                       | 1        | —               |

### Wiring

**I2C Bus (shared by RFID and ToF):**

| ESP32 Pin | Function |
| --------- | -------- |
| GPIO 21   | SDA      |
| GPIO 22   | SCL      |

**Stepper Motor (28BYJ-48 via ULN2003):**

| ESP32 Pin | ULN2003 Pin |
| --------- | ----------- |
| GPIO 25   | IN1         |
| GPIO 26   | IN2         |
| GPIO 14   | IN3         |
| GPIO 13   | IN4         |

**Load Cells (HX711):**

| ESP32 Pin | Function              |
| --------- | --------------------- |
| GPIO 17   | Left bowl HX711 DOUT  |
| GPIO 16   | Left bowl HX711 SCK   |
| GPIO 18   | Right bowl HX711 DOUT |
| GPIO 19   | Right bowl HX711 SCK  |

### Physical Assembly

1. Mount the RFID reader at the bottom of the feeding tunnel, just below the feeding window.
2. Mount the VL53L1X sensor on the side wall at the tunnel entrance, facing the opposite wall.
3. Fix the 28BYJ-48 motor below the 3D-printed turntable, with its shaft inserted into the centre.
4. Place two food bowls on the turntable, each on top of a load cell.
5. Place the ESP32 and breadboard inside the housing box underneath the turntable.

## Software Installation

### Prerequisites

- [PlatformIO](https://platformio.org/) (VS Code extension or CLI)
- USB cable for ESP32 flashing

### Configuration

1. Open `include/azure_config.h` and set your WiFi credentials and Azure IoT Hub device credentials:

```cpp
#define WIFI_SSID       "YourWiFiName"
#define WIFI_PASSWORD   "YourWiFiPassword"
#define IOT_HUB_HOST    "your-hub.azure-devices.net"
#define DEVICE_ID       "your-device-id"
#define DEVICE_KEY      "your-device-primary-key"
```

2. (Optional) Adjust sensor thresholds and motor parameters in `include/config.h` if your hardware setup differs from the default.

### Build and Upload

```bash
# Build the firmware
pio run

# Upload to the connected ESP32
pio run --target upload

# Open serial monitor to view logs
pio device monitor --baud 115200
```

All library dependencies (MFRC522_I2C, AccelStepper, HX711, VL53L1X, PubSubClient, ArduinoJson) are listed in `platformio.ini` and will be downloaded automatically on the first build.

## Project Structure

```
IOTProject/
├── include/
│   ├── config.h              # Pin assignments, thresholds, and motor parameters
│   └── azure_config.h        # WiFi and Azure IoT Hub credentials
├── src/
│   ├── main.cpp              # FSM logic and main loop
│   ├── rfid_module.cpp/h     # RFID reading, whitelist management, NVS persistence
│   ├── motor_module.cpp/h    # Stepper motor control with backlash compensation
│   ├── distance_module.cpp/h # VL53L1X distance sensor (cat presence detection)
│   ├── loadcell_module.cpp/h # HX711 load cell (food weight measurement)
│   └── azure_iot_module.cpp/h# Azure IoT Hub: MQTT, SAS auth, Device Twin, C2D, telemetry
└── platformio.ini            # Build configuration and library dependencies
```

## How It Works

The firmware runs a 6-state finite state machine (FSM) in a non-blocking main loop:

1. **IDLE** — Distance sensor monitors the tunnel entrance. When an object is detected, the system transitions to DETECTING.
2. **DETECTING** — RFID reader attempts to identify the cat. On success, the motor begins rotating to the assigned bowl position (OPENING). On timeout or cat departure, returns to IDLE.
3. **OPENING** — Waits for the stepper motor to reach the target bowl position. Records initial food weight from the load cell.
4. **FEEDING** — Cat is eating. The system monitors the distance sensor for cat departure (3-second absence confirmation) and enforces a 5-minute maximum feeding time.
5. **CLOSING** — Motor returns to home position with backlash compensation (overshoot + correction). Feeding record is uploaded to Azure IoT Hub.
6. **SCAN_RFID** — Triggered by a Cloud-to-Device command for remote RFID tag binding. Only available when IDLE.

### Fault Tolerance

- Any sensor failure at boot does not freeze the system; the module is marked as unavailable and the system runs in degraded mode.
- Feeding records are cached in a ring buffer (max 10) when the network is offline and automatically resent on reconnection.
- SAS tokens are auto-refreshed 2 minutes before expiry without interrupting the feeding process.
