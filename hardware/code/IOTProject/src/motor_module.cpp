#include "motor_module.h"
#include "config.h"
#include <AccelStepper.h>

// 28BYJ-48 的半步模式 (HALF4WIRE=8)
// ⚠️ 注意引脚顺序：IN1, IN3, IN2, IN4 (AccelStepper库强制要求交叉接)
static AccelStepper stepper(AccelStepper::HALF4WIRE, MOTOR_IN1, MOTOR_IN3, MOTOR_IN2, MOTOR_IN4);

// 标志位：是否正在执行关门复位过程（用于齿轮补偿分步）
static bool isReturningHome = false;
static bool backlashPhase = false;

void motor_init() {
  stepper.setMaxSpeed(MOTOR_MAX_SPEED);
  stepper.setAcceleration(MOTOR_ACCELERATION);
  
  // 假设开机时就在闭合位置 (0)
  stepper.setCurrentPosition(HOME_POSITION);
  
  Serial.println(F("[MOTOR] Stepper initialized."));
}

void motor_moveTo(int targetSteps) {
  stepper.enableOutputs();
  isReturningHome = false;
  backlashPhase = false;
  stepper.moveTo(targetSteps);
}

void motor_returnHome() {
  stepper.enableOutputs();
  isReturningHome = true;
  backlashPhase = false;
  
  // 关门时：为了补偿齿轮间隙，先往反方向多走一段 BACKLASH_STEPS
  // 因为是从两边往中间关门，所以要先判断当前在哪边，再决定往哪边过冲
  long currentPos = stepper.currentPosition();
  if (currentPos > 0) { // 在右侧碗（正数），回原点应往负数方向走
    stepper.moveTo(HOME_POSITION - BACKLASH_STEPS);
  } else if (currentPos < 0) { // 在左侧碗（负数），回原点应往正数方向走
    stepper.moveTo(HOME_POSITION + BACKLASH_STEPS);
  } else {
    // 已经在原点
    stepper.moveTo(HOME_POSITION);
  }
}

bool motor_update() {
  bool moving = stepper.run();
  
  // 如果当前是关门补偿流程
  if (isReturningHome && !moving) {
    if (!backlashPhase) {
      // 过冲完成，现在回到精确的 0 位
      backlashPhase = true;
      stepper.moveTo(HOME_POSITION);
    } else {
      // 回到 0 位也完成了
      isReturningHome = false;
    }
  }
  
  // 合并运动状态
  return moving || (isReturningHome && !moving);
}

bool motor_isAtTarget() {
  return stepper.distanceToGo() == 0 && !isReturningHome;
}

void motor_disableOutputs() {
  stepper.disableOutputs();
}
