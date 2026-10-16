#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_DRV2605.h>
#include "config.h"

#define DRV_EN_PIN 18   // Haptic driver enable pin

// =========================================================
//  Globals
// =========================================================
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);
Adafruit_DRV2605 drv;

bool sensorsReady = false;   // MPU6050 initialised
bool hapticReady   = false;  // DRV2605 initialised

// ---------- sampling ----------
uint32_t sampleRateHz   = DEFAULT_SAMPLE_RATE_HZ;
uint32_t sampleIntervalUs = 1000000UL / DEFAULT_SAMPLE_RATE_HZ;
uint64_t nextSampleAtUs = 0;

struct Sample {
  float ax, ay, az, gx, gy, gz, p;
};

Sample   currentBatch[SAMPLES_PER_BATCH];
uint16_t currentBatchCount = 0;
uint32_t currentBatchStartMs = 0;

struct QueuedBatch {
  Sample   samples[SAMPLES_PER_BATCH];
  uint16_t count;
  uint32_t startMs;
  bool     used;
};
QueuedBatch batchQueue[MAX_BATCH_QUEUE];
uint8_t queueHead = 0;
uint8_t queueTail = 0;
uint8_t queueCount = 0;

uint32_t lastWifiAttemptMs = 0;
bool wifiWasConnected = false;

uint32_t lastMqttAttemptMs = 0;
bool mqttWasConnected = false;
uint32_t lastHeartbeatMs = 0;
uint32_t lastSensorRetryMs = 0;

// =========================================================
//  RAW MPU6050 I2C FUNCTIONS (From your working script)
// =========================================================
uint8_t MPU_ADDR = 0x68;

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readRegisters(uint8_t reg, uint8_t count, uint8_t *buffer) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  
  size_t received = Wire.requestFrom((uint16_t)MPU_ADDR, (uint8_t)count, (uint8_t)true);
  if (received != count) {
    while (Wire.available()) Wire.read();
    return false;
  }
  
  for (uint8_t i = 0; i < count; i++) {
    buffer[i] = Wire.read();
  }
  return true;
}

int16_t readInt16(uint8_t highByte, uint8_t lowByte) {
  return (int16_t)(((uint16_t)highByte << 8) | lowByte);
}

bool detectMPU6050() {
  const uint8_t addresses[] = {0x68, 0x69};
  for (uint8_t i = 0; i < 2; i++) {
    Wire.beginTransmission(addresses[i]);
    if (Wire.endTransmission() == 0) {
      MPU_ADDR = addresses[i];
      return true;
    }
  }
  return false;
}

bool initializeMPU6050() {
  if (!detectMPU6050()) return false;
  
  uint8_t identity = 0;
  if (!readRegisters(0x75, 1, &identity)) return false; // WHO_AM_I
  
  if (!writeRegister(0x6B, 0x00)) return false; // Wake up
  delay(100);
  if (!writeRegister(0x1C, 0x00)) return false; // Accel: +/- 2g
  if (!writeRegister(0x1B, 0x00)) return false; // Gyro: +/- 250 dps
  if (!writeRegister(0x1A, 0x03)) return false; // Digital low-pass filter
  
  return true;
}

bool readSample(Sample &s) {
  if (!sensorsReady) return false;
  
  uint8_t data[14];
  if (!readRegisters(0x3B, 14, data)) return false;
  
  int16_t rawAx = readInt16(data[0], data[1]);
  int16_t rawAy = readInt16(data[2], data[3]);
  int16_t rawAz = readInt16(data[4], data[5]);
  
  int16_t rawGx = readInt16(data[8], data[9]);
  int16_t rawGy = readInt16(data[10], data[11]);
  int16_t rawGz = readInt16(data[12], data[13]);
  
  s.ax = rawAx / 16384.0f;
  s.ay = rawAy / 16384.0f;
  s.az = rawAz / 16384.0f;
  
  s.gx = rawGx / 131.0f;
  s.gy = rawGy / 131.0f;
  s.gz = rawGz / 131.0f;
  
  int raw = analogRead(PIN_FSR);
  s.p = constrain(raw / 4095.0f, 0.0f, 1.0f);
  return true;
}

// =========================================================
//  Queue helpers
// =========================================================
void enqueueBatch(Sample *samples, uint16_t count, uint32_t startMs) {
  if (queueCount >= MAX_BATCH_QUEUE) {
    queueHead = (queueHead + 1) % MAX_BATCH_QUEUE;
    queueCount--;
    Serial.println("[queue] full dropped oldest batch");
  }
  QueuedBatch &slot = batchQueue[queueTail];
  memcpy(slot.samples, samples, sizeof(Sample) * count);
  slot.count = count;
  slot.startMs = startMs;
  slot.used = true;
  queueTail = (queueTail + 1) % MAX_BATCH_QUEUE;
  queueCount++;
}

bool dequeuePeek(QueuedBatch **out) {
  if (queueCount == 0) return false;
  *out = &batchQueue[queueHead];
  return true;
}

void dequeuePop() {
  if (queueCount == 0) return;
  batchQueue[queueHead].used = false;
  queueHead = (queueHead + 1) % MAX_BATCH_QUEUE;
  queueCount--;
}

// =========================================================
//  WiFi & MQTT
// =========================================================
void maintainWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiWasConnected) {
      Serial.print("[wifi] connected, IP=");
      Serial.println(WiFi.localIP());
      wifiWasConnected = true;
    }
    return;
  }
  wifiWasConnected = false;
  uint32_t now = millis();
  if (now - lastWifiAttemptMs < WIFI_RETRY_INTERVAL_MS) return;
  lastWifiAttemptMs = now;
  Serial.println("[wifi] (re)connecting...");
  WiFi.disconnect();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void playHapticEffect(uint8_t effectId) {
  if (!hapticReady) return;
  drv.setWaveform(0, effectId);
  drv.setWaveform(1, 0);
  drv.go();
  Serial.printf("[haptic] playing effect #%u\n", effectId);
}

void applySampleRate(uint32_t hz) {
  if (hz < 10 || hz > 400) return;
  sampleRateHz = hz;
  sampleIntervalUs = 1000000UL / hz;
  Serial.printf("[config] sample rate set to %lu Hz\n", hz);
}

void mqttCallback(char *topic, byte *payload, unsigned int length) {
  char buf[256];
  unsigned int n = min(length, (unsigned int)sizeof(buf) - 1);
  memcpy(buf, payload, n);
  buf[n] = '\0';
  String t(topic);
  
  if (t == TOPIC_HAPTIC) {
    uint8_t effectId = (uint8_t)atoi(buf);
    playHapticEffect(effectId);
    return;
  }
  if (t == TOPIC_CONFIG) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, buf);
    if (!err && doc["sample_rate"].is<uint32_t>()) {
      applySampleRate(doc["sample_rate"].as<uint32_t>());
    }
  }
}

void publishStatus(const char *state, bool retained) {
  if (!mqtt.connected()) return;
  mqtt.publish(TOPIC_STATUS, state, retained);
}

void maintainMQTT() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqtt.connected()) {
    if (!mqttWasConnected) {
      Serial.println("[mqtt] connected");
      mqttWasConnected = true;
      mqtt.subscribe(TOPIC_HAPTIC, 1);
      mqtt.subscribe(TOPIC_CONFIG, 1);
      publishStatus("online", true);
    }
    return;
  }
  mqttWasConnected = false;
  uint32_t now = millis();
  if (now - lastMqttAttemptMs < MQTT_RETRY_INTERVAL_MS) return;
  lastMqttAttemptMs = now;
  Serial.println("[mqtt] (re)connecting...");
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setKeepAlive(MQTT_KEEPALIVE_SEC);
  mqtt.setCallback(mqttCallback);
  mqtt.setBufferSize(2048);
  
  bool ok;
  const char *clientId = DEVICE_ID;
  if (strlen(MQTT_USER) > 0) {
    ok = mqtt.connect(clientId, MQTT_USER, MQTT_PASS, TOPIC_STATUS, 1, true, "offline");
  } else {
    ok = mqtt.connect(clientId, TOPIC_STATUS, 1, true, "offline");
  }
  if (!ok) Serial.printf("[mqtt] connect failed, rc=%d\n", mqtt.state());
}

// =========================================================
//  Sensors Init
// =========================================================
void initSensors() {
  if (!sensorsReady) {
    if (initializeMPU6050()) {
      sensorsReady = true;
      Serial.println("[sensors] MPU6050 ready");
    } else {
      Serial.println("[sensors] MPU6050 not found");
    }
  }
  
  if (!hapticReady) {
    if (drv.begin(&Wire)) {
      drv.selectLibrary(1);
      drv.setMode(DRV2605_MODE_INTTRIG);
      hapticReady = true;
      Serial.println("[haptic] DRV2605 ready");
    } else {
      Serial.println("[haptic] DRV2605 not found");
    }
  }
}

// =========================================================
//  Publishing & Sampling
// =========================================================
void publishQueuedBatches() {
  if (!mqtt.connected()) return;
  QueuedBatch *b;
  if (!dequeuePeek(&b)) return;
  
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["batch_start_ms"] = b->startMs;
  doc["n"] = b->count;
  doc["fs"] = sampleRateHz;
  JsonArray samples = doc["samples"].to<JsonArray>();
  
  for (uint16_t i = 0; i < b->count; i++) {
    JsonArray row = samples.add<JsonArray>();
    row.add(roundf(b->samples[i].ax * 1000) / 1000.0);
    row.add(roundf(b->samples[i].ay * 1000) / 1000.0);
    row.add(roundf(b->samples[i].az * 1000) / 1000.0);
    row.add(roundf(b->samples[i].gx * 100) / 100.0);
    row.add(roundf(b->samples[i].gy * 100) / 100.0);
    row.add(roundf(b->samples[i].gz * 100) / 100.0);
    row.add(roundf(b->samples[i].p * 1000) / 1000.0);
  }
  
  char payload[3072];
  size_t len = serializeJson(doc, payload, sizeof(payload));
  if (mqtt.publish(TOPIC_DATA, (const uint8_t *)payload, len, false)) {
    dequeuePop();
  }
}

void sampleIfDue() {
  uint64_t nowUs = micros();
  if (nowUs < nextSampleAtUs) return;
  nextSampleAtUs = nowUs + sampleIntervalUs;
  
  Sample s;
  if (!readSample(s)) return;
  
  if (currentBatchCount == 0) {
    currentBatchStartMs = millis();
  }
  currentBatch[currentBatchCount++] = s;
  
  if (currentBatchCount >= SAMPLES_PER_BATCH) {
    enqueueBatch(currentBatch, currentBatchCount, currentBatchStartMs);
    currentBatchCount = 0;
  }
}

// =========================================================
void setup() {
  Serial.begin(115200);
  delay(300);
  
  pinMode(PIN_LED_STATUS, OUTPUT);
  pinMode(PIN_FSR, INPUT);  
  analogReadResolution(12);

  // Enable Haptic Driver Power
  pinMode(DRV_EN_PIN, OUTPUT);
  digitalWrite(DRV_EN_PIN, HIGH);
  delay(50);
  
  // Start I2C manually ONCE
  Wire.setPins(PIN_SDA, PIN_SCL);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(100000); 
  
  Serial.println("\n==================================");
  Serial.println(" FocusPen   " DEVICE_ID);
  Serial.println("==================================");
  
  initSensors();
  WiFi.mode(WIFI_STA);
}

void loop() {
  maintainWiFi();
  maintainMQTT();
  mqtt.loop();
  
  if (!sensorsReady || !hapticReady) {
    uint32_t now = millis();
    if (now - lastSensorRetryMs >= SENSOR_RETRY_INTERVAL_MS) {
      lastSensorRetryMs = now;
      initSensors();
    }
  }
  
  sampleIfDue();
  publishQueuedBatches();
  
  uint32_t now = millis();
  if (mqtt.connected() && now - lastHeartbeatMs >= STATUS_HEARTBEAT_MS) {
    lastHeartbeatMs = now;
    publishStatus("online", true);
  }
  digitalWrite(PIN_LED_STATUS, mqtt.connected() ? HIGH : LOW);
}