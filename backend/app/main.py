"""
FocusPen backend — FastAPI.

Run:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
import asyncio
import os
import shutil
from pathlib import Path
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .state import state
from .ws_manager import ws_manager
from .mqtt_client import backend_mqtt
from .windowing import windowing_manager
from .classifier import registry
from . import session as session_store

MODELS_DIR = Path(__file__).parent.parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

DEV_MODE_PASSWORD = os.environ.get("FOCUSPEN_DEV_PASSWORD", "focuspen-dev")

app = FastAPI(title="FocusPen backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    loop = asyncio.get_running_loop()
    ws_manager.bind_loop(loop)
    backend_mqtt.start()

@app.on_event("shutdown")
async def shutdown():
    backend_mqtt.stop()

# =========================================================
#  WebSocket — the live feed
# =========================================================
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        await ws.send_json({
            "type": "snapshot",
            "devices": state.snapshot_devices(),
            "config": state.config.as_dict(),
            "dev_mode": state.dev_mode,
            "active_model": registry.active_id,
            "available_models": list(registry.models.keys()),
            "recording_session_id": state.recording_session_id,
        })
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)

# =========================================================
#  State / config
# =========================================================
@app.get("/api/state")
def get_state():
    return {
        "devices": state.snapshot_devices(),
        "config": state.config.as_dict(),
        "dev_mode": state.dev_mode,
        "active_model": registry.active_id,
        "available_models": list(registry.models.keys()),
        "recording_session_id": state.recording_session_id,
    }

class ConfigUpdate(BaseModel):
    sample_rate_hz: int | None = None
    window_len_s: float | None = None
    hop_s: float | None = None
    confidence_threshold: float | None = None
    persistence_n: int | None = None
    persistence_m: int | None = None
    cooldown_s: float | None = None
    idle_alert_s: float | None = None

@app.put("/api/config")
def update_config(update: ConfigUpdate):
    if not state.dev_mode:
        raise HTTPException(403, "dev mode is off — enable it to edit config")

    c = state.config
    for field, value in update.dict(exclude_unset=True).items():
        setattr(c, field, value)

    windowing_manager.reconfigure_all(c.sample_rate_hz, c.window_len_s, c.hop_s)

    from .classifier import guard_layers
    for g in guard_layers.values():
        g.reconfigure(c.persistence_n, c.persistence_m, c.confidence_threshold,
                       c.cooldown_s, c.idle_alert_s)

    for device_id in state.devices:
        backend_mqtt.publish_config(device_id, {"sample_rate": c.sample_rate_hz})

    ws_manager.broadcast_threadsafe({"type": "config", **c.as_dict()})
    return c.as_dict()

# =========================================================
#  Dev mode
# =========================================================
class DevModeRequest(BaseModel):
    enabled: bool
    password: str = ""

@app.post("/api/devmode")
def set_dev_mode(req: DevModeRequest):
    if req.enabled:
        if req.password != DEV_MODE_PASSWORD:
            raise HTTPException(401, "wrong dev-mode password")
        state.dev_mode = True
    else:
        state.dev_mode = False
    ws_manager.broadcast_threadsafe({"type": "dev_mode", "enabled": state.dev_mode})
    return {"dev_mode": state.dev_mode}

# =========================================================
#  Manual / instant trigger
# =========================================================
class TriggerRequest(BaseModel):
    device_id: str
    effect_id: int

@app.post("/api/trigger")
def manual_trigger(req: TriggerRequest):
    if not state.dev_mode:
        raise HTTPException(403, "dev mode is off — enable it to send manual triggers")
    backend_mqtt.publish_haptic(req.device_id, req.effect_id)
    ws_manager.broadcast_threadsafe({
        "type": "trigger", "device_id": req.device_id,
        "decision": "manual", "label": "manual", "effect_id": req.effect_id,
    })
    return {"ok": True}

# =========================================================
#  Models — switch / upload weights
# =========================================================
@app.post("/api/models/select")
def select_model(model_id: str = Form(...)):
    if not state.dev_mode:
        raise HTTPException(403, "dev mode is off — enable it to switch models")
    try:
        registry.select(model_id)
    except KeyError:
        raise HTTPException(404, f"unknown model '{model_id}'")
    state.config.active_model_id = model_id
    ws_manager.broadcast_threadsafe({"type": "active_model", "model_id": model_id})
    return {"active_model": model_id}

@app.post("/api/models/upload")
async def upload_model(
    file: UploadFile = File(...),
    kind: str = Form(...),       
    model_id: str = Form(...),
):
    if not state.dev_mode:
        raise HTTPException(403, "dev mode is off — enable it to upload models")
    if kind not in ("rf", "tcn"):
        raise HTTPException(400, "kind must be 'rf' or 'tcn'")

    # Save as .onnx if it's a TCN model
    ext = 'joblib' if kind == 'rf' else 'onnx'
    dest = MODELS_DIR / f"{model_id}.{ext}"
    
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        registry.register_path(model_id, kind, str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"failed to load model: {e}")

    ws_manager.broadcast_threadsafe({
        "type": "model_uploaded", "model_id": model_id, "kind": kind,
        "available_models": list(registry.models.keys()),
    })
    return {"model_id": model_id, "kind": kind}

# =========================================================
#  Session recording
# =========================================================
class SessionStartRequest(BaseModel):
    name: str = "session"

@app.post("/api/session/start")
def start_session(req: SessionStartRequest):
    if not state.dev_mode:
        raise HTTPException(403, "dev mode is off")
    if state.recording_session_id is not None:
        raise HTTPException(409, "a session is already recording")
    sid = session_store.start_session(req.name)
    state.recording_session_id = sid
    ws_manager.broadcast_threadsafe({"type": "session_started", "session_id": sid})
    return {"session_id": sid}

@app.post("/api/session/stop")
def stop_session():
    if state.recording_session_id is None:
        raise HTTPException(409, "no session is recording")
    sid = state.recording_session_id
    session_store.stop_session(sid)
    state.recording_session_id = None
    ws_manager.broadcast_threadsafe({"type": "session_stopped", "session_id": sid})
    return {"session_id": sid}

@app.get("/api/session/list")
def list_sessions():
    return session_store.list_sessions()

@app.get("/api/session/{session_id}/export", response_class=PlainTextResponse)
def export_session(session_id: int):
    return session_store.export_session_csv(session_id)