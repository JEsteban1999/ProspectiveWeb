/* Slider — range control with mono numeric readout (HU thresholds, smoothing…). */

import { useId } from "react";

export function Slider({
  label,
  min,
  max,
  step = 1,
  value,
  onChange,
  unit = "",
}: {
  label: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (v: number) => void;
  unit?: string;
}) {
  const id = useId();
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", marginBottom: 6 }}>
        <label htmlFor={id} style={{ flex: 1, fontSize: 13, color: "var(--muted-foreground)" }}>
          {label}
        </label>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--foreground)" }}>
          {value}
          <span style={{ color: "var(--muted-foreground)", fontSize: 11 }}>{unit}</span>
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: "100%", accentColor: "var(--brand-slate)" }}
      />
    </div>
  );
}
