"""
Session recording. SQLite, zero external dependencies — fine for the
data volumes here (one row per window, roughly 1/second).
"""
import sqlite3
import time
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "sessions.db"
DB_PATH.parent.mkdir(exist_ok=True)

_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            started_at REAL,
            ended_at REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS window_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            device_id TEXT,
            ts REAL,
            label TEXT,
            manual_label TEXT,
            confidence REAL,
            decision TEXT,
            features TEXT
        )
    """)
    conn.commit()
    return conn


def start_session(name: str) -> int:
    with _lock:
        conn = _conn()
        cur = conn.execute(
            "INSERT INTO sessions (name, started_at) VALUES (?, ?)",
            (name, time.time()),
        )
        conn.commit()
        session_id = cur.lastrowid
        conn.close()
        return session_id


def stop_session(session_id: int):
    with _lock:
        conn = _conn()
        conn.execute("UPDATE sessions SET ended_at=? WHERE id=?", (time.time(), session_id))
        conn.commit()
        conn.close()


def log_window(session_id: int, device_id: str, label: str, confidence: float,
               decision: str | None, features_json: str, manual_label: str | None = None):
    with _lock:
        conn = _conn()
        conn.execute(
            """INSERT INTO window_rows
               (session_id, device_id, ts, label, manual_label, confidence, decision, features)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, device_id, time.time(), label, manual_label, confidence, decision, features_json),
        )
        conn.commit()
        conn.close()


def list_sessions():
    with _lock:
        conn = _conn()
        rows = conn.execute(
            "SELECT id, name, started_at, ended_at FROM sessions ORDER BY id DESC"
        ).fetchall()
        conn.close()
        return [
            {"id": r[0], "name": r[1], "started_at": r[2], "ended_at": r[3]}
            for r in rows
        ]


def export_session_csv(session_id: int) -> str:
    with _lock:
        conn = _conn()
        rows = conn.execute(
            """SELECT ts, device_id, label, manual_label, confidence, decision, features
               FROM window_rows WHERE session_id=? ORDER BY ts""",
            (session_id,),
        ).fetchall()
        conn.close()
    lines = ["ts,device_id,label,manual_label,confidence,decision,features"]
    for r in rows:
        lines.append(",".join("" if v is None else str(v) for v in r))
    return "\n".join(lines)
