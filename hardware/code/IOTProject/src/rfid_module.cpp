#include "rfid_module.h"
#include "config.h"
#include <MFRC522_I2C.h>
#include <Preferences.h>   // ESP32 NVS 掉电不丢失存储

// 实例化 RFID 对象 (使用配置中的 I2C 地址，Reset 脚填 -1 不使用硬件复位)
static MFRC522_I2C mfrc522(RFID_I2C_ADDR, -1);

// 白名单（动态管理，从 NVS 加载）
static CatProfile catProfiles[MAX_CATS];
static int catCount = 0;

// NVS 存储
static Preferences prefs;

// 硬件可用性
static bool rfidAvailable = false;

// ==================== NVS 读写 ====================

static void loadFromNVS() {
  prefs.begin("cats", true);  // 只读
  catCount = prefs.getInt("count", 0);
  if (catCount > MAX_CATS) catCount = MAX_CATS;

  for (int i = 0; i < catCount; i++) {
    String idx = String(i);
    catProfiles[i].uid       = prefs.getString(("uid" + idx).c_str(), "");
    catProfiles[i].name      = prefs.getString(("name" + idx).c_str(), "");
    catProfiles[i].bowlSteps = prefs.getInt(("bowl" + idx).c_str(), 0);
    catProfiles[i].bowlIndex = prefs.getInt(("bidx" + idx).c_str(), i);  // 默认 bowlIndex = 索引
  }
  prefs.end();
}

static void saveToNVS() {
  prefs.begin("cats", false);  // 读写
  prefs.clear();  // 清除所有旧 key，防止删猫后残留脏数据
  prefs.putInt("count", catCount);

  for (int i = 0; i < catCount; i++) {
    String idx = String(i);
    prefs.putString(("uid" + idx).c_str(), catProfiles[i].uid);
    prefs.putString(("name" + idx).c_str(), catProfiles[i].name);
    prefs.putInt(("bowl" + idx).c_str(), catProfiles[i].bowlSteps);
    prefs.putInt(("bidx" + idx).c_str(), catProfiles[i].bowlIndex);
  }
  prefs.end();
  Serial.printf("[RFID] 白名单已保存到 NVS (%d 只猫)\n", catCount);
}

// ==================== 辅助函数 ====================

// 字节数组转大写无空格字符串
static String getUIDString(byte *uid, byte uidSize) {
  String uidString = "";
  for (byte i = 0; i < uidSize; i++) {
    if (uid[i] < 0x10) uidString += "0";
    uidString += String(uid[i], HEX);
  }
  uidString.toUpperCase();
  return uidString;
}

// ==================== 公开接口 ====================

void rfid_init() {
  mfrc522.PCD_Init();

  // 检查 RFID 硬件是否正常
  byte version = mfrc522.PCD_ReadRegister(mfrc522.VersionReg);
  if (version == 0x00 || version == 0xFF) {
    Serial.println(F("[RFID] ❌ Module not detected! Check wiring."));
    rfidAvailable = false;
  } else {
    Serial.printf("[RFID] ✅ Module ready (firmware: 0x%02X)\n", version);
    rfidAvailable = true;
  }

  // 从 NVS 加载白名单
  loadFromNVS();

  // 如果 NVS 为空（首次烧录），写入默认的两只猫
  if (catCount == 0) {
    Serial.println(F("[RFID] NVS 为空，写入默认猫..."));
    rfid_addCat("B9BD18C9", "CatA", BOWL_LEFT_STEPS, 0);        // 左碗
    rfid_addCat("0420D6BAFD1691", "CatB", BOWL_RIGHT_STEPS, 1);  // 右碗
  }

  // 打印已注册的猫咪
  Serial.println(F("--- 已注册猫咪 ---"));
  for (int i = 0; i < catCount; i++) {
    Serial.printf("  [%d] %s  UID: %s  碗步数: %d  碗编号: %d\n",
                  i, catProfiles[i].name.c_str(), catProfiles[i].uid.c_str(),
                  catProfiles[i].bowlSteps, catProfiles[i].bowlIndex);
  }
  Serial.println(F("------------------"));
}

bool rfid_tryRead(String &outUID) {
  if (!rfidAvailable) return false;

  // 如果没有新卡
  if (!mfrc522.PICC_IsNewCardPresent()) {
    return false;
  }
  // 如果无法读取
  if (!mfrc522.PICC_ReadCardSerial()) {
    return false;
  }

  // 成功读取，转换 UID
  outUID = getUIDString(mfrc522.uid.uidByte, mfrc522.uid.size);

  // 读完立刻休眠该卡片，避免持续重复触发读取
  mfrc522.PICC_HaltA();

  return true;
}

int rfid_verifyCat(const String &uid) {
  for (int i = 0; i < catCount; i++) {
    if (catProfiles[i].uid == uid) {
      return i; // 匹配成功
    }
  }
  return -1; // 未授权
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
  // 检查是否已满（最多 2 只猫，受限于 2 个 Load Cell）
  if (catCount >= MAX_CATS) {
    Serial.println(F("[RFID] ❌ 白名单已满（最多2只），无法添加"));
    return -1;
  }

  // 检查 UID 是否已存在（防重复）
  for (int i = 0; i < catCount; i++) {
    if (catProfiles[i].uid == uid) {
      Serial.printf("[RFID] ⚠️ UID %s 已存在于索引 %d\n", uid.c_str(), i);
      return i;
    }
  }

  // 检查碗编号是否冲突（每个碗只能分配给一只猫）
  for (int i = 0; i < catCount; i++) {
    if (catProfiles[i].bowlIndex == bowlIndex) {
      Serial.printf("[RFID] ❌ 碗 %d 已被 %s 占用，无法分配给 %s\n",
                    bowlIndex, catProfiles[i].name.c_str(), name.c_str());
      return -1;
    }
  }

  // bowlIndex 合法性检查
  if (bowlIndex < 0 || bowlIndex > 1) {
    Serial.printf("[RFID] ❌ bowlIndex 必须为 0(左碗) 或 1(右碗)，收到 %d\n", bowlIndex);
    return -1;
  }

  // 添加
  int idx = catCount;
  catProfiles[idx].uid = uid;
  catProfiles[idx].name = name;
  catProfiles[idx].bowlSteps = bowlSteps;
  catProfiles[idx].bowlIndex = bowlIndex;
  catCount++;

  // 保存到 NVS
  saveToNVS();

  Serial.printf("[RFID] ✅ 已添加: %s (UID: %s, 碗编号: %d)\n",
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
    Serial.printf("[RFID] ⚠️ UID %s 不在白名单中\n", uid.c_str());
    return false;
  }

  Serial.printf("[RFID] 🗑️ 删除: %s (UID: %s)\n",
                catProfiles[removeIdx].name.c_str(), uid.c_str());

  // 把后面的元素往前移（填补空位）
  for (int i = removeIdx; i < catCount - 1; i++) {
    catProfiles[i] = catProfiles[i + 1];
  }
  catCount--;

  // 【核心修复】补偿正在喂食的猫的索引偏移
  extern int currentCatIndex;
  if (currentCatIndex > removeIdx) {
    // 正在吃饭的猫被往前移了一位，更新游标
    currentCatIndex--;
  } else if (currentCatIndex == removeIdx) {
    // 正在吃饭的猫被删了（双保险防守）
    currentCatIndex = -1;
  }

  // 清空最后一个位置
  catProfiles[catCount] = {"", "", 0, 0};

  // 保存到 NVS
  saveToNVS();

  return true;
}

bool rfid_isAvailable() {
  return rfidAvailable;
}
