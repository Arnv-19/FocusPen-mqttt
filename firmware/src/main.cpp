/* =========================================================
   FocusPen firmware — Seeed XIAO ESP32-S3
   PlatformIO project. See include/config.h for all settings.

   Design goal: sampling must never stop because the network is
   unhappy. WiFi and MQTT both reconnect through non-blocking state
   machines — nothing in loop() ever calls delay(). If the broker is
   unreachable, samples queue locally (bounded) rather than blocking
   or being silently discarded one-by-one.

   Topics (see config.h):
     publishes -> focuspen/<id>/data        batched raw samples
     publishes -> focuspen/<id>/status       "online"/"offline" (+ LWT)
     subscribes-> focuspen/<id>/haptic       effect id to play
     subscribes-> focuspen/<id>/config       {"sample_rate": N}
   ========================================================= */

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_DRV2605.h>
#include "config.h"

// =========================================================
//  Globals
// =========================================================
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

Adafruit_MPU6050 mpu;
Adafruit_DRV2605 drv;

bool sensorsReady = false;   // MPU6050 initialised
bool hapticReady   = false;  // DRV2605 initialised — pen still streams without it

// ---------- sampling ----------
uint32_t sampleRateHz   = DEFAULT_SAMPLE_RATE_HZ;
uint32_t sampleIntervalUs = 1000000UL / DEFAULT_SAMPLE_RATE_HZ;
uint64_t nextSampleAtUs = 0;

struct Sample {
  float ax, ay, az, gx, gy, gz, p;
};

// one in-progress batch
Sample   currentBatch[SAMPLES_PER_BATCH];
uint16_t currentBatchCount = 0;
uint32_t currentBatchStartMs = 0;

// bounded queue of completed batches awaiting publish
struct QueuedBatch {
  Sample   samples[SAMPLES_PER_BATCH];
  uint16_t count;
  uint32_t startMs;
  bool     used;
};
QueuedBatch batchQueue[MAX_BATCH_QUEUE];
uint8_t queueHead = 0;   // next to publish
uint8_t queueTail = 0;   // next free slot
uint8_t queueCount = 0;

// ---------- WiFi state machine ----------
uint32_t lastWifiAttemptMs = 0;
bool wifiWasConnected = false;

// ---------- MQTT state machine ----------
uint32_t lastMqttAttemptMs = 0;
bool mqttWasConnected = false;

// ---------- heartbeat ----------
uint32_t lastHeartbeatMs = 0;

// ---------- sensor retry ----------
uint32_t lastSensorRetryMs = 0;

// =========================================================
//  Queue helpers (never blocks; drops oldest when full)
// =========================================================
void enqueueBatch(Sample *samples, uint16_t count, uint32_t startMs) {
  if (queueCount >= MAX_BATCH_QUEUE) {
    // queue full: drop the oldest to make room. This only happens
    // during an extended disconnect — see README "known limitations".
    queueHead = (queueHead + 1) % MAX_BATCH_QUEUE;
    queueCount--;
    Serial.println("[queue] full — dropped oldest batch");
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
//  WiFi — non-blocking connect/reconnect
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
  // Non-blocking: we don't wait here. maintainWiFi() is called every
  // loop() and will notice once status() flips to WL_CONNECTED.
}

// =========================================================
//  Haptic + config message handling
// =========================================================
void playHapticEffect(uint8_t effectId) {
  if (!hapticReady) {
    Serial.println("[haptic] requested but driver not ready — ignored");
    return;
  }
  drv.setWaveform(0, effectId);
  drv.setWaveform(1, 0);
  drv.go();   // non-blocking: the DRV2605 plays the effect autonomously
  Serial.printf("[haptic] playing effect #%u\n", effectId);
}

void applySampleRate(uint32_t hz) {
  if (hz < 10 || hz > 400) {
    Serial.println("[config] sample_rate out of accepted range (10-400), ignored");
    return;
  }
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
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, buf);
    if (err) {
      Serial.print("[config] bad JSON: ");
      Serial.println(err.c_str());
      return;
    }
    if (doc.containsKey("sample_rate")) {
      applySampleRate(doc["sample_rate"].as<uint32_t>());
    }
    return;
  }
}

// =========================================================
//  MQTT — non-blocking connect/reconnect, with LWT
// =========================================================
void publishStatus(const char *state, bool retained) {
  if (!mqtt.connected()) return;
  mqtt.publish(TOPIC_STATUS, state, retained);
}

void maintainMQTT() {
  if (WiFi.status() != WL_CONNECTED) return;   // nothing to do without WiFi

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
  mqtt.setBufferSize(2048);   // batched JSON payloads need more than the 256B default

  bool ok;
  const char *clientId = DEVICE_ID;
  if (strlen(MQTT_USER) > 0) {
    ok = mqtt.connect(clientId, MQTT_USER, MQTT_PASS,
                       TOPIC_STATUS, 1, true, "offline");
  } else {
    ok = mqtt.connect(clientId, TOPIC_STATUS, 1, true, "offline");
  }

  if (!ok) {
    Serial.printf("[mqtt] connect failed, rc=%d\n", mqtt.state());
  }
}

// =========================================================
//  Sensors
// =========================================================
void initSensors() {
  Wire.begin(PIN_SDA, PIN_SCL);

  if (!sensorsReady) {
    if (mpu.begin()) {
      mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
      mpu.setGyroRange(MPU6050_RANGE_500_DEG);
      mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
      sensorsReady = true;
      Serial.println("[sensors] MPU6050 ready");
    } else {
      Serial.println("[sensors] MPU6050 not found — will retry");
    }
  }

  if (!hapticReady) {
    if (drv.begin()) {
      drv.selectLibrary(1);
      drv.setMode(DRV2605_MODE_INTTRIG);
      hapticReady = true;
      Serial.println("[haptic] DRV2605 ready");
    } else {
      Serial.println("[haptic] DRV2605 not found — pen will stream without haptics");
    }
  }
}

bool readSample(Sample &s) {
  if (!sensorsReady) return false;

  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  s.ax = a.acceleration.x;
  s.ay = a.acceleration.y;
  s.az = a.acceleration.z;
  s.gx = g.gyro.x * 57.2958f;  // rad/s -> deg/s
  s.gy = g.gyro.y * 57.2958f;
  s.gz = g.gyro.z * 57.2958f;

  int raw = analogRead(PIN_FSR);          // 0..4095 on the XIAO's 12-bit ADC
  s.p = constrain(raw / 4095.0f, 0.0f, 1.0f);

  return true;
}

// =========================================================
//  Publishing — drains the queue when MQTT is up
// =========================================================
void publishQueuedBatches() {
  if (!mqtt.connected()) return;

  QueuedBatch *b;
  // publish at most one batch per loop() to keep mqtt.loop() responsive
  if (!dequeuePeek(&b)) return;

  StaticJsonDocument<3072> doc;
  doc["device_id"] = DEVICE_ID;
  doc["batch_start_ms"] = b->startMs;
  doc["n"] = b->count;
  doc["fs"] = sampleRateHz;
  JsonArray samples = doc.createNestedArray("samples");
  for (uint16_t i = 0; i < b->count; i++) {
    JsonArray row = samples.createNestedArray();
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
  // on failure, batch stays queued and is retried next loop()
}

// =========================================================
//  Sampling — non-blocking timer, fills batch, enqueues when full
// =========================================================
void sampleIfDue() {
  uint64_t nowUs = micros();
  if (nowUs < nextSampleAtUs) return;
  nextSampleAtUs = nowUs + sampleIntervalUs;

  Sample s;
  if (!readSample(s)) return;   // sensor not ready yet; skip silently

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
  delay(300);   // allow USB serial to settle — not on the hot sampling path
  pinMode(PIN_LED_STATUS, OUTPUT);
  analogReadResolution(12);

  Serial.println("\n==================================");
  Serial.println(" FocusPen — " DEVICE_ID);
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
