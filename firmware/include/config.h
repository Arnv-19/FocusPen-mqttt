#pragma once

/* =========================================================
   FocusPen — firmware configuration
   Edit this file for your network, device identity, and pins.
   Nothing in main.cpp should need touching for normal setup.
   ========================================================= */

// ---------- identity ----------
// Every pen needs a unique ID — it becomes part of every MQTT topic,
// so two pens on the same network never collide.
#define DEVICE_ID "pen01"

// ---------- WiFi ----------
#define WIFI_SSID     "VIT-HOS2-4"
#define WIFI_PASSWORD "12345678"

// ---------- MQTT broker ----------
#define MQTT_HOST "10.57.231.71"   // your PC's LAN IP running Mosquitto
#define MQTT_PORT 1883
// Leave blank ("") if your broker allows anonymous connections.
#define MQTT_USER ""
#define MQTT_PASS ""

// ---------- pins (raw GPIO numbers — see wiring notes in README) ----------
#define PIN_SDA        5   // D4
#define PIN_SCL        4   // D5
#define PIN_FSR        1   // D0  (ADC)
#define PIN_LED_STATUS 2   // D1  (onboard-adjacent status LED; optional)

// ---------- sampling & batching ----------
// These are DEFAULTS. The PC can override sample rate at runtime over
// the config topic — see handleConfigMessage() in main.cpp.
#define DEFAULT_SAMPLE_RATE_HZ 100
#define SAMPLES_PER_BATCH      20   // ~200ms of data per MQTT publish at 100Hz

// ---------- MQTT topics (derived from DEVICE_ID, do not edit) ----------
#define TOPIC_DATA      "focuspen/" DEVICE_ID "/data"
#define TOPIC_INFERENCE "focuspen/" DEVICE_ID "/inference"
#define TOPIC_HAPTIC    "focuspen/" DEVICE_ID "/haptic"
#define TOPIC_CONFIG    "focuspen/" DEVICE_ID "/config"
#define TOPIC_STATUS    "focuspen/" DEVICE_ID "/status"

// ---------- resilience tunables ----------
#define WIFI_RETRY_INTERVAL_MS     5000
#define MQTT_RETRY_INTERVAL_MS     3000
#define MQTT_KEEPALIVE_SEC         15
#define SENSOR_RETRY_INTERVAL_MS   2000
#define STATUS_HEARTBEAT_MS        10000
#define MAX_BATCH_QUEUE            10   // batches buffered if publish can't keep up
