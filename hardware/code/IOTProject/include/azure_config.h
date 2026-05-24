// ============================================================
//  Azure IoT Hub connection configuration
//  Replace these placeholder values locally before flashing.
// ============================================================
#ifndef AZURE_CONFIG_H
#define AZURE_CONFIG_H

// ---------- WiFi ----------
#define WIFI_SSID       "<wifi ssid>"
#define WIFI_PASSWORD   "<wifi password>"

// ---------- Azure IoT Hub ----------
// Use the device identity created in Azure IoT Hub.
#define IOT_HUB_HOST    "<iot hub host>"
#define DEVICE_ID       "feeder-esp32-01"
#define DEVICE_KEY      "<device primary key base64>"

// ---------- SAS token lifetime ----------
#define SAS_TOKEN_DURATION_MINS  60

// ---------- NTP time ----------
#define NTP_SERVER      "pool.ntp.org"
#define GMT_OFFSET_SEC  (8 * 3600)   // UTC+8 for Perth
#define DAYLIGHT_OFFSET 0

#endif
