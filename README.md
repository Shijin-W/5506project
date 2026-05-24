# Smart Multi-Cat Feeder

An IoT-based automatic cat feeder that identifies individual cats via RFID, serves food from dedicated bowls, measures food intake, and reports data to the cloud for remote monitoring.

## Table of Contents

- [Project Overview](#project-overview)
- [System Architecture](#system-architecture)
- [Hardware Setup](#hardware-setup)
- [Software Installation](#software-installation)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Code Overview](#code-overview)

## Project Overview

Multi-cat households face a common problem: one cat may eat another's food, leading to over-feeding or under-feeding. This project solves it by:

1. **RFID Identification** — Each cat wears an RFID tag on its collar. The feeder reads the tag and rotates a turntable to present the correct food bowl.
2. **Weight Measurement** — Load cells under each bowl measure food intake per session.
3. **Cloud Monitoring** — Feeding records are sent to Azure IoT Hub, processed by Azure Functions, and displayed on a web dashboard.
4. **Health Alerts** — If a cat hasn't eaten or exceeds its daily target, the system sends email alerts to the owner.

## System Architecture

```
┌──────────────┐        MQTT/TLS        ┌────────────────────┐
│  ESP32 Device│ ─────────────────────►  │  Azure IoT Hub     │
│  (Firmware)  │  ◄─────────────────── │  (Cloud Gateway)   │
│              │  Device Twin + C2D     └────────┬───────────┘
└──────────────┘                                 │ Event Hub trigger
                                                 ▼
                                       ┌────────────────────┐
                                       │  Azure Functions   │
                                       │  (Python Backend)  │
                                       └────────┬───────────┘
                                                 │ REST API
                                                 ▼
                                       ┌────────────────────┐
                                       │  Web Dashboard     │
                                       │  (HTML/JS Frontend)│
                                       └────────────────────┘
```

**Data flow:**
1. The ESP32 reads sensor data and publishes telemetry to Azure IoT Hub via MQTT over TLS.
2. Azure Functions process incoming events (Event Hub trigger), store feeding records in Azure Table Storage, and generate health alerts.
3. The web dashboard fetches data from the Azure Functions REST API and displays feeding summaries, analytics charts, and alert history.

## Hardware Setup

### Components Required

| Component             | Model                        | Qty | Interface       |
|-----------------------|------------------------------|-----|-----------------|
| Microcontroller       | DFRobot FireBeetle 2 ESP32-E | 1   | —               |
| RFID Reader           | MFRC522 (I2C version)        | 1   | I2C (0x2C)      |
| Distance Sensor       | VL53L1X Time-of-Flight       | 1   | I2C (0x29)      |
| Stepper Motor         | 28BYJ-48 + ULN2003 driver    | 1   | GPIO            |
| Load Cell + Amplifier | HX711                        | 2   | GPIO            |
| RFID Tags             | 13.56 MHz passive tags       | 1 per cat | —         |
| Power Supply          | 5 V USB                      | 1   | —               |

### Wiring Diagram

**I2C Bus** (shared by RFID reader and distance sensor):

| ESP32 Pin | Function |
|-----------|----------|
| GPIO 21   | SDA      |
| GPIO 22   | SCL      |

**Stepper Motor** (28BYJ-48 via ULN2003 driver):

| ESP32 Pin | ULN2003 |
|-----------|---------|
| GPIO 25   | IN1     |
| GPIO 26   | IN2     |
| GPIO 14   | IN3     |
| GPIO 13   | IN4     |

**Load Cells** (HX711 amplifiers):

| ESP32 Pin | Function              |
|-----------|-----------------------|
| GPIO 17   | Left bowl HX711 DOUT  |
| GPIO 16   | Left bowl HX711 SCK   |
| GPIO 18   | Right bowl HX711 DOUT |
| GPIO 19   | Right bowl HX711 SCK  |

### Physical Assembly

1. Mount the RFID reader at the bottom of the feeding tunnel, below the feeding window.
2. Mount the VL53L1X sensor on the tunnel side wall, facing the opposite wall.
3. Fix the stepper motor below the 3D-printed turntable (STL files in `hardware/3d/`).
4. Place two food bowls on the turntable, each sitting on a load cell.
5. Place the ESP32 and breadboard inside the housing box underneath the turntable.

## Software Installation

### Prerequisites

| Tool | Purpose |
|------|---------|
| [PlatformIO](https://platformio.org/) | Build and upload ESP32 firmware |
| [Python 3.9+](https://www.python.org/) | Run the backend (Azure Functions) |
| [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/) | Deploy backend to Azure (optional) |
| [Azure Functions Core Tools](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local) | Run backend locally (optional) |

### 1. ESP32 Firmware

```bash
cd hardware/code
```

**Configure credentials** — edit `include/azure_config.h`:

```cpp
#define WIFI_SSID       "YourWiFiName"
#define WIFI_PASSWORD   "YourWiFiPassword"
#define IOT_HUB_HOST    "your-hub.azure-devices.net"
#define DEVICE_ID       "your-device-id"
#define DEVICE_KEY      "your-device-primary-key"
```

**Build and upload:**

```bash
pio run                          # Build firmware
pio run --target upload          # Flash to ESP32
pio device monitor --baud 115200 # View serial output
```

All library dependencies are listed in `platformio.ini` and will be downloaded automatically on the first build.

### 2. Azure Functions Backend

```bash
cd backend
pip install -r requirements.txt
```

**Configure environment** — copy the template and fill in your Azure credentials:

```bash
cp local.settings.template.json local.settings.json
# Edit local.settings.json with your Azure connection strings
```

Required settings: `AzureWebJobsStorage`, `STORAGE_CONNECTION_STRING`, `IOT_HUB_EVENTHUB_CONNECTION`, `IOT_HUB_EVENTHUB_NAME`, `IOT_HUB_CONNECTION_STRING`, `IOT_HUB_DEVICE_ID`, `LOCAL_TIMEZONE`.

**Seed initial cat profiles:**

```bash
python tools/seed_cat_profiles.py
```

**Deploy to Azure:**

```bash
func azure functionapp publish <function-app-name>
```

### 3. Web Dashboard (Frontend)

The frontend is a static website — no build step required.

```bash
cd frontend
python -m http.server 8088 --bind 127.0.0.1
```

Open `http://127.0.0.1:8088/index.html` in a browser.

To connect to a live backend, create `static/js/config.local.js`:

```javascript
window.FEEDER_CONFIG = {
  BACKEND_BASE_URL: "https://<function-app-name>.azurewebsites.net",
  FUNCTION_KEY: "<your-function-key>"
};
```

Load this file before `api.js` in the HTML pages.

## How It Works

### Firmware State Machine

The ESP32 firmware runs a **6-state finite state machine (FSM)** in a non-blocking `loop()`:

```
IDLE ──► DETECTING ──► OPENING ──► FEEDING ──► CLOSING ──► IDLE
                                                    │
IDLE ──► SCAN_RFID ──► IDLE       (Cloud-triggered RFID binding)
```

| State | Description |
|-------|-------------|
| **IDLE** | Distance sensor monitors the tunnel entrance. Transitions to DETECTING when an object is detected within 50 mm. |
| **DETECTING** | RFID reader attempts to identify the cat (5-second timeout). On match, motor begins rotating to the assigned bowl. |
| **OPENING** | Waits for the stepper motor to reach the target position. Records initial food weight from the load cell. |
| **FEEDING** | Cat is eating. Monitors for departure (3 seconds of continuous absence) and enforces a 5-minute max feeding time. |
| **CLOSING** | Motor returns to home position with backlash compensation. Feeding record (duration, intake) is uploaded to Azure IoT Hub. |
| **SCAN_RFID** | Triggered by a Cloud-to-Device command for remote RFID tag rebinding. Only available when IDLE. |

### Fault Tolerance

- **Sensor failure** — Any sensor that fails during boot is marked as unavailable. The system continues in degraded mode without freezing.
- **Network offline** — Feeding records are cached in a ring buffer (up to 10 records) and automatically resent when the connection is restored.
- **Token refresh** — SAS tokens are regenerated 2 minutes before expiry without interrupting the feeding process.

### Backend Processing

1. IoT Hub forwards device telemetry to Azure Functions via an Event Hub trigger.
2. The backend validates incoming events, maps RFID UIDs to cat profiles, and stores feeding records in Azure Table Storage.
3. Daily summaries and health alerts are computed automatically. If a cat hasn't eaten or exceeds its target, an alert is generated and optionally sent via email.
4. Pre-computed JSON files are written to Azure Blob Storage for fast frontend loading.

### Web Dashboard

| Page | Purpose |
|------|---------|
| **Dashboard** (`index.html`) | Today's feeding count, total intake, active alerts, device status |
| **Feeding Records** (`records.html`) | Detailed feeding history with date filtering |
| **Analytics** (`analytics.html`) | Intake trends and charts over a date range |
| **Health Alerts** (`alerts.html`) | Alert history, manual resolution, email subscription |
| **Cat Management** (`cats.html`) | Edit cat profiles, set daily targets, rebind RFID tags |

## Project Structure

```
5506project/
├── hardware/
│   ├── code/
│   │   ├── include/
│   │   │   ├── config.h              # Pin assignments, thresholds, motor parameters
│   │   │   └── azure_config.h        # WiFi and Azure IoT Hub credentials
│   │   ├── src/
│   │   │   ├── main.cpp              # FSM logic and main loop
│   │   │   ├── rfid_module.cpp/h     # RFID reading, whitelist, NVS persistence
│   │   │   ├── motor_module.cpp/h    # Stepper motor with backlash compensation
│   │   │   ├── distance_module.cpp/h # VL53L1X cat presence detection
│   │   │   ├── loadcell_module.cpp/h # HX711 food weight measurement
│   │   │   └── azure_iot_module.cpp/h# MQTT, SAS auth, Device Twin, telemetry
│   │   └── platformio.ini            # Build config and library dependencies
│   ├── 3d/                           # 3D-printed enclosure STL files
│   └── images/                       # Hardware photos
│
├── backend/
│   ├── backend_app.py                # Azure Functions entry point (all HTTP + Event triggers)
│   ├── shared/
│   │   ├── status_service.py         # Core processing: feeding events, heartbeats, alerts
│   │   ├── table_repository.py       # Azure Table Storage data access layer
│   │   ├── blob_repository.py        # Azure Blob Storage data access layer
│   │   ├── twin_service.py           # Azure IoT Hub Device Twin and C2D messaging
│   │   ├── email_service.py          # Alert email notification (ACS / SMTP)
│   │   ├── alert_service.py          # Alert creation helpers
│   │   ├── config.py                 # App configuration from environment variables
│   │   ├── parser.py                 # IoT Hub message parser
│   │   ├── validator.py              # Feeding event payload validator
│   │   └── time_utils.py             # UTC/local time conversion utilities
│   ├── tests/                        # Unit tests (pytest)
│   └── tools/                        # Seed scripts, backfill, RFID update CLI
│
├── frontend/
│   ├── index.html                    # Dashboard page
│   ├── records.html                  # Feeding records page
│   ├── analytics.html                # Analytics page
│   ├── alerts.html                   # Health alerts page
│   ├── cats.html                     # Cat management page
│   └── static/
│       ├── css/style.css             # Global stylesheet
│       └── js/
│           ├── api.js                # Backend API client and data transformations
│           ├── dashboard.js          # Dashboard page logic
│           ├── records.js            # Records page logic
│           ├── analytics.js          # Analytics page logic (Chart.js)
│           ├── alerts.js             # Alerts page logic
│           └── cats.js               # Cat management page logic
│
└── README.md                         # This file
```

## Code Overview

### Hardware Modules

| Module | File(s) | Description |
|--------|---------|-------------|
| **Main FSM** | `main.cpp` | Implements the 6-state finite state machine. Calls sensor modules and Azure module each loop iteration. |
| **RFID** | `rfid_module.cpp/h` | Reads MFRC522 RFID tags over I2C. Manages a cat whitelist stored in ESP32 NVS (non-volatile storage). Supports mock tag injection for serial-based testing. |
| **Motor** | `motor_module.cpp/h` | Controls the 28BYJ-48 stepper motor via AccelStepper library. Implements a two-phase homing process: overshoot past home then return, to compensate for gear backlash. |
| **Distance** | `distance_module.cpp/h` | Reads VL53L1X Time-of-Flight sensor over I2C. Returns whether an object (cat) is within the threshold range. Runs in degraded mode if sensor init fails. |
| **Load Cell** | `loadcell_module.cpp/h` | Reads two HX711 load cell amplifiers. Averages 5 readings for stability. Note: negative readings after reboot are intentional — intake = initial − final weight. |
| **Azure IoT** | `azure_iot_module.cpp/h` | Manages WiFi, NTP, TLS, and MQTT connection to Azure IoT Hub. Generates SAS tokens using HMAC-SHA256. Handles Device Twin sync and Cloud-to-Device commands. Caches up to 10 unsent records for offline resilience. |

### Backend Functions

| Function | Trigger | Description |
|----------|---------|-------------|
| `process_iothub_feeding_event` | Event Hub | Processes raw IoT messages: validates, stores feeding events, recalculates daily summaries, and generates alerts. |
| `check_daily_feeding_status` | Timer (scheduled) | Ensures every cat has a daily status entry. Generates "not eaten" alerts for cats with no feedings. |
| `get_current_status` | HTTP GET | Returns current feeding status for all cats. |
| `get_daily_summary` | HTTP GET | Returns daily summary for a given date. |
| `get_recent_feedings` | HTTP GET | Returns feeding records for a given date. |
| `get_analytics_range` | HTTP GET | Returns aggregated analytics over a date range. |
| `get_alerts` / `get_alert_history` | HTTP GET | Returns alerts for a date or date range. |
| `resolve_alert` | HTTP POST | Manually resolves an open alert. |
| `alert_subscriptions` | HTTP GET/POST | Manage email alert subscriptions. |
| `update_cat_profile` | HTTP PATCH | Update cat name or daily target, pushes Device Twin. |
| `start_rfid_rebind_scan` | HTTP POST | Sends a Cloud-to-Device command to the ESP32 to scan a new RFID tag. |
| `sync_device_twin_config` | HTTP POST | Force-pushes the latest cat config to the Device Twin. |

### Frontend Pages

| Page | Key Features |
|------|-------------|
| **Dashboard** | Summary cards (feedings, intake, alerts, device status), today's intake by cat, latest feeding records, recent alerts. |
| **Feeding Records** | Full feeding history with date-range picker, per-record details (time, duration, intake). |
| **Analytics** | Chart.js line and bar charts for intake trends over custom date ranges. Per-cat summaries with averages. |
| **Health Alerts** | Alert history with severity levels, manual resolve action, email subscription management. |
| **Cat Management** | Edit cat names and daily targets, trigger RFID rebind scan workflow from the browser. |
