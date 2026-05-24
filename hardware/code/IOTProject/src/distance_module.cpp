#include "distance_module.h"
#include "config.h"
#include <VL53L1X.h>

static VL53L1X distanceSensor;
static bool sensorAvailable = false;

void distance_init() {
  distanceSensor.setTimeout(500);
  if (!distanceSensor.init()) {
    Serial.println(F("[ToF] ❌ Failed to detect sensor! System will run without distance detection."));
    sensorAvailable = false;
    return;  // 不再 while(1) 卡死，改为降级运行
  }

  sensorAvailable = true;

  // 使用短距模式 (Short) 适合 < 1.3米的精确测量
  distanceSensor.setDistanceMode(VL53L1X::Short);
  distanceSensor.setMeasurementTimingBudget(50000); // 50ms 测量时间

  // 开始连续测量，每50ms更新一次
  distanceSensor.startContinuous(50);

  Serial.println(F("[ToF] ✅ Module initialized."));
}

int distance_readMM() {
  if (!sensorAvailable) return 8190;

  int dist = distanceSensor.read();
  if (distanceSensor.timeoutOccurred()) {
    Serial.println(F("[ToF] TIMEOUT"));
    return 8190; // 返回一个极大的值代表失效或无穷远
  }
  return dist;
}

bool distance_isCatPresent() {
  if (!sensorAvailable) return false;  // 传感器不可用 → 当没有猫
  int dist = distance_readMM();
  // 距离 > 0 排除了可能出现的 0 异常值
  // 距离 < 阈值 表示有物体遮挡
  return (dist > 0 && dist < CAT_PRESENT_THRESHOLD_MM);
}

bool distance_isAvailable() {
  return sensorAvailable;
}
