#ifndef LOADCELL_MODULE_H
#define LOADCELL_MODULE_H

#include <Arduino.h>

// Initialize both HX711 modules, apply calibration factors, and auto-tare
void loadcell_init();

// Read weight in grams for the specified bowl. bowlIndex: 0=left, 1=right
// Returns -9999.0 if sensor is unavailable
float loadcell_readGrams(int bowlIndex);

// Tare (zero) the specified bowl
void loadcell_tare(int bowlIndex);

// Tare both bowls
void loadcell_tareAll();

#endif
