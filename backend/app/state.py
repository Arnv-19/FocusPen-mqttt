"""
Shared, in-process application state.

Single-process FastAPI app, so plain module-level state (behind a lock
where it's mutated from two threads — the MQTT thread and the API
thread) is sufficient. No external store needed for a capstone deploy.
"""
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional


@dataclass
class PipelineConfig:
    """Everything editable from the dashboard's control panel."""
    sample_rate_hz: int = 100
    window_len_s: float = 2.0
    hop_s: float = 1.0
    confidence_threshold: float = 0.60
    persistence_n: int = 4          # fire after N of last M windows agree
    persistence_m: int = 6
    cooldown_s: float = 60.0
    idle_alert_s: float = 30.0
    active_model_id: str = "rule"   # "rule" | "rf" | "tcn"

    def as_dict(self):
        return asdict(self)


@dataclass
class DeviceState:
    device_id: str
    online: bool = False
    last_seen_ms: int = 0
    last_label: Optional[str] = None
    last_confidence: Optional[float] = None
    fidget_count_window: int = 0     # how many of last M windows were restless
    in_cooldown_until: float = 0.0
    idle_since: Optional[float] = None


class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        self.config = PipelineConfig()
        self.devices: Dict[str, DeviceState] = {}
        self.dev_mode = False
        self.recording_session_id: Optional[int] = None

    def get_device(self, device_id: str) -> DeviceState:
        with self.lock:
            if device_id not in self.devices:
                self.devices[device_id] = DeviceState(device_id=device_id)
            return self.devices[device_id]

    def touch_device(self, device_id: str):
        with self.lock:
            d = self.get_device(device_id)
            d.online = True
            d.last_seen_ms = int(time.time() * 1000)

    def mark_offline(self, device_id: str):
        with self.lock:
            d = self.get_device(device_id)
            d.online = False

    def snapshot_devices(self):
        with self.lock:
            return {k: asdict(v) for k, v in self.devices.items()}


state = AppState()
