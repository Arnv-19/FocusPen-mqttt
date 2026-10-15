import React, { useState } from "react";
import { apiBase } from "../hooks/useFocusPenSocket";

const field = { display: "flex", flexDirection: "column", gap: 4, fontSize: 11, color: "var(--mute)" };
const input = {
  background: "var(--panel-raised)", border: "1px solid var(--line)", borderRadius: 6,
  color: "var(--text)", padding: "6px 8px", fontSize: 13, width: "100%",
};
const sectionTitle = { fontSize: 12, fontWeight: 700, letterSpacing: 0.4, color: "var(--mute)", marginBottom: 8, marginTop: 18 };

export default function ControlPanel({ config, devMode, activeModel, availableModels, devices }) {
  const [draft, setDraft] = useState(config || {});
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [triggerDevice, setTriggerDevice] = useState("");
  const [triggerEffect, setTriggerEffect] = useState(47);
  const [sessionName, setSessionName] = useState("session-1");
  const [modelFile, setModelFile] = useState(null);
  const [modelKind, setModelKind] = useState("rf");
  const [modelId, setModelId] = useState("");

  React.useEffect(() => setDraft(config || {}), [config]);

  async function call(path, body, method = "POST") {
    setErr(""); setBusy(true);
    try {
      const res = await fetch(apiBase() + path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t);
      }
      return await res.json();
    } catch (e) {
      setErr(String(e.message || e));
      throw e;
    } finally {
      setBusy(false);
    }
  }

  async function toggleDevMode() {
    if (devMode) {
      await call("/api/devmode", { enabled: false, password: "" });
    } else {
      await call("/api/devmode", { enabled: true, password: pw });
    }
  }

  async function saveConfig() {
    await call("/api/config", draft, "PUT");
  }

  async function fireManual() {
    if (!triggerDevice) return;
    await call("/api/trigger", { device_id: triggerDevice, effect_id: Number(triggerEffect) });
  }

  async function uploadModel() {
    if (!modelFile || !modelId) return;
    const form = new FormData();
    form.append("file", modelFile);
    form.append("kind", modelKind);
    form.append("model_id", modelId);
    setBusy(true); setErr("");
    try {
      const res = await fetch(apiBase() + "/api/models/upload", { method: "POST", body: form });
      if (!res.ok) throw new Error(await res.text());
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function selectModel(id) {
    const form = new FormData();
    form.append("model_id", id);
    await fetch(apiBase() + "/api/models/select", { method: "POST", body: form });
  }

  const deviceIds = Object.keys(devices || {});

  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 10, padding: 16, width: 300, flexShrink: 0 }}>
      {/* ---------------- dev mode ---------------- */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: 700, fontSize: 13 }}>Dev mode</span>
        <span className="mono" style={{
          fontSize: 11, padding: "2px 8px", borderRadius: 999,
          background: devMode ? "rgba(224,92,92,0.18)" : "rgba(130,145,163,0.15)",
          color: devMode ? "var(--red)" : "var(--mute)",
        }}>
          {devMode ? "ON — can send commands" : "OFF — view only"}
        </span>
      </div>
      {!devMode && (
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <input style={input} type="password" placeholder="dev password"
                 value={pw} onChange={(e) => setPw(e.target.value)} />
          <button onClick={toggleDevMode} disabled={busy}
                  style={{ background: "var(--teal-dim)", border: "none", borderRadius: 6, color: "white", padding: "0 12px" }}>
            Enable
          </button>
        </div>
      )}
      {devMode && (
        <button onClick={toggleDevMode} disabled={busy} style={{ marginTop: 8, background: "var(--panel-raised)", border: "1px solid var(--line)", borderRadius: 6, color: "var(--text)", padding: "6px 10px", width: "100%" }}>
          Disable dev mode
        </button>
      )}

      <fieldset disabled={!devMode} style={{ border: "none", padding: 0, margin: 0, opacity: devMode ? 1 : 0.5 }}>
        {/* ---------------- pipeline config ---------------- */}
        <div style={sectionTitle}>PIPELINE CONFIG</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <label style={field}>Sample rate (Hz)
            <input style={input} type="number" value={draft.sample_rate_hz ?? ""} onChange={(e) => setDraft({ ...draft, sample_rate_hz: Number(e.target.value) })} />
          </label>
          <label style={field}>Window (s)
            <input style={input} type="number" step="0.1" value={draft.window_len_s ?? ""} onChange={(e) => setDraft({ ...draft, window_len_s: Number(e.target.value) })} />
          </label>
          <label style={field}>Hop (s)
            <input style={input} type="number" step="0.1" value={draft.hop_s ?? ""} onChange={(e) => setDraft({ ...draft, hop_s: Number(e.target.value) })} />
          </label>
          <label style={field}>Confidence
            <input style={input} type="number" step="0.05" value={draft.confidence_threshold ?? ""} onChange={(e) => setDraft({ ...draft, confidence_threshold: Number(e.target.value) })} />
          </label>
          <label style={field}>Persist N
            <input style={input} type="number" value={draft.persistence_n ?? ""} onChange={(e) => setDraft({ ...draft, persistence_n: Number(e.target.value) })} />
          </label>
          <label style={field}>of M
            <input style={input} type="number" value={draft.persistence_m ?? ""} onChange={(e) => setDraft({ ...draft, persistence_m: Number(e.target.value) })} />
          </label>
          <label style={field}>Cooldown (s)
            <input style={input} type="number" value={draft.cooldown_s ?? ""} onChange={(e) => setDraft({ ...draft, cooldown_s: Number(e.target.value) })} />
          </label>
          <label style={field}>Idle alert (s)
            <input style={input} type="number" value={draft.idle_alert_s ?? ""} onChange={(e) => setDraft({ ...draft, idle_alert_s: Number(e.target.value) })} />
          </label>
        </div>
        <button onClick={saveConfig} style={{ marginTop: 10, width: "100%", background: "var(--teal-dim)", border: "none", borderRadius: 6, color: "white", padding: "8px 0", fontWeight: 600 }}>
          Save config
        </button>

        {/* ---------------- manual trigger ---------------- */}
        <div style={sectionTitle}>INSTANT TRIGGER (demo)</div>
        <select style={input} value={triggerDevice} onChange={(e) => setTriggerDevice(e.target.value)}>
          <option value="">select device…</option>
          {deviceIds.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
          <button onClick={() => { setTriggerEffect(1); fireManual(); }} style={{ flex: 1, background: "var(--amber-dim)", border: "none", borderRadius: 6, color: "white", padding: "8px 0" }}>
            Alert (#1)
          </button>
          <button onClick={() => { setTriggerEffect(47); fireManual(); }} style={{ flex: 1, background: "var(--teal-dim)", border: "none", borderRadius: 6, color: "white", padding: "8px 0" }}>
            Gentle (#47)
          </button>
        </div>

        {/* ---------------- model ---------------- */}
        <div style={sectionTitle}>MODEL</div>
        <select style={input} value={activeModel} onChange={(e) => selectModel(e.target.value)}>
          {availableModels.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
          <input style={input} placeholder="model id (e.g. rf_v1)" value={modelId} onChange={(e) => setModelId(e.target.value)} />
          <select style={input} value={modelKind} onChange={(e) => setModelKind(e.target.value)}>
            <option value="rf">Random Forest (.joblib)</option>
            <option value="tcn">TCN (TorchScript .pt)</option>
          </select>
          <input style={input} type="file" onChange={(e) => setModelFile(e.target.files[0])} />
          <button onClick={uploadModel} style={{ background: "var(--panel-raised)", border: "1px solid var(--line)", borderRadius: 6, color: "var(--text)", padding: "8px 0" }}>
            Upload weights
          </button>
        </div>
      </fieldset>

      {err && <div style={{ color: "var(--red)", fontSize: 11, marginTop: 10 }}>{err}</div>}
    </div>
  );
}
