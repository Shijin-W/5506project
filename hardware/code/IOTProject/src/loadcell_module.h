#ifndef LOADCELL_MODULE_H
#define LOADCELL_MODULE_H

#include <Arduino.h>

// 初始化两个 HX711，应用校准因子，自动去皮
void loadcell_init();

// 读取指定碗的重量（克）。bowlIndex: 0=左碗, 1=右碗
// 返回 -1.0 表示传感器不可用
float loadcell_readGrams(int bowlIndex);

// 对指定碗去皮归零
void loadcell_tare(int bowlIndex);

// 两个碗都去皮归零
void loadcell_tareAll();

#endif
