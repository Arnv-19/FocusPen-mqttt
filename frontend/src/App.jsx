import React, { useState, useEffect } from "react";
import useFocusPenSocket from "./hooks/useFocusPenSocket";
import LiveChart from "./components/LiveChart";
import WindowStrip from "./components/WindowStrip";
import ControlPanel from "./components/ControlPanel";
import DeviceList from "./components/DeviceList";
import SessionRecorder from "./components/SessionRecorder";

export default function App() {
  const {
    connected, devices, config, devMode, activeModel, availableModels,
    raw, windows, lastTrigger, recordingSessionId,
  } = useFocusPenSocket();

  const [selected, setSelected] = useState(null);

  useEffect(() => {
    const ids = Object.keys(devices);
    if (!selected && ids.length) setSelected(ids[0]);
  }, [devices, selected]);

  const deviceRaw = raw[selected] || [];
  const deviceWindows = windows[selected] || [];

  return (
    <div style={{ minHeight: "100%", padding: "18px 22px 40px" }}>
      {/* ---------------- header ---------------- */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: -0.3 }}>FocusPen</div>
          <div style={{ fontSize: 12, color: "var(--mute)" }}>live monitoring &amp; control</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            width: 9, height: 9, borderRadius: 999,
            background: connected ? "var(--teal)" : "var(--red)",
          }} />
          <span className="mono" style={{ fontSize: 12, color: "var(--mute)" }}>
            {connected ? "backend connected" : "reconnecting…"}
          </span>
        </div>
      </div>

      {lastTrigger && Date.now() - lastTrigger.ts < 4000 && (
        <div style={{
          background: "rgba(224,154,62,0.15)", border: "1px solid var(--amber)", borderRadius: 8,
          padding: "8px 14px", marginBottom: 14, fontSize: 13, color: "var(--amber)",
        }}>
          ▶ {lastTrigger.device_id} — {lastTrigger.decision} fired
          {lastTrigger.restless_count != null ? ` (${lastTrigger.restless_count}/${lastTrigger.m} crossed)` : ""}
        </div>
      )}

      <div style={{ marginBottom: 14 }}>
        <DeviceList devices={devices} selected={selected} onSelect={setSelected} />
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        {/* ---------------- main column ---------------- */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
          {selected ? (
            <>
              <LiveChart title="Accelerometer" unit="m/s²" data={deviceRaw} channels={["ax", "ay", "az"]} />
              <LiveChart title="Gyroscope" unit="°/s" data={deviceRaw} channels={["gx", "gy", "gz"]} />
              <LiveChart title="Pressure" unit="0–1" data={deviceRaw} channels={["p"]} height={110} />
              <WindowStrip deviceId={selected} windows={deviceWindows} config={config} />
              <SessionRecorder devMode={devMode} recordingSessionId={recordingSessionId} />
            </>
          ) : (
            <div style={{ color: "var(--mute)" }}>Waiting for a pen to come online…</div>
          )}
        </div>

        {/* ---------------- control panel ---------------- */}
        <ControlPanel
          config={config}
          devMode={devMode}
          activeModel={activeModel}
          availableModels={availableModels}
          devices={devices}
        />
      </div>
    </div>
  );
}
