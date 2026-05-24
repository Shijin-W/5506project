#ifndef RFID_MODULE_H
#define RFID_MODULE_H

#include <Arduino.h>

struct CatProfile {
  String uid;
  String name;
  int bowlSteps;   // 目标步数（正=顺时针，负=逆时针）
  int bowlIndex;   // 碗编号: 0=左碗, 1=右碗（用于 Load Cell 读取）
};

// 初始化 RFID 模块 + 从 NVS 加载白名单
void rfid_init();

// 尝试读取一次 RFID 标签。成功读取则将 UID 存入 outUID 并返回 true。非阻塞。
bool rfid_tryRead(String &outUID);

// 验证 UID 是否在白名单中。匹配返回猫咪的索引 (0, 1, ...)，不匹配返回 -1。
int rfid_verifyCat(const String &uid);

// 根据索引获取猫咪配置
CatProfile* rfid_getCatProfile(int idx);

// 获取当前注册的猫数量
int rfid_getCatCount();

// 添加猫到白名单并保存到 NVS，返回索引，满了返回 -1
int rfid_addCat(const String &uid, const String &name, int bowlSteps, int bowlIndex);

// 从白名单删除猫并保存到 NVS，返回 true 成功
bool rfid_removeCat(const String &uid);

// RFID 硬件是否可用
bool rfid_isAvailable();

#endif
