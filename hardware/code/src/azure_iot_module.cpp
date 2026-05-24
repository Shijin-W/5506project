#include "azure_iot_module.h"
#include "azure_config.h"
#include "config.h"
#include "rfid_module.h"

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>

// mbedtls for HMAC-SHA256 signing of SAS Token (built-in on ESP32, no extra install needed)
#include <mbedtls/md.h>
#include <mbedtls/base64.h>

// ==================== Azure IoT Hub Root CA ====================
// DigiCert Global Root G2 - root certificate used by Azure IoT Hub
static const char* ROOT_CA = R"EOF(
-----BEGIN CERTIFICATE-----
MIIDjjCCAnagAwIBAgIQAzrx5qcRqaC7KGSxHQn65TANBgkqhkiG9w0BAQsFADBh
MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3
d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBH
MjAeFw0xMzA4MDExMjAwMDBaFw0zODAxMTUxMjAwMDBaMGExCzAJBgNVBAYTAlVT
MRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5j
b20xIDAeBgNVBAMTF0RpZ2lDZXJ0IEdsb2JhbCBSb290IEcyMIIBIjANBgkqhkiG
9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuzfNNNx7a8myaJCtSnX/RrohCgiN9RlUyfuI
2/Ou8jqJkTx65qsGGmvPrC3oXgkkRLpimn7Wo6h+4FR1IAWsULecYxpsMNzaHxmx
1x7e/dfgy5SDN67sH0NO3Xss0r0upS/kqbitOtSZpLYl6ZtrAGCSYP9PIUkY92eQ
q2EGnI/yuum06ZIya7XzV+hdG82MHauVBJVJ8zUtluNJbd134/tJS7SsVQepj5Wz
tCO7TG1F8PapspUwtP1MVYwnSlcUfIKdzXOS0xZKBgyMUNGPHgm+F6HmIcr9g+UQ
vIOlCsRnKPZzFBQ9RnbDhxSJITRNrw9FDKZJobq7nMWxM4MphQIDAQABo0IwQDAP
BgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBhjAdBgNVHQ4EFgQUTiJUIBiV
5uNu5g/6+rkS7QYXjzkwDQYJKoZIhvcNAQELBQADggEBAGBnKJRvDkhj6zHd6mcY
1Yl9PMCcit6E7UL/VEQIgOfR9PaMoBd4Ij3oy+Bii0du5l/jK5d3kO7KKIhL4YUQ
nLLEoYmNOIkSu5URH9Rv3ufkbe0E6LaLqRy3/QUYA3h+nnqVCKnfp7un0pNycQEI
bMhDYFRABVBL0OBURR3FJHjFJpWzqMvOnIl60vM+moJ8B6Q7/JBfqC3C19CVpx7d
AqyaJK0UHHWUQ1IQE5g0Kxxt7yHris3bA7+FOMiQBPegQewNmh8uKRnMzeltMrGe
0Bj9re6LFwv3k4EYhu7IJ0NIBfDKDhgO0GQszCNOJsR7dnv0UCVotQJyUco+f5WV
hSk=
-----END CERTIFICATE-----
)EOF";

// ==================== Global Objects ====================
static WiFiClientSecure wifiClient;
static PubSubClient mqttClient(wifiClient);

// MQTT Topics
static String telemetryTopic;
static String c2dTopic;
static String twinReportedPub;

// SAS Token
static String sasToken;
static unsigned long tokenExpiryEpoch = 0;

// MQTT reconnect throttle
static unsigned long lastMqttAttempt = 0;
const unsigned long MQTT_RETRY_INTERVAL_MS = 5000;

// ==================== Data Cache Queue ====================
#define MAX_CACHED_RECORDS 10

struct CachedRecord {
  char json[512];
  bool used;
};

static CachedRecord cache[MAX_CACHED_RECORDS];
static int cacheWriteIdx = 0;

static void cacheRecord(const char* json) {
  strncpy(cache[cacheWriteIdx].json, json, sizeof(cache[cacheWriteIdx].json) - 1);
  cache[cacheWriteIdx].json[sizeof(cache[cacheWriteIdx].json) - 1] = '\0';
  cache[cacheWriteIdx].used = true;
  cacheWriteIdx = (cacheWriteIdx + 1) % MAX_CACHED_RECORDS;
  Serial.println(F("[Azure] Data cached for retry."));
}

static void retryCachedData() {
  for (int i = 0; i < MAX_CACHED_RECORDS; i++) {
    if (cache[i].used) {
      if (mqttClient.publish(telemetryTopic.c_str(), cache[i].json)) {
        Serial.printf("[Azure] Cached data resent: %s\n", cache[i].json);
        cache[i].used = false;
      } else {
        // Send failed, retry next time
        break;
      }
    }
  }
}

// External control functions defined in main.cpp
extern void startScanMode(const String& opId, int timeoutSec, int trayIndex);
extern void cancelScanMode();

// ==================== Device Twin Handling ====================
static int appliedConfigVersion = 0;
static int reportRid = 100;

static void reportAppliedConfig() {
  JsonDocument doc;
  doc["configVersionApplied"] = appliedConfigVersion;

  JsonObject known = doc["knownCats"].to<JsonObject>();
  for (int i = 0; i < rfid_getCatCount(); i++) {
    CatProfile* cat = rfid_getCatProfile(i);
    if (cat) {
      String catId = (cat->bowlIndex == 0) ? "cat_a" : "cat_b";
      known[catId] = cat->uid;
    }
  }

  time_t now; time(&now);
  char timeBuf[30];
  strftime(timeBuf, sizeof(timeBuf), "%Y-%m-%dT%H:%M:%SZ", gmtime(&now));
  doc["lastSyncTime"] = timeBuf;

  char buf[512];
  serializeJson(doc, buf, sizeof(buf));
  String topic = twinReportedPub + String(reportRid++);
  mqttClient.publish(topic.c_str(), buf);
  Serial.printf("[Twin] Reported: %s\n", buf);
}

static void applyDesiredConfig(JsonObject desired) {
  int newVersion = desired["configVersion"] | 0;
  if (newVersion <= appliedConfigVersion && appliedConfigVersion > 0) {
    Serial.printf("[Twin] configVersion %d is up to date, skipping\n", newVersion);
    return;
  }

  JsonObject cats = desired["cats"];
  if (!cats.isNull()) {
    rfid_clearAll();  // Clear whitelist, rebuild from scratch

    for (JsonPair kv : cats) {
      String catId = kv.key().c_str();
      JsonObject cat = kv.value().as<JsonObject>();

      String uid  = cat["catUID"].as<String>();
      String name = cat["catName"].as<String>();

      // Bowl assignment: bowlIndex inferred from catId key
      int bowlIndex = (catId == "cat_a") ? 0 : 1; 
      int bowlSteps = (bowlIndex == 0) ? BOWL_LEFT_STEPS : BOWL_RIGHT_STEPS;

      rfid_addCat(uid, name, bowlSteps, bowlIndex);
    }
  }

  appliedConfigVersion = newVersion;
  reportAppliedConfig();
  Serial.printf("[Twin] Applied configVersion %d\n", newVersion);
}

static void handleTwinFullResponse(byte* payload, unsigned int length) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, length)) return;
  JsonObject desired = doc["desired"];
  if (!desired.isNull()) applyDesiredConfig(desired);
}

static void handleDesiredPatch(byte* payload, unsigned int length) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, length)) return;
  applyDesiredConfig(doc.as<JsonObject>());
}

// ==================== C2D / Twin Message Callback ====================
static void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String t = String(topic);

  if (t.startsWith("$iothub/twin/res/")) {
    int statusCode = t.substring(17, 20).toInt();
    if (statusCode == 200) {
      handleTwinFullResponse(payload, length);
    }
  } else if (t.startsWith("$iothub/twin/PATCH/properties/desired/")) {
    handleDesiredPatch(payload, length);
  } else if (t.indexOf("devicebound") > 0) {
    // Parse C2D one-time command
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) {
      Serial.printf("[C2D] JSON parse error: %s\n", err.c_str());
      return;
    }

    const char* action = doc["action"];
    if (!action) return;

    if (strcmp(action, "start_scan") == 0) {
      String opId = doc["operationId"].as<String>();
      int timeout = doc["timeoutSec"] | 120; // Default 120 seconds
      int trayIndex = doc["trayIndex"] | -1; // Parse trayIndex field
      startScanMode(opId, timeout, trayIndex);
    } else if (strcmp(action, "cancel_scan") == 0) {
      cancelScanMode();
    }
  }
}

// ==================== Internal Function Declarations ====================
static void connectWiFi();
static void syncNTP();
static String generateSASToken(unsigned long expiryEpoch);
static String urlEncode(const String& str);
static void connectMQTT();

// ==================== WiFi Connection ====================
// Blocking version: used only during setup() for initial connection (may wait up to 20s)
static void connectWiFi() {
  Serial.printf("[Azure] Connecting to WiFi '%s'", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[Azure] WiFi connected! IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[Azure] WiFi connection failed! Check SSID/password.");
  }
}

// Non-blocking version: used at runtime when WiFi drops, does not block loop()
static void tryReconnectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.println(F("[Azure] WiFi lost, attempting reconnect..."));
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  // Do not wait! Next azure_loop() iteration will check again
}

// ==================== NTP Time Sync ====================
static void syncNTP() {
  Serial.println(F("[Azure] Syncing time via NTP..."));
  configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET, NTP_SERVER);

  // Wait for time sync (max 15 seconds)
  time_t now = 0;
  int attempts = 0;
  while (now < 1700000000 && attempts < 30) {  // Timestamps after 2023
    delay(500);
    time(&now);
    attempts++;
  }

  if (now >= 1700000000) {
    struct tm timeinfo;
    localtime_r(&now, &timeinfo);
    Serial.printf("[Azure] Time synced: %s", asctime(&timeinfo));
  } else {
    Serial.println(F("[Azure] NTP sync failed!"));
  }
}

// ==================== SAS Token Generation ====================
static String generateSASToken(unsigned long expiryEpoch) {
  // 1. Build resource URI
  String resourceUri = String(IOT_HUB_HOST) + "/devices/" + String(DEVICE_ID);
  String encodedUri = urlEncode(resourceUri);

  // 2. Build string to sign
  String toSign = encodedUri + "\n" + String(expiryEpoch);

  Serial.printf("[Azure] SAS: URI=%s\n", resourceUri.c_str());
  Serial.printf("[Azure] SAS: Expiry=%lu\n", expiryEpoch);

  // 3. Base64-decode the device key
  size_t keyLen = 0;
  unsigned char decodedKey[64];
  int decRet = mbedtls_base64_decode(decodedKey, sizeof(decodedKey), &keyLen,
                        (const unsigned char*)DEVICE_KEY, strlen(DEVICE_KEY));
  if (decRet != 0) {
    Serial.printf("[Azure] Base64 decode failed! ret=%d\n", decRet);
    return "";
  }
  Serial.printf("[Azure] SAS: Key decoded, %d bytes\n", (int)keyLen);

  // 4. HMAC-SHA256 signature
  unsigned char signature[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, decodedKey, keyLen);
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)toSign.c_str(), toSign.length());
  mbedtls_md_hmac_finish(&ctx, signature);
  mbedtls_md_free(&ctx);

  // 5. Base64-encode the signature
  unsigned char encodedSignature[64];
  size_t encodedLen = 0;
  mbedtls_base64_encode(encodedSignature, sizeof(encodedSignature), &encodedLen,
                        signature, 32);
  String sigStr = String((char*)encodedSignature).substring(0, encodedLen);

  // 6. Assemble the SAS Token string
  String token = "SharedAccessSignature sr=" + encodedUri +
                 "&sig=" + urlEncode(sigStr) +
                 "&se=" + String(expiryEpoch);

  Serial.println(F("[Azure] SAS Token generated successfully."));
  return token;
}

// URL encoding
static String urlEncode(const String& str) {
  String encoded = "";
  for (unsigned int i = 0; i < str.length(); i++) {
    char c = str.charAt(i);
    if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
      encoded += c;
    } else {
      char buf[4];
      snprintf(buf, sizeof(buf), "%%%02X", (unsigned char)c);
      encoded += buf;
    }
  }
  return encoded;
}

// ==================== MQTT Connection ====================
static void connectMQTT() {
  // Check if token needs refresh
  time_t now;
  time(&now);

  Serial.printf("[Azure] Current epoch time: %lu\n", (unsigned long)now);

  // On first call tokenExpiryEpoch=0, must generate token
  // Also refresh when token is about to expire (2 minutes before expiry)
  if (tokenExpiryEpoch == 0 || (unsigned long)now >= tokenExpiryEpoch - 120) {
    if ((unsigned long)now < 1700000000) {
      Serial.println(F("[Azure] NTP time not synced yet, cannot generate SAS token."));
      return;
    }
    tokenExpiryEpoch = (unsigned long)now + (SAS_TOKEN_DURATION_MINS * 60);
    sasToken = generateSASToken(tokenExpiryEpoch);
    if (sasToken.length() == 0) {
      Serial.println(F("[Azure] SAS token generation failed!"));
      return;
    }
  }

  // MQTT connection parameters
  String username = String(IOT_HUB_HOST) + "/" + String(DEVICE_ID) + "/?api-version=2021-04-12";

  mqttClient.setServer(IOT_HUB_HOST, 8883);
  mqttClient.setBufferSize(2048);  // Increase buffer size; Twin data can be large
  mqttClient.setCallback(mqttCallback);

  Serial.println(F("[Azure] Connecting to IoT Hub MQTT..."));

  if (mqttClient.connect(DEVICE_ID, username.c_str(), sasToken.c_str())) {
    Serial.println(F("[Azure] MQTT connected to Azure IoT Hub!"));

    // Subscribe to C2D (Cloud-to-Device) messages
    if (mqttClient.subscribe(c2dTopic.c_str())) {
      Serial.println(F("[Azure] Subscribed to C2D messages."));
    } else {
      Serial.println(F("[Azure] Failed to subscribe to C2D topic."));
    }

    // Subscribe to Device Twin responses and patches
    if (mqttClient.subscribe("$iothub/twin/res/#")) {
      Serial.println(F("[Azure] Subscribed to Twin responses."));
    }
    if (mqttClient.subscribe("$iothub/twin/PATCH/properties/desired/#")) {
      Serial.println(F("[Azure] Subscribed to Twin desired updates."));
    }

    // On each MQTT connect, request full Twin document for sync
    mqttClient.publish("$iothub/twin/GET/?$rid=1", "");

    // After successful connection, retry sending cached data
    retryCachedData();

  } else {
    Serial.printf("[Azure] MQTT connection failed, rc=%d\n", mqttClient.state());
  }
}

// ==================== Public Interface ====================

void azure_init() {
  // Initialize cache queue
  for (int i = 0; i < MAX_CACHED_RECORDS; i++) {
    cache[i].used = false;
  }

  // 1. Connect WiFi
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) return;

  // 2. Sync time (SAS Token requires accurate time)
  syncNTP();

  // 3. Set TLS root certificate
  wifiClient.setCACert(ROOT_CA);

  // 4. Build MQTT topics
  telemetryTopic = "devices/" + String(DEVICE_ID) + "/messages/events/";
  c2dTopic = "devices/" + String(DEVICE_ID) + "/messages/devicebound/#";
  twinReportedPub = "$iothub/twin/PATCH/properties/reported/?$rid=";

  // 5. Connect MQTT
  connectMQTT();
}

void azure_loop() {
  // Non-blocking WiFi reconnect (does not block loop)
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastMqttAttempt < MQTT_RETRY_INTERVAL_MS) return;
    lastMqttAttempt = millis();
    tryReconnectWiFi();  // Non-blocking: initiates connection, does not wait
    return;
  }

  // MQTT reconnect with throttle
  if (!mqttClient.connected()) {
    if (millis() - lastMqttAttempt < MQTT_RETRY_INTERVAL_MS) return;
    lastMqttAttempt = millis();
    connectMQTT();
    return;
  }

  // PubSubClient internal maintenance (keepalive + receive C2D messages)
  mqttClient.loop();
}

void azure_sendFeedingData(int catIndex, unsigned long feedingStartMs, float intakeGrams) {
  // Get cat profile
  CatProfile* cat = rfid_getCatProfile(catIndex);
  if (!cat) return;

  // Get current timestamp
  time_t now;
  time(&now);

  // Calculate feeding duration in seconds
  unsigned long feedingDurationSec = (millis() - feedingStartMs) / 1000;

  // Build JSON payload
  JsonDocument doc;
  doc["deviceId"]         = DEVICE_ID;
  doc["catName"]          = cat->name;
  doc["catUID"]           = cat->uid;
  doc["event"]            = "feeding_complete";
  doc["feedingEndTime"]   = (unsigned long)now;
  doc["feedingStartTime"] = (unsigned long)now - feedingDurationSec;
  doc["durationSec"]      = feedingDurationSec;

  // intakeGrams: -1 means weighing unavailable, send null to backend
  if (intakeGrams >= 0) {
    doc["intakeGrams"] = serialized(String(intakeGrams, 1));
  } else {
    doc["intakeGrams"] = nullptr;  // JSON null
  }

  char jsonBuffer[512];
  serializeJson(doc, jsonBuffer, sizeof(jsonBuffer));

  if (mqttClient.connected() && mqttClient.publish(telemetryTopic.c_str(), jsonBuffer)) {
    Serial.printf("[Azure] Data sent: %s\n", jsonBuffer);
  } else {
    Serial.println(F("[Azure] Send failed, caching for retry..."));
    cacheRecord(jsonBuffer);
  }
}

void azure_sendHardwareFault(const char* hardwareName, const char* detail) {
  time_t now;
  time(&now);

  JsonDocument doc;
  doc["deviceId"]  = DEVICE_ID;
  doc["event"]     = "hardware_fault";
  doc["hardware"]  = hardwareName;
  doc["detail"]    = detail;
  doc["timestamp"] = (unsigned long)now;

  char jsonBuffer[256];
  serializeJson(doc, jsonBuffer, sizeof(jsonBuffer));

  if (mqttClient.connected() && mqttClient.publish(telemetryTopic.c_str(), jsonBuffer)) {
    Serial.printf("[Azure] Fault reported: %s\n", jsonBuffer);
  } else {
    Serial.println(F("[Azure] Fault report queued."));
    cacheRecord(jsonBuffer);
  }
}

void azure_sendHeartbeat(bool rfidOk, bool tofOk, bool motorOk) {
  time_t now;
  time(&now);

  JsonDocument doc;
  doc["deviceId"]  = DEVICE_ID;
  doc["event"]     = "heartbeat";
  doc["timestamp"] = (unsigned long)now;
  doc["rfid_ok"]   = rfidOk;
  doc["tof_ok"]    = tofOk;
  doc["motor_ok"]  = motorOk;

  char jsonBuffer[256];
  serializeJson(doc, jsonBuffer, sizeof(jsonBuffer));

  // Heartbeat is not cached if offline; missing a few is acceptable
  if (mqttClient.connected() && mqttClient.publish(telemetryTopic.c_str(), jsonBuffer)) {
    Serial.printf("[Azure] Heartbeat sent: %s\n", jsonBuffer);
  }
}

void azure_sendScanTelemetry(const String& operationId, const String& uid) {
  JsonDocument doc;
  doc["deviceId"]    = DEVICE_ID;
  doc["event"]       = "tag_scanned";
  doc["operationId"] = operationId;
  doc["uid"]         = uid;
  time_t now; time(&now);
  doc["timestamp"]   = (unsigned long)now;

  char buf[256];
  serializeJson(doc, buf, sizeof(buf));
  if (mqttClient.connected()) {
    mqttClient.publish(telemetryTopic.c_str(), buf);
    Serial.printf("[Azure] Scan telemetry sent: %s\n", buf);
  } else {
    cacheRecord(buf);
  }
}

void azure_sendScanStatus(const String& operationId, const char* status, const char* reason) {
  JsonDocument doc;
  doc["deviceId"]    = DEVICE_ID;
  doc["event"]       = "scan_status";
  doc["operationId"] = operationId;
  doc["status"]      = status;
  if (reason) {
    doc["reason"]    = reason;
  }
  time_t now; time(&now);
  doc["timestamp"]   = (unsigned long)now;

  char buf[256];
  serializeJson(doc, buf, sizeof(buf));
  if (mqttClient.connected()) {
    mqttClient.publish(telemetryTopic.c_str(), buf);
    Serial.printf("[Azure] Scan status sent: %s\n", buf);
  } else {
    // Status is important, cache to prevent data loss on disconnect
    cacheRecord(buf);
  }
}
