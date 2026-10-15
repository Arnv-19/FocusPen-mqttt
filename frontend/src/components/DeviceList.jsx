import React from "react";

const LABEL_COLOR = { writing: "#16B8A6", fidgeting: "#E09A3E", idle: "#5B6B80", gripping: "#9B7FD4" };

export default function DeviceList({ devices, selected, onSelect }) {
  const ids = Object.keys(devices || {});
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {ids.length === 0 && <span style={{ color: "var(--mute)", fontSize: 13 }}>no pens seen yet</span>}
      {ids.map((id) => {
        const d = devices[id];
        return (
          <button
            key={id}
            onClick={() => onSelect(id)}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              background: selected === id ? "var(--panel-raised)" : "var(--panel)",
              border: `1px solid ${selected === id ? "var(--teal)" : "var(--line)"}`,
              borderRadius: 999, padding: "6px 12px", color: "var(--text)",
            }}
          >
            <span style={{
              width: 8, height: 8, borderRadius: 999,
              background: d.online ? "var(--teal)" : "var(--red)",
            }} />
            <span className="mono" style={{ fontSize: 12 }}>{id}</span>
            {d.last_label && (
              <span className="mono" style={{ fontSize: 11, color: LABEL_COLOR[d.last_label] || "var(--mute)" }}>
                {d.last_label}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
