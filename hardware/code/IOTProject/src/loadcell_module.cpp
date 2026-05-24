#include "loadcell_module.h"
#include "config.h"
#include "HX711.h"

static HX711 scaleLeft;
static HX711 scaleRight;
static bool lc1Available = false;  // 左碗 HX711 可用性
static bool lc2Available = false;  // 右碗 HX711 可用性

void loadcell_init() {
  // 初始化左碗
  scaleLeft.begin(LC1_DOUT_PIN, LC1_SCK_PIN);
  if (scaleLeft.is_ready()) {
    scaleLeft.set_scale(LOADCELL_1_CALIBRATION);
    scaleLeft.tare(10);  // 取 10 次平均作为零点
    lc1Available = true;
    Serial.println(F("[LoadCell] 左碗 ✅ 初始化完成"));
  } else {
    lc1Available = false;
    Serial.println(F("[LoadCell] 左碗 ❌ HX711 未检测到！"));
  }

  // 初始化右碗
  scaleRight.begin(LC2_DOUT_PIN, LC2_SCK_PIN);
  if (scaleRight.is_ready()) {
    scaleRight.set_scale(LOADCELL_2_CALIBRATION);
    scaleRight.tare(10);
    lc2Available = true;
    Serial.println(F("[LoadCell] 右碗 ✅ 初始化完成"));
  } else {
    lc2Available = false;
    Serial.println(F("[LoadCell] 右碗 ❌ HX711 未检测到！"));
  }
}

float loadcell_readGrams(int bowlIndex) {
  HX711* scale = (bowlIndex == 0) ? &scaleLeft : &scaleRight;
  bool available = (bowlIndex == 0) ? lc1Available : lc2Available;

  if (!available) {
    Serial.printf("[LoadCell] ⚠️ 碗 %d 传感器不可用\n", bowlIndex);
    return -9999.0f;  // -9999 表示"无法读取"（因为正常读数可能是负数）
  }

  if (!scale->is_ready()) {
    Serial.printf("[LoadCell] ⚠️ 碗 %d HX711 未就绪\n", bowlIndex);
    return -9999.0f;
  }

  // 取 5 次平均以获得稳定读数
  float weight = scale->get_units(5);

  // 注意：不要在这里截断负数！
  // 重启时 tare() 以碗里现有猫粮为零点，猫吃掉后读数为负，这是正确的。
  // 食量 = initialWeight - finalWeight，负值会被正确算为正食量。

  return weight;
}

void loadcell_tare(int bowlIndex) {
  HX711* scale = (bowlIndex == 0) ? &scaleLeft : &scaleRight;
  bool available = (bowlIndex == 0) ? lc1Available : lc2Available;
  if (available && scale->is_ready()) {
    scale->tare(10);
    Serial.printf("[LoadCell] 碗 %d 去皮完成\n", bowlIndex);
  }
}

void loadcell_tareAll() {
  loadcell_tare(0);
  loadcell_tare(1);
}
