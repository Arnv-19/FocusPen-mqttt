"""
Windowing — turns a continuous 7-channel stream into overlapping
fixed-length windows, exactly as described in the architecture:
window_len_s of data, a new window every hop_s.

One RingBuffer per device, so multiple pens never interfere.
Sample rate, window length and hop all come from state.config and can
change live from the dashboard — see reconfigure().
"""
from __future__ import annotations
import numpy as np
from collections import deque
from typing import Optional


class RingBuffer:
    def __init__(self, sample_rate_hz: int, window_len_s: float, hop_s: float):
        self.reconfigure(sample_rate_hz, window_len_s, hop_s)
        self.buf: deque = deque(maxlen=self.window_n * 4)  # generous headroom
        self.samples_since_last_window = 0

    def reconfigure(self, sample_rate_hz: int, window_len_s: float, hop_s: float):
        self.fs = sample_rate_hz
        self.window_n = max(1, int(round(window_len_s * sample_rate_hz)))
        self.hop_n = max(1, int(round(hop_s * sample_rate_hz)))
        # keep existing data if any; deque maxlen adjustment happens lazily
        if hasattr(self, "buf"):
            new_buf = deque(self.buf, maxlen=self.window_n * 4)
            self.buf = new_buf

    def push_batch(self, rows: list[list[float]]):
        """rows: list of [ax,ay,az,gx,gy,gz,p]. Returns list of windows
        (each a numpy array shape (window_n, 7)) emitted by this push."""
        emitted = []
        for row in rows:
            self.buf.append(row)
            self.samples_since_last_window += 1
            if len(self.buf) >= self.window_n and \
               self.samples_since_last_window >= self.hop_n:
                window = np.array(list(self.buf)[-self.window_n:], dtype=np.float32)
                emitted.append(window)
                self.samples_since_last_window = 0
        return emitted


class WindowingManager:
    """One RingBuffer per device_id, all sharing the live global config."""
    def __init__(self):
        self.buffers: dict[str, RingBuffer] = {}

    def get_buffer(self, device_id: str, sample_rate_hz: int,
                   window_len_s: float, hop_s: float) -> RingBuffer:
        if device_id not in self.buffers:
            self.buffers[device_id] = RingBuffer(sample_rate_hz, window_len_s, hop_s)
        return self.buffers[device_id]

    def reconfigure_all(self, sample_rate_hz: int, window_len_s: float, hop_s: float):
        for rb in self.buffers.values():
            rb.reconfigure(sample_rate_hz, window_len_s, hop_s)


windowing_manager = WindowingManager()
