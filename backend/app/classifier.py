"""
Two things live here:

1. Models — pluggable classifiers behind one interface. Swapping the
   active model (rule / rf / tcn) is just changing which object
   `ModelRegistry.active` points to; nothing else in the pipeline
   changes. A model always returns (label, confidence) where label is
   one of: "writing", "fidgeting", "idle", "gripping".

2. GuardLayer — turns a stream of per-window (label, confidence) into
   at most one decision per device: None, "alert", or "gentle_feedback".
   This is the debounce/confidence/cooldown logic from the design doc,
   now actually running.
"""
from __future__ import annotations
import time
import numpy as np
from collections import deque
from typing import Optional, Tuple

from .features import extract_features

LABELS = ["writing", "fidgeting", "idle", "gripping"]


# =========================================================
#  Models
# =========================================================
class BaseModel:
    id = "base"
    needs_raw_window = False   # True for TCN, False for feature-based models

    def predict(self, window: np.ndarray, fs: int) -> Tuple[str, float]:
        raise NotImplementedError


class RuleModel(BaseModel):
    """
    Always available, no training required. Implements the same
    motion x pressure quadrant used to design the behaviour classes:

                     low pressure        high pressure
      high motion    fidgeting           writing
      low motion     idle                gripping

    This exists so the whole pipeline — windowing, MQTT, dashboard,
    guard layer — is demoable and testable before any model is trained.
    """
    id = "rule"
    needs_raw_window = False

    MOTION_TH = 1.2      # tilt+lateral activity threshold
    PRESSURE_TH = 0.35

    def predict(self, window: np.ndarray, fs: int) -> Tuple[str, float]:
        feats = extract_features(window, fs)
        mean_lateral, var_lateral, jerk_rms, spin_rms, tilt_rms, pressure_mean = feats

        motion = max(spin_rms / 50.0, tilt_rms / 50.0, var_lateral)
        high_motion = motion > self.MOTION_TH
        high_pressure = pressure_mean > self.PRESSURE_TH

        if high_motion and high_pressure:
            label, conf = "writing", 0.75
        elif high_motion and not high_pressure:
            label, conf = "fidgeting", 0.75
        elif not high_motion and high_pressure:
            label, conf = "gripping", 0.70
        else:
            label, conf = "idle", 0.80
        return label, conf


class RandomForestModel(BaseModel):
    id = "rf"
    needs_raw_window = False

    def __init__(self, model_path: str):
        import joblib
        self.clf = joblib.load(model_path)

    def predict(self, window: np.ndarray, fs: int) -> Tuple[str, float]:
        feats = extract_features(window, fs).reshape(1, -1)
        proba = self.clf.predict_proba(feats)[0]
        idx = int(np.argmax(proba))
        classes = list(self.clf.classes_)
        return str(classes[idx]), float(proba[idx])


class TCNModel(BaseModel):
    id = "tcn"
    needs_raw_window = True

    def __init__(self, model_path: str):
        import torch
        self.torch = torch
        self.model = torch.jit.load(model_path, map_location="cpu")
        self.model.eval()

    def predict(self, window: np.ndarray, fs: int) -> Tuple[str, float]:
        # window: (N, 7) -> model expects (1, 7, N), per-channel z-scored.
        x = window.astype(np.float32).T  # (7, N)
        mean = x.mean(axis=1, keepdims=True)
        std = x.std(axis=1, keepdims=True) + 1e-6
        x = (x - mean) / std
        x = x[None, :, :]  # (1, 7, N)
        with self.torch.no_grad():
            logits = self.model(self.torch.from_numpy(x))
            probs = self.torch.softmax(logits, dim=-1).numpy()[0]
        idx = int(np.argmax(probs))
        return LABELS[idx], float(probs[idx])


class ModelRegistry:
    def __init__(self):
        self.models: dict[str, BaseModel] = {"rule": RuleModel()}
        self.active_id = "rule"

    def register_path(self, model_id: str, kind: str, path: str):
        if kind == "rf":
            self.models[model_id] = RandomForestModel(path)
        elif kind == "tcn":
            self.models[model_id] = TCNModel(path)
        else:
            raise ValueError(f"unknown model kind: {kind}")

    def select(self, model_id: str):
        if model_id not in self.models:
            raise KeyError(model_id)
        self.active_id = model_id

    @property
    def active(self) -> BaseModel:
        return self.models[self.active_id]


registry = ModelRegistry()


# =========================================================
#  Guard layer
# =========================================================
class GuardLayer:
    """
    One instance per device. Converts a stream of (label, confidence)
    — one call per window — into at most one decision:
      None | "alert" | "gentle_feedback"

    Mirrors the design: confidence gate, N-of-M persistence with
    hysteresis, cooldown, and a separate sustained-idle timer.
    """
    def __init__(self, persistence_n=4, persistence_m=6,
                 confidence_threshold=0.60, cooldown_s=60.0, idle_alert_s=30.0):
        self.n = persistence_n
        self.m = persistence_m
        self.conf_th = confidence_threshold
        self.cooldown_s = cooldown_s
        self.idle_alert_s = idle_alert_s

        self.history: deque[str] = deque(maxlen=self.m)
        self.restless_state = False   # hysteresis state for fidget/grip
        self.idle_since: Optional[float] = None
        self.last_fire_ts = 0.0

    def reconfigure(self, persistence_n, persistence_m, confidence_threshold,
                     cooldown_s, idle_alert_s):
        self.n = persistence_n
        self.cooldown_s = cooldown_s
        self.conf_th = confidence_threshold
        self.idle_alert_s = idle_alert_s
        if persistence_m != self.m:
            self.m = persistence_m
            self.history = deque(self.history, maxlen=self.m)

    def _restless_count(self) -> int:
        return sum(1 for l in self.history if l in ("fidgeting", "gripping"))

    def process(self, label: str, confidence: float) -> dict:
        """Returns a dict describing what happened this window — always
        includes the running count so the dashboard can show
        'crossed threshold' exactly where it happened."""
        now = time.time()

        if confidence < self.conf_th:
            # Below confidence: don't let this window count toward
            # anything, but still track idle timing on label trend if
            # it was a strong idle reading previously — simplest and
            # safest is to just not push an unreliable window.
            return {
                "label": label, "confidence": confidence, "counted": False,
                "restless_count": self._restless_count(), "m": self.m,
                "decision": None, "cooling_down": now < self.last_fire_ts + self.cooldown_s,
            }

        self.history.append(label)
        count = self._restless_count()

        if not self.restless_state and count >= self.n:
            self.restless_state = True
        elif self.restless_state and count <= 1:
            self.restless_state = False

        if label == "idle":
            if self.idle_since is None:
                self.idle_since = now
        else:
            self.idle_since = None

        decision = None
        cooling_down = now < self.last_fire_ts + self.cooldown_s

        if not cooling_down:
            if self.restless_state:
                decision = "gentle_feedback"
            elif self.idle_since is not None and (now - self.idle_since) >= self.idle_alert_s:
                decision = "alert"

        if decision is not None:
            self.last_fire_ts = now
            if decision == "alert":
                self.idle_since = None  # restart the idle timer after firing

        return {
            "label": label, "confidence": confidence, "counted": True,
            "restless_count": count, "m": self.m,
            "decision": decision, "cooling_down": cooling_down,
        }


guard_layers: dict[str, GuardLayer] = {}


def get_guard(device_id: str) -> GuardLayer:
    if device_id not in guard_layers:
        from .state import state
        c = state.config
        guard_layers[device_id] = GuardLayer(
            persistence_n=c.persistence_n, persistence_m=c.persistence_m,
            confidence_threshold=c.confidence_threshold,
            cooldown_s=c.cooldown_s, idle_alert_s=c.idle_alert_s,
        )
    return guard_layers[device_id]
