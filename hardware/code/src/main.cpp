#include <Arduino.h>
#include <Wire.h>
#include "config.h"
#include "rfid_module.h"
#include "motor_module.h"
#include "distance_module.h"
#include "loadcell_module.h"
#include "azure_iot_module.h"

// FSM state definition
enum State { IDLE, DETECTING, OPENING, FEEDING, CLOSING, SCAN_RFID };
static State state = IDLE;

// Runtime state variables (currentCatIndex is non-static to allow extern access from azure_iot_module)
int currentCatIndex = -1;
static unsigned long stateEnterTime = 0;
static unsigned long catAbsentStart = 0;   // Cat absence continuous timer start
static unsigned long feedingStartTime = 0; // Feeding start time for telemetry upload
static float initialWeight = 0;  // Food weight when bowl opens (-1 = weighing unavailable)
static float finalWeight = 0;    // Food weight when bowl closes
static float intakeGrams = 0;    // Food intake this cycle (-1 = no data)

// Hardware health status (used in heartbeat)
static bool motorOk = true;

// Scan mode global variables
String currentOperationId = "";
unsigned long scanTimeoutMs = 120000;

// External interface to enter scan mode (called by azure_iot_module)
void startScanMode(const String& opId, int timeoutSec, int trayIndex) {
  if (state != IDLE && state != SCAN_RFID) {
    Serial.println(F("[SCAN] Device is currently feeding, cannot enter scan mode"));
    // Wrong state, send failed status
    azure_sendScanStatus(opId, "failed", "device_busy");
    return;
  }
  currentOperationId = opId;
  scanTimeoutMs = timeoutSec * 1000UL;
  state = SCAN_RFID;
  stateEnterTime = millis();
  
  Serial.printf("[SCAN] Entering RFID scan mode, OperationID: %s, Timeout: %ds, Target Tray: %d\n", 
                opId.c_str(), timeoutSec, trayIndex);
                
  if (trayIndex >= 0) {
    Serial.printf("[SCAN] Tip: Motor could rotate to indicate tray %d if needed\n", trayIndex);
  }

  azure_sendScanStatus(opId, "armed");
}

void cancelScanMode() {
  if (state == SCAN_RFID) {
    Serial.println(F("[SCAN] Scan cancelled by user, returning to IDLE"));
    azure_sendScanStatus(currentOperationId, "cancelled");
    currentOperationId = "";
    state = IDLE;
  }
}

void printState(const char* stateName) {
  Serial.print(F("==== STATE: "));
  Serial.print(stateName);
  Serial.println(F(" ===="));
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  // 1. Initialize I2C bus
  Wire.begin(I2C_SDA, I2C_SCL);

  // 2. Initialize all sub-modules (any module failure will not freeze the system)
  rfid_init();
  motor_init();
  distance_init();
  loadcell_init();

  // 3. Initialize Azure IoT Hub connection (WiFi + NTP + MQTT)
  azure_init();

  // Print system status
  Serial.println(F("\n--- Smart Cat Feeder V6.0 Online ---"));
  Serial.printf("[System] RFID: %s | Distance Sensor: %s\n",
                rfid_isAvailable() ? "OK" : "FAIL",
                distance_isAvailable() ? "OK" : "FAIL");
  Serial.printf("[System] Whitelisted Cats: %d\n", rfid_getCatCount());

  // 4. Report hardware faults (only after Azure connection is established)
  if (!rfid_isAvailable()) {
    azure_sendHardwareFault("RFID", "init_failed");
  }
  if (!distance_isAvailable()) {
    azure_sendHardwareFault("ToF", "init_failed");
  }

  // 5. Send boot heartbeat
  azure_sendHeartbeat(rfid_isAvailable(), distance_isAvailable(), motorOk);

  printState("IDLE");
}

void loop() {
  // === Serial command handler (for testing without physical RFID tags) ===
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "REBOOT") {
      Serial.println(F("Received reboot command, restarting..."));
      delay(500);
      ESP.restart();
    } else if (cmd.startsWith("SIMULATE:")) {
      String mockUid = cmd.substring(9);
      mockUid.trim();
      extern void rfid_injectMock(const String&);
      rfid_injectMock(mockUid);
      Serial.printf("[MOCK] Injected virtual tag UID: %s\n", mockUid.c_str());
    }
  }

  // Core: advance stepper motor by one step (if target is set). Non-blocking, executes very fast.
  motor_update();

  // Maintain Azure MQTT connection (auto-reconnect + token refresh + resend cached data)
  azure_loop();

  // Send heartbeat periodically (every 5 minutes)
  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat > 300000) {
    azure_sendHeartbeat(rfid_isAvailable(), distance_isAvailable(), motorOk);
    lastHeartbeat = millis();
  }

  switch (state) {
    case IDLE: {
      // Standby: only distance sensor is active as a "gatekeeper"
      if (distance_isCatPresent()) {
        Serial.println(F("[IDLE] Object detected in tunnel, waking up RFID..."));
        state = DETECTING;
        stateEnterTime = millis();
        printState("DETECTING");
      }
      break;
    }

    case DETECTING: {
      // 1. Check timeout
      if (millis() - stateEnterTime > RFID_DETECT_TIMEOUT_MS) {
        Serial.println(F("[DETECTING] RFID timeout (no collar?). Returning to IDLE"));
        state = IDLE;
        printState("IDLE");
        break;
      }
      
      // 2. Check if cat left
      if (!distance_isCatPresent()) {
        Serial.println(F("[DETECTING] Cat left. Canceling scan, returning to IDLE"));
        state = IDLE;
        printState("IDLE");
        break;
      }

      // 3. Attempt to read RFID
      String uid;
      if (rfid_tryRead(uid)) {
        Serial.print(F("[DETECTING] Scanned tag: "));
        Serial.println(uid);

        int catIdx = rfid_verifyCat(uid);
        if (catIdx >= 0) {
          CatProfile* cat = rfid_getCatProfile(catIdx);
          Serial.printf(">> ID Confirmed: Welcome %s! Preparing food...\n", cat->name.c_str());
          
          currentCatIndex = catIdx;
          
          motor_moveTo(cat->bowlSteps);
          
          state = OPENING;
          stateEnterTime = millis();
          printState("OPENING");
        } else {
          Serial.println(F("WARNING: Unauthorized tag detected! Access denied."));
          delay(500);  // Prevent log spam
        }
      }
      break;
    }

    case OPENING: {
      // Wait for motor to reach the target bowl position
      if (motor_isAtTarget()) {
        motor_disableOutputs(); // Disable coils immediately to prevent overheating
        motorOk = true;         // Motor executed successfully, mark as healthy

        // Record initial food weight
        CatProfile* cat = rfid_getCatProfile(currentCatIndex);
        if (cat) {
          initialWeight = loadcell_readGrams(cat->bowlIndex);
          if (initialWeight > -9000.0f) {
            Serial.printf("[OPENING] Initial weight: %.1f g\n", initialWeight);
          } else {
            Serial.println(F("[OPENING] Load cell unavailable, skipping intake calculation"));
          }
        }

        Serial.println(F("[OPENING] Bowl opened, cat is eating..."));
        state = FEEDING;
        stateEnterTime = millis();
        feedingStartTime = millis();
        catAbsentStart = 0;
        printState("FEEDING");
        break;
      }

      // Motor timeout protection
      if (millis() - stateEnterTime > MOTOR_TIMEOUT_MS) {
        Serial.println(F("[OPENING] Motor timeout! Disabling outputs, returning to IDLE"));
        motor_disableOutputs();
        motorOk = false;  // Mark motor as faulty
        azure_sendHardwareFault("Motor", "opening_timeout");
        currentCatIndex = -1;
        state = IDLE;
        printState("IDLE");
      }
      break;
    }

    case FEEDING: {
      unsigned long now = millis();

      // Logic 1: Check if cat is still eating
      if (distance_isCatPresent()) {
        catAbsentStart = 0;  // Cat is still present, reset absence timer
      } else {
        // Cat is outside the distance sensor threshold
        if (catAbsentStart == 0) {
          catAbsentStart = now;  // Record when cat first disappeared
        } else if (now - catAbsentStart > CAT_LEAVE_TIMEOUT_MS) {
          // Cat has been absent for 3 consecutive seconds -> confirmed departure
          // Record closing weight and calculate intake
          CatProfile* cat = rfid_getCatProfile(currentCatIndex);
          if (cat && initialWeight > -9000.0f) {
            finalWeight = loadcell_readGrams(cat->bowlIndex);
            if (finalWeight > -9000.0f) {
              intakeGrams = initialWeight - finalWeight;
              if (intakeGrams < 0) intakeGrams = 0;
            } else {
              intakeGrams = -1;  // Weighing unavailable
            }
          } else {
            intakeGrams = -1;
          }

          if (cat) {
            if (intakeGrams >= 0) {
              Serial.printf("[FEEDING] Final weight: %.1f g, Intake: %.1f g\n", finalWeight, intakeGrams);
            }
            Serial.printf("[FEEDING] %s has left (for %d seconds), closing bowl...\n", 
                          cat->name.c_str(), CAT_LEAVE_TIMEOUT_MS/1000);
          }
          
          motor_returnHome();
          state = CLOSING;
          stateEnterTime = millis();
          printState("CLOSING");
          break;
        }
      }

      // Logic 2: Max feeding time enforcement (forced close)
      if (now - stateEnterTime > MAX_FEEDING_TIME_MS) {
        CatProfile* cat = rfid_getCatProfile(currentCatIndex);
        if (cat && initialWeight > -9000.0f) {
          finalWeight = loadcell_readGrams(cat->bowlIndex);
          if (finalWeight > -9000.0f) {
            intakeGrams = initialWeight - finalWeight;
            if (intakeGrams < 0) intakeGrams = 0;
          } else {
            intakeGrams = -1;
          }
        } else {
          intakeGrams = -1;
        }
        if (intakeGrams >= 0) {
          Serial.printf("[FEEDING] Timeout - Final weight: %.1f g, Intake: %.1f g\n", finalWeight, intakeGrams);
        }
        Serial.println(F("[FEEDING] Max feeding time reached, forcing close!"));
        motor_returnHome();
        state = CLOSING;
        stateEnterTime = millis();
        printState("CLOSING");
      }
      break;
    }

    case CLOSING: {
      // Wait for motor to return to home position (includes backlash compensation)
      if (motor_isAtTarget()) {
        motor_disableOutputs(); // Motor at home, disable coils
        motorOk = true;         // Motor executed successfully, mark as healthy

        // Send feeding record to Azure IoT Hub
        azure_sendFeedingData(currentCatIndex, feedingStartTime, intakeGrams);

        Serial.println(F("[CLOSING] --- Bowl closed securely, system IDLE ---\n"));
        currentCatIndex = -1;
        state = IDLE;
        printState("IDLE");
        break;
      }

      // Motor timeout protection
      if (millis() - stateEnterTime > MOTOR_TIMEOUT_MS) {
        Serial.println(F("[CLOSING] Motor timeout! Disabling outputs"));
        motor_disableOutputs();
        motorOk = false;  // Mark motor as faulty
        azure_sendHardwareFault("Motor", "closing_timeout");

        // Upload feeding data even if closing failed
        azure_sendFeedingData(currentCatIndex, feedingStartTime, intakeGrams);

        currentCatIndex = -1;
        state = IDLE;
        printState("IDLE");
      }
      break;
    }

    case SCAN_RFID: {
      // Scan timeout
      if (millis() - stateEnterTime > scanTimeoutMs) {
        Serial.println(F("[SCAN] Scan timed out, no new tag detected"));
        azure_sendScanStatus(currentOperationId, "timeout", "no_tag_detected");
        currentOperationId = "";
        state = IDLE;
        printState("IDLE");
        break;
      }

      // Try reading RFID
      String uid;
      if (rfid_tryRead(uid)) {
        Serial.printf("[SCAN] Tag scanned: %s\n", uid.c_str());
        // Send telemetry and status; cloud decides which cat to assign
        azure_sendScanTelemetry(currentOperationId, uid);
        azure_sendScanStatus(currentOperationId, "scanned");
        
        currentOperationId = "";
        state = IDLE;
        printState("IDLE");
      }
      break;
    }
  }

  // Small delay to reduce CPU and I2C bus utilization
  delay(10);
}