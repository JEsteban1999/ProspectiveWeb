/* FileField — styled file picker that shows the chosen filename. Shared by the
   signup form and the admin "new user" sheet to keep one visual identity. */

import { useRef } from "react";
import { Icon } from "./Icon";

export function FileField({
  label, accept, file, onPick,
}: { label: string; accept: string; file: File | null; onPick: (f: File | null) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--foreground)", marginBottom: 6 }}>{label}</div>
      <input
        ref={ref}
        type="file"
        accept={accept}
        style={{ display: "none" }}
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
      />
      <button
        type="button"
        onClick={() => ref.current?.click()}
        style={{
          width: "100%", textAlign: "left", cursor: "pointer",
          background: "var(--input, var(--card))", border: "1px solid var(--border)",
          borderRadius: "var(--radius-md)", padding: "9px 12px", fontSize: 13,
          color: file ? "var(--foreground)" : "var(--muted-foreground)",
          display: "flex", alignItems: "center", gap: 8,
        }}
      >
        <Icon name="ATTACH" size={14} color="var(--muted-foreground)" />
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {file ? file.name : "Seleccionar archivo…"}
        </span>
        {file && (
          <span
            onClick={(e) => { e.stopPropagation(); onPick(null); if (ref.current) ref.current.value = ""; }}
            style={{ color: "var(--muted-foreground)", fontSize: 14, padding: "0 2px" }}
            title="Quitar"
          >
            ✕
          </span>
        )}
      </button>
    </div>
  );
}
