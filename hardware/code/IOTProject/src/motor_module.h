#ifndef MOTOR_MODULE_H
#define MOTOR_MODULE_H

#include <Arduino.h>

void motor_init();

// 设置目标步数（非阻塞），开始运动
void motor_moveTo(int targetSteps);

// 关门，回到 0 位（包含齿轮间隙补偿）
void motor_returnHome();

// 必须放在 loop() 中高频调用。返回 true=还在运动，false=静止
bool motor_update();

// 返回 true=电机已到达目标位置
bool motor_isAtTarget();

// 释放所有线圈电流，防止发烫
void motor_disableOutputs();

#endif
