#include "loadcell_module.h"
#include "config.h"
#include "HX711.h"

static HX711 scaleLeft;
static HX711 scaleRight;
static bool lc1Available = false;  // Left bowl HX711 availability
static bool lc2Available = false;  // Right bowl HX711 availability

void loadcell_init() {
  // Initialize left bowl
  scaleLeft.begin(LC1_DOUT_PIN, LC1_SCK_PIN);
  if (scaleLeft.is_ready()) {
    scaleLeft.set_scale(LOADCELL_1_CALIBRATION);
    scaleLeft.tare(10);  // Average 10 readings as zero point
    lc1Available = true;
    Serial.println(F("[LoadCell] Left Bowl: Init complete"));
  } else {
    lc1Available = false;
    Serial.println(F("[LoadCell] Left Bowl: HX711 not detected!"));
  }

  // Initialize right bowl
  scaleRight.begin(LC2_DOUT_PIN, LC2_SCK_PIN);
  if (scaleRight.is_ready()) {
    scaleRight.set_scale(LOADCELL_2_CALIBRATION);
    scaleRight.tare(10);
    lc2Available = true;
    Serial.println(F("[LoadCell] Right Bowl: Init complete"));
  } else {
    lc2Available = false;
    Serial.println(F("[LoadCell] Right Bowl: HX711 not detected!"));
  }
}

float loadcell_readGrams(int bowlIndex) {
  HX711* scale = (bowlIndex == 0) ? &scaleLeft : &scaleRight;
  bool available = (bowlIndex == 0) ? lc1Available : lc2Available;

  if (!available) {
    Serial.printf("[LoadCell] Bowl %d sensor unavailable\n", bowlIndex);
    return -9999.0f;  // -9999 indicates "cannot read" (normal readings may be negative)
  }

  if (!scale->is_ready()) {
    Serial.printf("[LoadCell] Bowl %d HX711 not ready\n", bowlIndex);
    return -9999.0f;
  }

  // Average 5 readings for stable result
  float weight = scale->get_units(5);

  // Note: do NOT clamp negative values here!
  // After reboot, tare() uses the current food weight as zero.
  // After the cat eats, the reading becomes negative. This is correct.
  // Intake = initialWeight - finalWeight; negative reading produces positive intake.

  return weight;
}

void loadcell_tare(int bowlIndex) {
  HX711* scale = (bowlIndex == 0) ? &scaleLeft : &scaleRight;
  bool available = (bowlIndex == 0) ? lc1Available : lc2Available;
  if (available && scale->is_ready()) {
    scale->tare(10);
    Serial.printf("[LoadCell] Bowl %d tared\n", bowlIndex);
  }
}

void loadcell_tareAll() {
  loadcell_tare(0);
  loadcell_tare(1);
}
