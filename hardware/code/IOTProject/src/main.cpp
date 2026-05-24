#include <Arduino.h>
#include <Wire.h>
#include "config.h"
#include "rfid_module.h"
#include "motor_module.h"
#include "distance_module.h"
#include "loadcell_module.h"
#include "azure_iot_module.h"

// 状态机定义
enum State { IDLE, DETECTING, OPENING, FEEDING, CLOSING };
static State state = IDLE;

// 运行状态变量（currentCatIndex 非 static，允许 azure_iot_module extern 访问）
int currentCatIndex = -1;
static unsigned long stateEnterTime = 0;
static unsigned long catAbsentStart = 0;   // 猫离开连续计时起点
static unsigned long feedingStartTime = 0; // 记录喂食开始时间，用于上传数据
static float initialWeight = 0;  // 开碗时食物重量（-1 表示称重不可用）
static float finalWeight = 0;    // 关碗时食物重量
static float intakeGrams = 0;    // 本次食量（-1 表示无数据）

// 硬件健康状态（用于心跳包）
static bool motorOk = true;

void printState(const char* stateName) {
  Serial.print(F("==== STATE: "));
  Serial.print(stateName);
  Serial.println(F(" ===="));
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  // 1. 初始化 I2C 总线
  Wire.begin(I2C_SDA, I2C_SCL);

  // 2. 初始化各子模块（任何模块失败都不会卡死系统）
  rfid_init();
  motor_init();
  distance_init();
  loadcell_init();

  // 3. 初始化 Azure IoT Hub 连接 (WiFi + NTP + MQTT)
  azure_init();

  // 打印系统状态
  Serial.println(F("\n--- 🐱 智能猫咪喂食器系统 6.0 已上线 ---"));
  Serial.printf("[系统] RFID: %s | 距离传感器: %s\n",
                rfid_isAvailable() ? "✅" : "❌",
                distance_isAvailable() ? "✅" : "❌");
  Serial.printf("[系统] 白名单猫数: %d\n", rfid_getCatCount());

  // 4. 上报硬件故障（Azure 连上后才能发）
  if (!rfid_isAvailable()) {
    azure_sendHardwareFault("RFID", "init_failed");
  }
  if (!distance_isAvailable()) {
    azure_sendHardwareFault("ToF", "init_failed");
  }

  // 5. 发送开机心跳包
  azure_sendHeartbeat(rfid_isAvailable(), distance_isAvailable(), motorOk);

  printState("IDLE");
}

void loop() {
  // 核心：让电机运行一步（如果有目标的话）。这个函数不阻塞，执行极快。
  motor_update();

  // 维持 Azure MQTT 连接（自动重连 + Token 刷新 + 补发缓存数据）
  azure_loop();

  // 定期发送心跳包 (每 5 分钟)
  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat > 300000) {
    azure_sendHeartbeat(rfid_isAvailable(), distance_isAvailable(), motorOk);
    lastHeartbeat = millis();
  }

  switch (state) {
    case IDLE: {
      // 待机状态：仅靠距离传感器做"门卫"，非常省电
      if (distance_isCatPresent()) {
        Serial.println(F("[IDLE] 🔔 探测到物体进入通道，唤醒 RFID..."));
        state = DETECTING;
        stateEnterTime = millis();
        printState("DETECTING");
      }
      break;
    }

    case DETECTING: {
      // 1. 检查是否超时（可能猫只是路过或者没戴项圈）
      if (millis() - stateEnterTime > RFID_DETECT_TIMEOUT_MS) {
        Serial.println(F("[DETECTING] ❌ RFID读取超时，猫没戴项圈？回到待机"));
        state = IDLE;
        printState("IDLE");
        break;
      }
      
      // 2. 检查猫是不是走开了
      if (!distance_isCatPresent()) {
        Serial.println(F("[DETECTING] 🏃 猫已离开，取消读取，回到待机"));
        state = IDLE;
        printState("IDLE");
        break;
      }

      // 3. 尝试读取 RFID
      String uid;
      if (rfid_tryRead(uid)) {
        Serial.print(F("[DETECTING] 扫描到标签: "));
        Serial.println(uid);

        int catIdx = rfid_verifyCat(uid);
        if (catIdx >= 0) {
          // 身份确认成功！
          CatProfile* cat = rfid_getCatProfile(catIdx);
          Serial.printf(">> 身份确认：欢迎主子 %s！准备开饭...\n", cat->name.c_str());
          
          currentCatIndex = catIdx;
          
          // 给电机发送目标指令（此步非阻塞，仅仅设置目标）
          motor_moveTo(cat->bowlSteps);
          
          state = OPENING;
          stateEnterTime = millis();
          printState("OPENING");
        } else {
          // 身份不匹配，保持 DETECTING 状态直到猫离开或超时
          Serial.println(F("❌ 警告：未登记的非法标签，拒绝开门！"));
          delay(500);  // 防刷屏
        }
      }
      break;
    }

    case OPENING: {
      // 等待电机转到指定碗位
      if (motor_isAtTarget()) {
        motor_disableOutputs(); // 到位后立刻断电防烫
        motorOk = true;         // 电机成功执行，状态恢复正常

        // 记录开碗时的食物重量（用 bowlIndex 而非 catIndex）
        CatProfile* cat = rfid_getCatProfile(currentCatIndex);
        if (cat) {
          initialWeight = loadcell_readGrams(cat->bowlIndex);
          if (initialWeight > -9000.0f) {
            Serial.printf("[OPENING] ⚖️ 初始重量: %.1f g\n", initialWeight);
          } else {
            Serial.println(F("[OPENING] ⚠️ 称重不可用，跳过食量计算"));
          }
        }

        Serial.println(F("[OPENING] 🟢 碗已打开，猫咪开始进食..."));
        state = FEEDING;
        stateEnterTime = millis();
        feedingStartTime = millis();
        catAbsentStart = 0;
        printState("FEEDING");
        break;
      }

      // 电机超时保护：防止电机卡死导致系统永远停在 OPENING
      if (millis() - stateEnterTime > MOTOR_TIMEOUT_MS) {
        Serial.println(F("[OPENING] ❌ 电机超时！强制断电，回到待机"));
        motor_disableOutputs();
        motorOk = false;  // 标记电机故障
        azure_sendHardwareFault("Motor", "opening_timeout");
        currentCatIndex = -1;
        state = IDLE;
        printState("IDLE");
      }
      break;
    }

    case FEEDING: {
      unsigned long now = millis();

      // 逻辑 1：判断猫是否还在吃
      if (distance_isCatPresent()) {
        catAbsentStart = 0;  // 猫还在，随时重置离开计时器
      } else {
        // 猫不在距离传感器阈值内了
        if (catAbsentStart == 0) {
          catAbsentStart = now;  // 记录开始消失的时间
        } else if (now - catAbsentStart > CAT_LEAVE_TIMEOUT_MS) {
          // 已经连续 3 秒没有猫了 -> 确实离开了
          // 记录关碗时的食物重量，计算食量
          CatProfile* cat = rfid_getCatProfile(currentCatIndex);
          if (cat && initialWeight > -9000.0f) {
            finalWeight = loadcell_readGrams(cat->bowlIndex);
            if (finalWeight > -9000.0f) {
              intakeGrams = initialWeight - finalWeight;
              if (intakeGrams < 0) intakeGrams = 0;
            } else {
              intakeGrams = -1;  // 称重不可用
            }
          } else {
            intakeGrams = -1;
          }

          if (cat) {
            if (intakeGrams >= 0) {
              Serial.printf("[FEEDING] ⚖️ 最终重量: %.1f g, 食量: %.1f g\n", finalWeight, intakeGrams);
            }
            Serial.printf("[FEEDING] 🐾 %s 已离开 (连续 %d 秒)，准备关门...\n", 
                          cat->name.c_str(), CAT_LEAVE_TIMEOUT_MS/1000);
          }
          
          motor_returnHome();
          state = CLOSING;
          stateEnterTime = millis();
          printState("CLOSING");
          break;
        }
      }

      // 逻辑 2：最长防霸占时间（超时强制关闭）
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
          Serial.printf("[FEEDING] ⚖️ 超时 - 最终重量: %.1f g, 食量: %.1f g\n", finalWeight, intakeGrams);
        }
        Serial.println(F("[FEEDING] ⏰ 用餐时间达到上限，强制关门！"));
        motor_returnHome();
        state = CLOSING;
        stateEnterTime = millis();
        printState("CLOSING");
      }
      break;
    }

    case CLOSING: {
      // 等待电机转回 0 位（包含齿轮间隙补偿）
      if (motor_isAtTarget()) {
        motor_disableOutputs(); // 关门到位，断电
        motorOk = true;         // 电机成功执行，状态恢复正常

        // 发送喂食记录到 Azure IoT Hub
        azure_sendFeedingData(currentCatIndex, feedingStartTime, intakeGrams);

        Serial.println(F("[CLOSING] --- 门已关紧，系统待机 ---\n"));
        currentCatIndex = -1;
        state = IDLE;
        printState("IDLE");
        break;
      }

      // 电机超时保护
      if (millis() - stateEnterTime > MOTOR_TIMEOUT_MS) {
        Serial.println(F("[CLOSING] ❌ 电机超时！强制断电"));
        motor_disableOutputs();
        motorOk = false;  // 标记电机故障
        azure_sendHardwareFault("Motor", "closing_timeout");

        // 即使关门失败也要上传喂食数据
        azure_sendFeedingData(currentCatIndex, feedingStartTime, intakeGrams);

        currentCatIndex = -1;
        state = IDLE;
        printState("IDLE");
      }
      break;
    }
  }

  // 稍微延迟降低 CPU 和 I2C 总线占用率
  delay(10);
}