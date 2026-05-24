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
#define BACKLASH_STEPS      20    // Gear backlash compensation

// === Bowl Positions (in steps) ===
#define BOWL_LEFT_STEPS   (-1024)  // Cat A: counter-clockwise 90 deg
#define BOWL_RIGHT_STEPS  (1024)   // Cat B: clockwise 90 deg
#define HOME_POSITION     0        // Closed position

// === Distance Sensor ===
#define CAT_PRESENT_THRESHOLD_MM  50  // <50mm = cat is in the tunnel
#define CAT_LEAVE_TIMEOUT_MS      3000 // 3 seconds no object = cat left

// === RFID ===
#define RFID_DETECT_TIMEOUT_MS    5000 // DETECTING state max wait 5 seconds

// === Feeding ===
#define MAX_FEEDING_TIME_MS  300000  // 5 minutes forced close

// === Cat Profiles ===
#define MAX_CATS  2  // Max 2 cats (limited by 2 load cells)

// === Motor Timeout ===
#define MOTOR_TIMEOUT_MS  15000  // Motor pulses not finished in 15s = blocked

// === Load Cell (HX711) ===
#define LC1_DOUT_PIN  17    // Left bowl data
#define LC1_SCK_PIN   16    // Left bowl clock
#define LC2_DOUT_PIN  18    // Right bowl data
#define LC2_SCK_PIN   19    // Right bowl clock

// Calibration factors (calibrated with iPhone 16 Pro, 199g)
#define LOADCELL_1_CALIBRATION  232.27f  // Left bowl
#define LOADCELL_2_CALIBRATION  225.1f   // Right bowl

#endif
