import { useEffect, useRef, useState, useCallback } from "react";

const RAW_BUFFER_LEN = 300;     // ~3s at 100Hz — enough to read the shape live
const WINDOW_STRIP_LEN = 40;    // last 40 windows (~40s) shown in the strip

export function wsURL() {
  const host = window.location.hostname;
  return `ws://${host}:8000/ws`;
}

export function apiBase() {
  const host = window.location.hostname;
  return `http://${host}:8000`;
}

export default function useFocusPenSocket() {
  const [connected, setConnected] = useState(false);
  const [devices, setDevices] = useState({});
  const [config, setConfig] = useState(null);
  const [devMode, setDevMode] = useState(false);
  const [activeModel, setActiveModel] = useState("rule");
  const [availableModels, setAvailableModels] = useState(["rule"]);
  const [raw, setRaw] = useState({});          // { device_id: [{t, ax, ay, ... }] }
  const [windows, setWindows] = useState({});  // { device_id: [{label, confidence, decision, ...}] }
  const [lastTrigger, setLastTrigger] = useState(null);
  const [recordingSessionId, setRecordingSessionId] = useState(null);

  const wsRef = useRef(null);
  const tCounter = useRef({});

  useEffect(() => {
    let cancelled = false;

    function connect() {
      const ws = new WebSocket(wsURL());
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!cancelled) setTimeout(connect, 2000);   // dashboard reconnects too
      };
      ws.onerror = () => ws.close();

      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        handleMessage(msg);
      };
    }

    function handleMessage(msg) {
      switch (msg.type) {
        case "snapshot":
          setDevices(msg.devices || {});
          setConfig(msg.config);
          setDevMode(msg.dev_mode);
          setActiveModel(msg.active_model);
          setAvailableModels(msg.available_models);
          setRecordingSessionId(msg.recording_session_id ?? null);
          break;

        case "session_started":
          setRecordingSessionId(msg.session_id);
          break;

        case "session_stopped":
          setRecordingSessionId(null);
          break;

        case "device_status":
          setDevices((d) => ({
            ...d,
            [msg.device_id]: { ...(d[msg.device_id] || {}), online: msg.online, device_id: msg.device_id },
          }));
          break;

        case "raw": {
          const id = msg.device_id;
          tCounter.current[id] = (tCounter.current[id] || 0) + msg.samples.length;
          setRaw((prev) => {
            const existing = prev[id] || [];
            const added = msg.samples.map((row, i) => ({
              t: tCounter.current[id] - msg.samples.length + i,
              ax: row[0], ay: row[1], az: row[2],
              gx: row[3], gy: row[4], gz: row[5],
              p: row[6],
            }));
            const merged = [...existing, ...added].slice(-RAW_BUFFER_LEN);
            return { ...prev, [id]: merged };
          });
          break;
        }

        case "window": {
          const id = msg.device_id;
          setWindows((prev) => {
            const existing = prev[id] || [];
            const merged = [...existing, msg].slice(-WINDOW_STRIP_LEN);
            return { ...prev, [id]: merged };
          });
          setDevices((d) => ({
            ...d,
            [id]: {
              ...(d[id] || {}),
              device_id: id,
              last_label: msg.label,
              last_confidence: msg.confidence,
              fidget_count_window: msg.restless_count,
            },
          }));
          break;
        }

        case "trigger":
          setLastTrigger({ ...msg, ts: Date.now() });
          break;

        case "config":
          setConfig((c) => ({ ...c, ...msg }));
          break;

        case "dev_mode":
          setDevMode(msg.enabled);
          break;

        case "active_model":
          setActiveModel(msg.model_id);
          break;

        case "model_uploaded":
          setAvailableModels(msg.available_models);
          break;

        default:
          break;
      }
    }

    connect();
    return () => {
      cancelled = true;
      wsRef.current?.close();
    };
  }, []);

  return { connected, devices, config, devMode, activeModel, availableModels, raw, windows, lastTrigger, recordingSessionId };
}
