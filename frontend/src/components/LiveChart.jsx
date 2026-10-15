import React from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

const COLORS = { ax: "#6FD6C7", ay: "#16B8A6", az: "#0E7A6F", gx: "#F0C27B", gy: "#E09A3E", gz: "#9C6B23", p: "#9B7FD4" };

export default function LiveChart({ title, data, channels, unit, height = 160 }) {
  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 10, padding: "12px 14px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{title}</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--mute)" }}>{unit}</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="t" hide />
          <YAxis tick={{ fontSize: 10, fill: "var(--mute)" }} width={40} />
          <Tooltip
            contentStyle={{ background: "var(--panel-raised)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 11 }}
            labelFormatter={() => ""}
          />
          {channels.map((ch) => (
            <Line key={ch} type="monotone" dataKey={ch} stroke={COLORS[ch]} dot={false}
                  strokeWidth={ch.length === 1 ? 2 : 1.4} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
        {channels.map((ch) => (
          <span key={ch} className="mono" style={{ fontSize: 10, color: COLORS[ch] }}>
            ● {ch}
          </span>
        ))}
      </div>
    </div>
  );
}
