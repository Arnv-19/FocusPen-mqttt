"""
The backend's MQTT client. Runs in its own thread (paho's network
loop), bridging into the FastAPI asyncio world only through
ws_manager.broadcast_threadsafe().

Responsibilities:
  - subscribe to focuspen/+/data and focuspen/+/status for every pen
  - feed incoming samples into that device's windowing ring buffer
  - for every emitted window: classify, run the guard layer, broadcast
    the result to the dashboard, and if the device is on-device
    inference instead (focuspen/+/inference), just forward that
  - publish focuspen/<id>/haptic when the guard layer decides to fire,
    or when a manual trigger / instant-demo button requests it
  - publish focuspen/<id>/config when the dashboard edits settings
  - reconnect automatically (paho handles this once loop_start() is
    called and reconnect delay is configured) — we never block on it
"""
from __future__ import annotations
import json
import time
import logging
import paho.mqtt.client as mqtt

from .state import state
from .windowing import windowing_manager
from .classifier import registry, get_guard
from .ws_manager import ws_manager
from . import session as session_store

log = logging.getLogger("mqtt_client")

MQTT_HOST = "10.57.231.71"
MQTT_PORT = 1883
MQTT_USER = ""
MQTT_PASS = ""


class BackendMQTT:
    def __init__(self):
        self.client = mqtt.Client(
            client_id="focuspen-backend",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        if MQTT_USER:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def start(self):
        self.client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.client.loop_start()   # own thread, auto-reconnects

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    # -----------------------------------------------------------
# -----------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        print(f"\n🔥🔥🔥 BACKEND MQTT CONNECTED! Code: {reason_code}\n")
        client.subscribe("focuspen/+/data", qos=0)
        client.subscribe("focuspen/+/status", qos=1)
        client.subscribe("focuspen/+/inference", qos=0)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        print(f"\n⚠️ BACKEND MQTT DISCONNECTED: {reason_code}\n")

    # -----------------------------------------------------------
    # -----------------------------------------------------------
    def _on_message(self, client, userdata, msg):
        print(f"📦 Data arrived from broker on topic: {msg.topic}", flush=True)
        try:
            parts = msg.topic.split("/")
            if len(parts) != 3:
                return
            _, device_id, kind = parts

            if kind == "status":
                payload = msg.payload.decode(errors="replace")
                if payload == "online":
                    state.touch_device(device_id)
                else:
                    state.mark_offline(device_id)
                ws_manager.broadcast_threadsafe({
                    "type": "device_status", "device_id": device_id, "online": payload == "online",
                })
                return

            if kind == "data":
                self._handle_data(device_id, msg.payload)
                return

            if kind == "inference":
                # device is doing its own on-chip inference — skip our
                # classifier for this device and just run the guard layer
                # on what it reports.
                payload = json.loads(msg.payload.decode())
                self._handle_label(device_id, payload["label"], payload.get("confidence", 1.0))
                return

        except Exception:
            log.exception("error handling MQTT message on %s", msg.topic)

    # -----------------------------------------------------------
    def _handle_data(self, device_id: str, raw_payload: bytes):
        payload = json.loads(raw_payload.decode())
        rows = payload["samples"]
        fs = payload.get("fs", state.config.sample_rate_hz)
        state.touch_device(device_id)

        rb = windowing_manager.get_buffer(
            device_id, fs, state.config.window_len_s, state.config.hop_s,
        )
        windows = rb.push_batch(rows)

        # stream raw samples straight through for the live charts —
        # dashboards decimate for display, so send everything we have.
        ws_manager.broadcast_threadsafe({
            "type": "raw", "device_id": device_id, "fs": fs, "samples": rows,
        })

        for window in windows:
            self._classify_and_guard(device_id, window, fs)

    def _classify_and_guard(self, device_id: str, window, fs: int):
        model = registry.active
        import numpy as np
        label, confidence = model.predict(window, fs)
        self._handle_label(device_id, label, confidence)

    def _handle_label(self, device_id: str, label: str, confidence: float):
        guard = get_guard(device_id)
        result = guard.process(label, confidence)

        d = state.get_device(device_id)
        d.last_label = result["label"]
        d.last_confidence = result["confidence"]
        d.fidget_count_window = result["restless_count"]

        ws_manager.broadcast_threadsafe({
            "type": "window", "device_id": device_id, **result,
        })

        if state.recording_session_id is not None:
            session_store.log_window(
                state.recording_session_id, device_id, result["label"],
                result["confidence"], result["decision"], "{}",
            )

        if result["decision"] == "alert":
            self.publish_haptic(device_id, effect_id=1)       # strong click
        elif result["decision"] == "gentle_feedback":
            self.publish_haptic(device_id, effect_id=47)      # soft double buzz

        if result["decision"]:
            ws_manager.broadcast_threadsafe({
                "type": "trigger", "device_id": device_id,
                "decision": result["decision"], "label": result["label"],
                "restless_count": result["restless_count"], "m": result["m"],
            })

    # -----------------------------------------------------------
    def publish_haptic(self, device_id: str, effect_id: int):
        self.client.publish(f"focuspen/{device_id}/haptic", str(effect_id), qos=1)

    def publish_config(self, device_id: str, config: dict):
        self.client.publish(f"focuspen/{device_id}/config", json.dumps(config), qos=1)


backend_mqtt = BackendMQTT()
