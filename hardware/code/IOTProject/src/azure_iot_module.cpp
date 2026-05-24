#include "azure_iot_module.h"
#include "azure_config.h"
#include "config.h"
#include "rfid_module.h"

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>

// mbedtls 用于 SAS Token 的 HMAC-SHA256 签名 (ESP32 自带，无需额外安装)
#include <mbedtls/md.h>
#include <mbedtls/base64.h>

// ==================== Azure IoT Hub Root CA ====================
// DigiCert Global Root G2 — Azure IoT Hub 使用的根证书
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

// ==================== 全局对象 ====================
static WiFiClientSecure wifiClient;
static PubSubClient mqttClient(wifiClient);

// MQTT Topics
static String telemetryTopic;
static String c2dTopic;

// SAS Token
static String sasToken;
static unsigned long tokenExpiryEpoch = 0;

// MQTT 重连节流
static unsigned long lastMqttAttempt = 0;
const unsigned long MQTT_RETRY_INTERVAL_MS = 5000;

// ==================== 数据缓存队列 ====================
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
  Serial.println(F("[Azure] 📦 Data cached for retry."));
}

static void retryCachedData() {
  for (int i = 0; i < MAX_CACHED_RECORDS; i++) {
    if (cache[i].used) {
      if (mqttClient.publish(telemetryTopic.c_str(), cache[i].json)) {
        Serial.printf("[Azure] 📤 Cached data resent: %s\n", cache[i].json);
        cache[i].used = false;
      } else {
        // 发送失败，下次再试
        break;
      }
    }
  }
}

// 外部状态查询（main.cpp 中定义）
extern int currentCatIndex;

// ==================== C2D 消息回调 ====================
static void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.printf("[C2D] Received message on topic: %s\n", topic);

  // 解析 JSON 指令
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    Serial.printf("[C2D] ❌ JSON parse error: %s\n", err.c_str());
    return;
  }

  const char* action = doc["action"];
  if (!action) {
    Serial.println(F("[C2D] ⚠️ Missing 'action' field"));
    return;
  }

  if (strcmp(action, "add_cat") == 0) {
    // 字段完整性检查
    if (!doc.containsKey("uid") || !doc.containsKey("name") ||
        !doc.containsKey("bowlSteps") || !doc.containsKey("bowlIndex")) {
      Serial.println(F("[C2D] ❌ add_cat: missing required fields (uid/name/bowlSteps/bowlIndex)"));
      return;
    }
    String uid = doc["uid"].as<String>();
    String name = doc["name"].as<String>();
    int bowlSteps = doc["bowlSteps"].as<int>();
    int bowlIndex = doc["bowlIndex"].as<int>();
    int idx = rfid_addCat(uid, name, bowlSteps, bowlIndex);
    Serial.printf("[C2D] %s 添加猫: %s → 索引 %d\n", (idx >= 0) ? "✅" : "❌", name.c_str(), idx);

  } else if (strcmp(action, "remove_cat") == 0) {
    if (!doc.containsKey("uid")) {
      Serial.println(F("[C2D] ❌ remove_cat: missing 'uid' field"));
      return;
    }
    // 安全检查：正在喂食的猫不能删除
    String uid = doc["uid"].as<String>();
    if (currentCatIndex >= 0) {
      CatProfile* feedingCat = rfid_getCatProfile(currentCatIndex);
      if (feedingCat && feedingCat->uid == uid) {
        Serial.println(F("[C2D] ❌ 该猫正在喂食中，拒绝删除！"));
        return;
      }
    }
    bool ok = rfid_removeCat(uid);
    Serial.printf("[C2D] %s 删除猫: %s\n", ok ? "✅" : "❌", uid.c_str());

  } else {
    Serial.printf("[C2D] ⚠️ Unknown action: %s\n", action);
  }
}

// ==================== 内部函数声明 ====================
static void connectWiFi();
static void syncNTP();
static String generateSASToken(unsigned long expiryEpoch);
static String urlEncode(const String& str);
static void connectMQTT();

// ==================== WiFi 连接 ====================
// 阻塞版：仅在 setup() 首次连接时使用（可以等 20 秒）
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
    Serial.println("\n[Azure] ❌ WiFi connection failed! Check SSID/password.");
  }
}

// 非阻塞版：运行中 WiFi 断了用这个，不卡住 loop()
static void tryReconnectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.println(F("[Azure] WiFi lost, attempting reconnect..."));
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  // 不等！下一次 azure_loop() 会再检查
}

// ==================== NTP 时间同步 ====================
static void syncNTP() {
  Serial.println(F("[Azure] Syncing time via NTP..."));
  configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET, NTP_SERVER);

  // 等待时间同步（最多 15 秒）
  time_t now = 0;
  int attempts = 0;
  while (now < 1700000000 && attempts < 30) {  // 2023年以后的时间戳
    delay(500);
    time(&now);
    attempts++;
  }

  if (now >= 1700000000) {
    struct tm timeinfo;
    localtime_r(&now, &timeinfo);
    Serial.printf("[Azure] Time synced: %s", asctime(&timeinfo));
  } else {
    Serial.println(F("[Azure] ❌ NTP sync failed!"));
  }
}

// ==================== SAS Token 生成 ====================
static String generateSASToken(unsigned long expiryEpoch) {
  // 1. 构建资源 URI
  String resourceUri = String(IOT_HUB_HOST) + "/devices/" + String(DEVICE_ID);
  String encodedUri = urlEncode(resourceUri);

  // 2. 构建待签名字符串
  String toSign = encodedUri + "\n" + String(expiryEpoch);

  Serial.printf("[Azure] SAS: URI=%s\n", resourceUri.c_str());
  Serial.printf("[Azure] SAS: Expiry=%lu\n", expiryEpoch);

  // 3. Base64 解码设备密钥
  size_t keyLen = 0;
  unsigned char decodedKey[64];
  int decRet = mbedtls_base64_decode(decodedKey, sizeof(decodedKey), &keyLen,
                        (const unsigned char*)DEVICE_KEY, strlen(DEVICE_KEY));
  if (decRet != 0) {
    Serial.printf("[Azure] ❌ Base64 decode failed! ret=%d\n", decRet);
    return "";
  }
  Serial.printf("[Azure] SAS: Key decoded, %d bytes\n", (int)keyLen);

  // 4. HMAC-SHA256 签名
  unsigned char signature[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, decodedKey, keyLen);
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)toSign.c_str(), toSign.length());
  mbedtls_md_hmac_finish(&ctx, signature);
  mbedtls_md_free(&ctx);

  // 5. Base64 编码签名
  unsigned char encodedSignature[64];
  size_t encodedLen = 0;
  mbedtls_base64_encode(encodedSignature, sizeof(encodedSignature), &encodedLen,
                        signature, 32);
  String sigStr = String((char*)encodedSignature).substring(0, encodedLen);

  // 6. 组装 SAS Token
  String token = "SharedAccessSignature sr=" + encodedUri +
                 "&sig=" + urlEncode(sigStr) +
                 "&se=" + String(expiryEpoch);

  Serial.println(F("[Azure] SAS Token generated successfully."));
  return token;
}

// URL 编码
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

// ==================== MQTT 连接 ====================
static void connectMQTT() {
  // 检查是否需要刷新 Token
  time_t now;
  time(&now);

  Serial.printf("[Azure] Current epoch time: %lu\n", (unsigned long)now);

  // 首次调用时 tokenExpiryEpoch=0，必须生成 Token
  // 或者当 Token 即将过期时（提前 2 分钟）也刷新
  if (tokenExpiryEpoch == 0 || (unsigned long)now >= tokenExpiryEpoch - 120) {
    if ((unsigned long)now < 1700000000) {
      Serial.println(F("[Azure] ❌ NTP time not synced yet, cannot generate SAS token."));
      return;
    }
    tokenExpiryEpoch = (unsigned long)now + (SAS_TOKEN_DURATION_MINS * 60);
    sasToken = generateSASToken(tokenExpiryEpoch);
    if (sasToken.length() == 0) {
      Serial.println(F("[Azure] ❌ SAS token generation failed!"));
      return;
    }
  }

  // MQTT 连接参数
  String username = String(IOT_HUB_HOST) + "/" + String(DEVICE_ID) + "/?api-version=2021-04-12";

  mqttClient.setServer(IOT_HUB_HOST, 8883);
  mqttClient.setBufferSize(1024);
  mqttClient.setCallback(mqttCallback);  // 设置 C2D 回调

  Serial.println(F("[Azure] Connecting to IoT Hub MQTT..."));

  if (mqttClient.connect(DEVICE_ID, username.c_str(), sasToken.c_str())) {
    Serial.println(F("[Azure] ✅ MQTT connected to Azure IoT Hub!"));

    // 订阅 C2D (Cloud-to-Device) 消息
    if (mqttClient.subscribe(c2dTopic.c_str())) {
      Serial.println(F("[Azure] ✅ Subscribed to C2D messages."));
    } else {
      Serial.println(F("[Azure] ⚠️ Failed to subscribe to C2D topic."));
    }

    // 连接成功后尝试补发缓存数据
    retryCachedData();

  } else {
    Serial.printf("[Azure] ❌ MQTT connection failed, rc=%d\n", mqttClient.state());
  }
}

// ==================== 公开接口 ====================

void azure_init() {
  // 初始化缓存队列
  for (int i = 0; i < MAX_CACHED_RECORDS; i++) {
    cache[i].used = false;
  }

  // 1. 连 WiFi
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) return;

  // 2. 同步时间（SAS Token 需要准确时间）
  syncNTP();

  // 3. 设置 TLS 证书
  wifiClient.setCACert(ROOT_CA);

  // 4. 构建 MQTT Topics
  telemetryTopic = "devices/" + String(DEVICE_ID) + "/messages/events/";
  c2dTopic = "devices/" + String(DEVICE_ID) + "/messages/devicebound/#";

  // 5. 连接 MQTT
  connectMQTT();
}

void azure_loop() {
  // WiFi 断了就非阻塞重连（不卡住 loop）
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastMqttAttempt < MQTT_RETRY_INTERVAL_MS) return;
    lastMqttAttempt = millis();
    tryReconnectWiFi();  // 非阻塞：只发起连接，不等结果
    return;
  }

  // MQTT 断了就重连（带节流）
  if (!mqttClient.connected()) {
    if (millis() - lastMqttAttempt < MQTT_RETRY_INTERVAL_MS) return;
    lastMqttAttempt = millis();
    connectMQTT();
    return;
  }

  // PubSubClient 内部维护（处理心跳 + 接收 C2D 消息）
  mqttClient.loop();
}

void azure_sendFeedingData(int catIndex, unsigned long feedingStartMs, float intakeGrams) {
  // 获取猫咪信息
  CatProfile* cat = rfid_getCatProfile(catIndex);
  if (!cat) return;

  // 获取当前时间戳
  time_t now;
  time(&now);

  // 计算喂食时长（秒）
  unsigned long feedingDurationSec = (millis() - feedingStartMs) / 1000;

  // 构建 JSON
  JsonDocument doc;
  doc["deviceId"]         = DEVICE_ID;
  doc["catName"]          = cat->name;
  doc["catUID"]           = cat->uid;
  doc["event"]            = "feeding_complete";
  doc["feedingEndTime"]   = (unsigned long)now;
  doc["feedingStartTime"] = (unsigned long)now - feedingDurationSec;
  doc["durationSec"]      = feedingDurationSec;

  // intakeGrams: -1 表示称重不可用，传 null 给后端
  if (intakeGrams >= 0) {
    doc["intakeGrams"] = serialized(String(intakeGrams, 1));
  } else {
    doc["intakeGrams"] = nullptr;  // JSON null
  }

  char jsonBuffer[512];
  serializeJson(doc, jsonBuffer, sizeof(jsonBuffer));

  // 尝试发送
  if (mqttClient.connected() && mqttClient.publish(telemetryTopic.c_str(), jsonBuffer)) {
    Serial.printf("[Azure] ✅ Data sent: %s\n", jsonBuffer);
  } else {
    Serial.println(F("[Azure] ⚠️ Send failed, caching for retry..."));
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
    Serial.printf("[Azure] ⚠️ Fault reported: %s\n", jsonBuffer);
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

  // 心跳包如果不通就不缓存了，丢了就丢了，等下个周期
  if (mqttClient.connected() && mqttClient.publish(telemetryTopic.c_str(), jsonBuffer)) {
    Serial.printf("[Azure] 💓 Heartbeat sent: %s\n", jsonBuffer);
  }
}
