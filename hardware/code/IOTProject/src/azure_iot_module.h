#ifndef AZURE_IOT_MODULE_H
#define AZURE_IOT_MODULE_H

#include <Arduino.h>

// 初始化 WiFi + NTP + TLS + MQTT 连接
void azure_init();

// 发送一次喂食记录到 Azure IoT Hub
// catIndex: 猫咪索引
// feedingStartMs: 喂食开始时的 millis() 值
// intakeGrams: 食量（克），-1 表示称重不可用
void azure_sendFeedingData(int catIndex, unsigned long feedingStartMs, float intakeGrams);

// 在 loop() 中调用，维持 MQTT 连接（自动重连 + Token 刷新 + 补发缓存）
void azure_loop();

// 发送硬件故障事件到 Azure
// hardwareName: "RFID" / "ToF" / "LoadCell_L" / "LoadCell_R" / "Motor"
// detail: 故障描述，如 "init_failed" / "timeout"
void azure_sendHardwareFault(const char* hardwareName, const char* detail);

// 发送心跳包（包含各硬件当前健康状态）
void azure_sendHeartbeat(bool rfidOk, bool tofOk, bool motorOk);

#endif
