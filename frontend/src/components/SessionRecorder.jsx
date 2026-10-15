import React, { useEffect, useState } from "react";
import { apiBase } from "../hooks/useFocusPenSocket";

export default function SessionRecorder({ devMode, recordingSessionId }) {
  const [name, setName] = useState("session-" + new Date().toISOString().slice(0, 16));
  const [sessions, setSessions] = useState([]);
  const [err, setErr] = useState("");

  async function refresh() {
    const res = await fetch(apiBase() + "/api/session/list");
    setSessions(await res.json());
  }
  useEffect(() => { refresh(); }, [recordingSessionId]);

  async function start() {
    setErr("");
    const res = await fetch(apiBase() + "/api/session/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) setErr(await res.text());
    refresh();
  }
  async function stop() {
    const res = await fetch(apiBase() + "/api/session/stop", { method: "POST" });
    if (!res.ok) setErr(await res.text());
    refresh();
  }

  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 10, padding: 14 }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Session recording</div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          disabled={!devMode || !!recordingSessionId}
          value={name} onChange={(e) => setName(e.target.value)}
          style={{ flex: 1, background: "var(--panel-raised)", border: "1px solid var(--line)", borderRadius: 6, color: "var(--text)", padding: "6px 8px" }}
        />
        {!recordingSessionId ? (
          <button disabled={!devMode} onClick={start} style={{ background: "var(--teal-dim)", border: "none", borderRadius: 6, color: "white", padding: "0 14px" }}>
            ● Record
          </button>
        ) : (
          <button onClick={stop} style={{ background: "var(--red)", border: "none", borderRadius: 6, color: "white", padding: "0 14px" }}>
            ■ Stop
          </button>
        )}
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 11, marginTop: 6 }}>{err}</div>}

      <div style={{ marginTop: 10, maxHeight: 160, overflowY: "auto" }}>
        {sessions.map((s) => (
          <div key={s.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "4px 0", borderBottom: "1px solid var(--line)" }}>
            <span>{s.name} {!s.ended_at && <span style={{ color: "var(--red)" }}>● recording</span>}</span>
            <a href={apiBase() + `/api/session/${s.id}/export`} target="_blank" rel="noreferrer" style={{ color: "var(--teal)" }}>
              export CSV
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}
