#ifndef RFID_MODULE_H
#define RFID_MODULE_H

#include <Arduino.h>

struct CatProfile {
  String uid;
  String name;
  int bowlSteps;   // Target steps (positive=clockwise, negative=counter-clockwise)
  int bowlIndex;   // Bowl number: 0=left, 1=right (used for load cell reading)
};

// Initialize RFID module and load whitelist from NVS
void rfid_init();

// Attempt to read an RFID tag once. On success, stores UID in outUID and returns true. Non-blocking.
bool rfid_tryRead(String &outUID);

// Verify if UID is in the whitelist. Returns cat index (0, 1, ...) on match, -1 if not found.
int rfid_verifyCat(const String &uid);

// Get cat profile by index
CatProfile* rfid_getCatProfile(int idx);

// Get number of currently registered cats
int rfid_getCatCount();

// Add a cat to the whitelist and save to NVS. Returns index on success, -1 if full.
int rfid_addCat(const String &uid, const String &name, int bowlSteps, int bowlIndex);

// Remove a cat from the whitelist and save to NVS. Returns true on success.
bool rfid_removeCat(const String &uid);

// Returns true if RFID hardware is available
bool rfid_isAvailable();

// Clear all whitelist entries (used during Device Twin sync)
void rfid_clearAll();

// Inject a virtual RFID tag for serial-based testing (no physical hardware needed)
void rfid_injectMock(const String& uid);

#endif
