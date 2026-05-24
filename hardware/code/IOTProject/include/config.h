#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// === I2C ===
#define I2C_SDA  21
#define I2C_SCL  22
#define RFID_I2C_ADDR  0x2C
#define TOF_I2C_ADDR   0x29

// === Stepper Motor (28BYJ-48) ===
#define MOTOR_IN1  25
#define MOTOR_IN2  26
#define MOTOR_IN3  14
#define MOTOR_IN4  13
#define STEPS_PER_REV       4096
#define MOTOR_MAX_SPEED     800.0
#define MOTOR_ACCELERATION  400.0
#define BACKLASH_STEPS      20

// === Bowl Positions (steps) ===
#define BOWL_LEFT_STEPS   (-1024)
#define BOWL_RIGHT_STEPS  (1024)
#define HOME_POSITION     0

// === Distance Sensor ===
#define CAT_PRESENT_THRESHOLD_MM  50
#define CAT_LEAVE_TIMEOUT_MS      3000

// === RFID ===
#define RFID_DETECT_TIMEOUT_MS    5000

// === Feeding ===
#define MAX_FEEDING_TIME_MS  300000

// === Cat Profiles ===
#define MAX_CATS  2

// === Motor Timeout ===
#define MOTOR_TIMEOUT_MS  15000

// === Load Cell (HX711) ===
#define LC1_DOUT_PIN  17
#define LC1_SCK_PIN   16
#define LC2_DOUT_PIN  18
#define LC2_SCK_PIN   19

// Calibration factors measured from the prototype hardware.
#define LOADCELL_1_CALIBRATION  232.27f
#define LOADCELL_2_CALIBRATION  225.1f

#endif
