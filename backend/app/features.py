"""
Hand-computed measurements — Random Forest / SVM path ONLY.
The TCN never sees these; it reads the raw windowed channels directly
(see classifier.py: TCNModel.predict takes the window unmodified).

Column order in a window: [ax, ay, az, gx, gy, gz, p]
"""
import numpy as np

FEATURE_NAMES = [
    "mean_lateral", "var_lateral", "jerk_rms", "spin_rms", "tilt_rms", "pressure_mean",
]


def extract_features(window: np.ndarray, fs: int) -> np.ndarray:
    """window: (N, 7) array. Returns a (6,) feature vector."""
    ax, ay, az = window[:, 0], window[:, 1], window[:, 2]
    gx, gy, gz = window[:, 3], window[:, 4], window[:, 5]
    p = window[:, 6]

    a_lateral = np.sqrt(ax**2 + ay**2)
    g_spin = np.abs(gz)
    g_tilt = np.sqrt(gx**2 + gy**2)

    mean_lateral = float(np.mean(a_lateral))
    var_lateral = float(np.var(a_lateral))

    dt = 1.0 / fs
    jerk = np.diff(a_lateral) / dt
    jerk_rms = float(np.sqrt(np.mean(jerk**2))) if len(jerk) else 0.0

    spin_rms = float(np.sqrt(np.mean(g_spin**2)))
    tilt_rms = float(np.sqrt(np.mean(g_tilt**2)))
    pressure_mean = float(np.mean(p))

    return np.array([mean_lateral, var_lateral, jerk_rms, spin_rms, tilt_rms, pressure_mean],
                     dtype=np.float32)
