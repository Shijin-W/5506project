#ifndef MOTOR_MODULE_H
#define MOTOR_MODULE_H

#include <Arduino.h>

void motor_init();

// Set target step count (non-blocking), start movement
void motor_moveTo(int targetSteps);

// Return to home position (0) with gear backlash compensation
void motor_returnHome();

// Must be called at high frequency in loop(). Returns true=still moving, false=idle
bool motor_update();

// Returns true if motor has reached the target position
bool motor_isAtTarget();

// Disable all coil outputs to prevent overheating
void motor_disableOutputs();

#endif
