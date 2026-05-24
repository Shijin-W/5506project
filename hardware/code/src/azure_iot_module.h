#ifndef AZURE_IOT_MODULE_H
#define AZURE_IOT_MODULE_H

#include <Arduino.h>

// Initialize WiFi + NTP + TLS + MQTT connection
void azure_init();

// Send a feeding record to Azure IoT Hub
// catIndex: index of the cat in the whitelist
// feedingStartMs: millis() value when feeding started
// intakeGrams: food intake in grams; -1 means weighing unavailable
void azure_sendFeedingData(int catIndex, unsigned long feedingStartMs, float intakeGrams);

// Call in loop() to maintain MQTT connection (auto-reconnect + token refresh + resend cached data)
void azure_loop();

// Send a hardware fault event to Azure
// hardwareName: "RFID" / "ToF" / "LoadCell_L" / "LoadCell_R" / "Motor"
// detail: fault description, e.g. "init_failed" / "timeout"
void azure_sendHardwareFault(const char* hardwareName, const char* detail);

// Send heartbeat with current hardware health status
void azure_sendHeartbeat(bool rfidOk, bool tofOk, bool motorOk);

// Scan mode: send scanned tag telemetry
void azure_sendScanTelemetry(const String& operationId, const String& uid);

// Scan mode: send scan status (armed, scanned, timeout, cancelled, failed)
void azure_sendScanStatus(const String& operationId, const char* status, const char* reason = nullptr);

#endif
