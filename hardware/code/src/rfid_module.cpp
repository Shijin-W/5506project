#include "rfid_module.h"
#include "config.h"
#include <MFRC522_I2C.h>
#include <Preferences.h>   // ESP32 NVS non-volatile storage

// RFID reader instance (uses I2C address from config, reset pin -1 = not used)
static MFRC522_I2C mfrc522(RFID_I2C_ADDR, -1);

// Whitelist (dynamically managed, loaded from NVS)
static CatProfile catProfiles[MAX_CATS];
static int catCount = 0;

// NVS storage
static Preferences prefs;

// Hardware availability
static bool rfidAvailable = false;

// ==================== NVS Read/Write ====================

static void loadFromNVS() {
  prefs.begin("cats", true);  // Read-only
  catCount = prefs.getInt("count", 0);
  if (catCount > MAX_CATS) catCount = MAX_CATS;

  for (int i = 0; i < catCount; i++) {
    String idx = String(i);
    catProfiles[i].uid       = prefs.getString(("uid" + idx).c_str(), "");
    catProfiles[i].name      = prefs.getString(("name" + idx).c_str(), "");
    catProfiles[i].bowlSteps = prefs.getInt(("bowl" + idx).c_str(), 0);
    catProfiles[i].bowlIndex = prefs.getInt(("bidx" + idx).c_str(), i);  // Default bowlIndex = index
  }
  prefs.end();
}

static void saveToNVS() {
  prefs.begin("cats", false);  // Read-write
  prefs.clear();  // Clear all old keys to prevent stale data after cat removal
  prefs.putInt("count", catCount);

  for (int i = 0; i < catCount; i++) {
    String idx = String(i);
    prefs.putString(("uid" + idx).c_str(), catProfiles[i].uid);
    prefs.putString(("name" + idx).c_str(), catProfiles[i].name);
    prefs.putInt(("bowl" + idx).c_str(), catProfiles[i].bowlSteps);
    prefs.putInt(("bidx" + idx).c_str(), catProfiles[i].bowlIndex);
  }
  prefs.end();
  Serial.printf("[RFID] Whitelist saved to NVS (%d cats)\n", catCount);
}

// ==================== Helper Functions ====================

// Convert byte array to uppercase hex string (no spaces)
static String getUIDString(byte *uid, byte uidSize) {
  String uidString = "";
  for (byte i = 0; i < uidSize; i++) {
    if (uid[i] < 0x10) uidString += "0";
    uidString += String(uid[i], HEX);
  }
  uidString.toUpperCase();
  return uidString;
}

// ==================== Public Interface ====================

void rfid_init() {
  mfrc522.PCD_Init();

  // Check if RFID hardware is responding
  byte version = mfrc522.PCD_ReadRegister(mfrc522.VersionReg);
  if (version == 0x00 || version == 0xFF) {
    Serial.println(F("[RFID] Module not detected! Check wiring."));
    rfidAvailable = false;
  } else {
    Serial.printf("[RFID] Module ready (firmware: 0x%02X)\n", version);
    rfidAvailable = true;
  }

  // Load whitelist from NVS
  loadFromNVS();

  // Note: no hardcoded default cats; wait for Azure IoT Hub Device Twin sync
  for (int i = 0; i < catCount; i++) {
    Serial.printf("  [%d] %s  UID: %s  Bowl Steps: %d  Bowl Index: %d\n",
                  i, catProfiles[i].name.c_str(), catProfiles[i].uid.c_str(),
                  catProfiles[i].bowlSteps, catProfiles[i].bowlIndex);
  }
  Serial.println(F("------------------"));
}

static String injectedMockUid = "";

void rfid_injectMock(const String& uid) {
  injectedMockUid = uid;
}

bool rfid_tryRead(String &outUID) {
  // 1. Check for serial-injected virtual tag first
  if (injectedMockUid != "") {
    outUID = injectedMockUid;
    injectedMockUid = ""; // Clear after one read
    return true;
  }

  // 2. Normal hardware read logic
  if (!rfidAvailable) return false;

  // No new card present
  if (!mfrc522.PICC_IsNewCardPresent()) {
    return false;
  }
  // Cannot read card serial
  if (!mfrc522.PICC_ReadCardSerial()) {
    return false;
  }

  // Successfully read, convert UID
  outUID = getUIDString(mfrc522.uid.uidByte, mfrc522.uid.size);

  // Halt the card immediately to prevent repeated reads during a single approach
  mfrc522.PICC_HaltA();

  return true;
}

int rfid_verifyCat(const String &uid) {
  for (int i = 0; i < catCount; i++) {
    if (catProfiles[i].uid == uid) {
      return i; // Match found
    }
  }
  return -1; // Not authorized
}

CatProfile* rfid_getCatProfile(int idx) {
  if (idx >= 0 && idx < catCount) {
    return &catProfiles[idx];
  }
  return nullptr;
}

int rfid_getCatCount() {
  return catCount;
}

int rfid_addCat(const String &uid, const String &name, int bowlSteps, int bowlIndex) {
  // Check if whitelist is full (max 2 cats, limited by 2 load cells)
  if (catCount >= MAX_CATS) {
    Serial.println(F("[RFID] Whitelist full (max 2), cannot add"));
    return -1;
  }

  // Check if UID already exists (prevent duplicates)
  for (int i = 0; i < catCount; i++) {
    if (catProfiles[i].uid == uid) {
      Serial.printf("[RFID] UID %s already exists at index %d\n", uid.c_str(), i);
      return i;
    }
  }

  // Check if bowl index conflicts (each bowl can only be assigned to one cat)
  for (int i = 0; i < catCount; i++) {
    if (catProfiles[i].bowlIndex == bowlIndex) {
      Serial.printf("[RFID] Bowl %d is occupied by %s, cannot assign to %s\n",
                    bowlIndex, catProfiles[i].name.c_str(), name.c_str());
      return -1;
    }
  }

  // Validate bowl index
  if (bowlIndex < 0 || bowlIndex > 1) {
    Serial.printf("[RFID] bowlIndex must be 0(left) or 1(right), received %d\n", bowlIndex);
    return -1;
  }

  // Add the cat
  int idx = catCount;
  catProfiles[idx].uid = uid;
  catProfiles[idx].name = name;
  catProfiles[idx].bowlSteps = bowlSteps;
  catProfiles[idx].bowlIndex = bowlIndex;
  catCount++;

  // Persist to NVS
  saveToNVS();

  Serial.printf("[RFID] Added: %s (UID: %s, Bowl: %d)\n",
                name.c_str(), uid.c_str(), bowlIndex);
  return idx;
}

bool rfid_removeCat(const String &uid) {
  int removeIdx = -1;
  for (int i = 0; i < catCount; i++) {
    if (catProfiles[i].uid == uid) {
      removeIdx = i;
      break;
    }
  }

  if (removeIdx < 0) {
    Serial.printf("[RFID] UID %s not in whitelist\n", uid.c_str());
    return false;
  }

  Serial.printf("[RFID] Deleted: %s (UID: %s)\n",
                catProfiles[removeIdx].name.c_str(), uid.c_str());

  // Shift remaining elements forward to fill the gap
  for (int i = removeIdx; i < catCount - 1; i++) {
    catProfiles[i] = catProfiles[i + 1];
  }
  catCount--;

  // Fix: adjust currentCatIndex if the active feeding cat's index shifted
  extern int currentCatIndex;
  if (currentCatIndex > removeIdx) {
    // Currently feeding cat was shifted forward by one position
    currentCatIndex--;
  } else if (currentCatIndex == removeIdx) {
    // Currently feeding cat was removed (safety fallback)
    currentCatIndex = -1;
  }

  // Clear the last position
  catProfiles[catCount] = {"", "", 0, 0};

  // Persist to NVS
  saveToNVS();

  return true;
}

void rfid_clearAll() {
  for (int i = 0; i < MAX_CATS; i++) {
    catProfiles[i] = {"", "", 0, 0};
  }
  catCount = 0;
  saveToNVS();
  Serial.println(F("[RFID] Whitelist cleared (waiting for Twin sync)"));
}

bool rfid_isAvailable() {
  return rfidAvailable;
}
