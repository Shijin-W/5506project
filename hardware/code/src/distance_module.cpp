#include "distance_module.h"
#include "config.h"
#include <VL53L1X.h>

static VL53L1X distanceSensor;
static bool sensorAvailable = false;

void distance_init() {
  distanceSensor.setTimeout(500);
  if (!distanceSensor.init()) {
    Serial.println(F("[ToF] Failed to detect sensor! System will run without distance detection."));
    sensorAvailable = false;
    return;  // Do not freeze; run in degraded mode
  }

  sensorAvailable = true;

  // Use Short mode for accurate measurement at < 1.3 m range
  distanceSensor.setDistanceMode(VL53L1X::Short);
  distanceSensor.setMeasurementTimingBudget(50000); // 50ms measurement time

  // Start continuous measurement, updating every 50ms
  distanceSensor.startContinuous(50);

  Serial.println(F("[ToF] Module initialized."));
}

int distance_readMM() {
  if (!sensorAvailable) return 8190;

  int dist = distanceSensor.read();
  if (distanceSensor.timeoutOccurred()) {
    Serial.println(F("[ToF] TIMEOUT"));
    return 8190; // Return a very large value representing failure/no object
  }
  return dist;
}

bool distance_isCatPresent() {
  if (!sensorAvailable) return false;  // Sensor unavailable -> treat as no cat
  int dist = distance_readMM();
  // dist > 0 filters out possible 0 anomalies
  // dist < threshold means an object is blocking the sensor
  return (dist > 0 && dist < CAT_PRESENT_THRESHOLD_MM);
}

bool distance_isAvailable() {
  return sensorAvailable;
}
