#ifndef DISTANCE_MODULE_H
#define DISTANCE_MODULE_H

#include <Arduino.h>

// 初始化距离传感器（失败不会卡死系统，改为降级运行）
void distance_init();

// 读取距离（毫米），失败返回 8190
int distance_readMM();

// 是否有物体（猫）在阈值范围内
bool distance_isCatPresent();

// 传感器是否可用
bool distance_isAvailable();

#endif
