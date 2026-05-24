#include "motor_module.h"
#include "config.h"
#include <AccelStepper.h>

// 28BYJ-48 half-step mode (HALF4WIRE=8)
// Note: pin order is IN1, IN3, IN2, IN4 (AccelStepper requires crossed wiring)
static AccelStepper stepper(AccelStepper::HALF4WIRE, MOTOR_IN1, MOTOR_IN3, MOTOR_IN2, MOTOR_IN4);

// Flags for the homing/backlash compensation process
static bool isReturningHome = false;
static bool backlashPhase = false;

void motor_init() {
  stepper.setMaxSpeed(MOTOR_MAX_SPEED);
  stepper.setAcceleration(MOTOR_ACCELERATION);
  
  // Assume motor starts at closed position (0)
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
  
  // When closing: overshoot past home to compensate for gear backlash
  // Determine overshoot direction based on current position
  long currentPos = stepper.currentPosition();
  if (currentPos > 0) { // At right bowl (positive), must go negative to return
    stepper.moveTo(HOME_POSITION - BACKLASH_STEPS);
  } else if (currentPos < 0) { // At left bowl (negative), must go positive to return
    stepper.moveTo(HOME_POSITION + BACKLASH_STEPS);
  } else {
    // Already at home
    stepper.moveTo(HOME_POSITION);
  }
}

bool motor_update() {
  bool moving = stepper.run();
  
  // Handle the two-phase backlash compensation process
  if (isReturningHome && !moving) {
    if (!backlashPhase) {
      // Overshoot complete, now move to exact home position
      backlashPhase = true;
      stepper.moveTo(HOME_POSITION);
    } else {
      // Returned to exact home position, homing complete
      isReturningHome = false;
    }
  }
  
  // Combined motion status
  return moving || (isReturningHome && !moving);
}

bool motor_isAtTarget() {
  return stepper.distanceToGo() == 0 && !isReturningHome;
}

void motor_disableOutputs() {
  stepper.disableOutputs();
}
