import React from "react";

const LABEL_COLOR = {
  writing: "#16B8A6",
  fidgeting: "#E09A3E",
  idle: "#5B6B80",
  gripping: "#9B7FD4",
};
const LABEL_SHORT = { writing: "W", fidgeting: "F", idle: "I", gripping: "G" };

export default function WindowStrip({ deviceId, windows, config }) {
  const latest = windows[windows.length - 1];
  const n = config?.persistence_n ?? 4;
  const m = config?.persistence_m ?? 6;
  const count = latest?.restless_count ?? 0;
  const crossed = count >= n;

  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 10, padding: "12px 14px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Windowing — {deviceId}</span>
        <span
          className="mono"
          style={{
            fontSize: 12, padding: "3px 8px", borderRadius: 6,
            background: crossed ? "rgba(224,154,62,0.18)" : "rgba(91,107,128,0.18)",
            color: crossed ? "var(--amber)" : "var(--mute)",
            fontWeight: 700,
          }}
        >
          {count} / {m} restless · {crossed ? `≥${n} → threshold crossed` : `need ${n} to fire`}
        </span>
      </div>

      <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
        {windows.map((w, i) => {
          const fired = w.decision && w.decision !== null;
          return (
            <div
              key={i}
              title={`${w.label} (${(w.confidence * 100).toFixed(0)}%)${fired ? " — " + w.decision : ""}`}
              style={{
                width: 22, height: 28,
                background: LABEL_COLOR[w.label] || "#444",
                opacity: w.counted === false ? 0.35 : 1,
                borderRadius: 4,
                display: "flex", alignItems: "center", justifyContent: "center",
                position: "relative",
                outline: fired ? "2px solid var(--amber)" : "none",
              }}
            >
              <span className="mono" style={{ fontSize: 11, color: "white", fontWeight: 700 }}>
                {LABEL_SHORT[w.label] || "?"}
              </span>
              {fired && (
                <span style={{
                  position: "absolute", top: -8, fontSize: 9, color: "var(--amber)",
                }}>▼</span>
              )}
            </div>
          );
        })}
        {windows.length === 0 && (
          <span style={{ color: "var(--mute)", fontSize: 12 }}>waiting for data…</span>
        )}
      </div>

      <div style={{ display: "flex", gap: 14, marginTop: 10, fontSize: 11 }}>
        {Object.entries(LABEL_SHORT).map(([label, short]) => (
          <span key={label} style={{ color: LABEL_COLOR[label] }}>
            <b className="mono">{short}</b> {label}
          </span>
        ))}
      </div>
    </div>
  );
}
