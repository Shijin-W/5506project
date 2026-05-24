// ============================================================
//  Azure IoT Hub Connection Configuration
//  Replace the placeholders below with your actual credentials
// ============================================================
#ifndef AZURE_CONFIG_H
#define AZURE_CONFIG_H

// ---------- WiFi ----------
#define WIFI_SSID       "OnePlus 13"       // Your WiFi SSID
#define WIFI_PASSWORD   "66666666"       // Your WiFi password

// ---------- Azure IoT Hub ----------
// These 3 values are from Azure Portal device registration:
#define IOT_HUB_HOST   "multicatfeeder.azure-devices.net"  // IoT Hub hostname
#define DEVICE_ID       "feeder-esp32-01"          // Device ID
#define DEVICE_KEY      "CxX1INt69XaLI1jM8P8z3aGaJkHxX7KemKY1bh2gAlk="   // Device primary key (Base64)

// ---------- SAS Token Validity ----------
// Token is automatically regenerated on expiry; default 60 minutes
#define SAS_TOKEN_DURATION_MINS  60

// ---------- NTP Time Server ----------
// Accurate time is required for SAS Token generation; using Perth timezone (UTC+8)
#define NTP_SERVER      "pool.ntp.org"
#define GMT_OFFSET_SEC  (8 * 3600)   // UTC+8 for Perth
#define DAYLIGHT_OFFSET 0

#endif
