#ifndef DISTANCE_MODULE_H
#define DISTANCE_MODULE_H

#include <Arduino.h>

// Initialize distance sensor (failure does not freeze the system; runs in degraded mode)
void distance_init();

// Read distance in millimeters; returns 8190 on failure
int distance_readMM();

// Returns true if an object (cat) is within the threshold range
bool distance_isCatPresent();

// Returns true if the sensor is available
bool distance_isAvailable();

#endif
