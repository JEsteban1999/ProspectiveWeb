/* Select — styled native combobox with the small uppercase label. */

import { useId } from "react";
import type { SelectHTMLAttributes } from "react";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: readonly string[] | { value: string; label: string }[];
}

export function Select({ label, options, style, ...rest }: SelectProps) {
  const id = useId();
  const opts = options.map((o) =>
    typeof o === "string" ? { value: o, label: o } : o
  );
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
      {label && (
        <label
          htmlFor={id}
          style={{ fontSize: "var(--text-label)", fontWeight: 600, letterSpacing: "var(--tracking-label)", textTransform: "uppercase", color: "var(--muted-foreground)" }}
        >
          {label}
        </label>
      )}
      <select
        id={id}
        {...rest}
        style={{
          height: "var(--control-md)",
          padding: "0 10px",
          borderRadius: "var(--radius-md)",
          background: "var(--background)",
          border: "1px solid var(--input)",
          boxShadow: "var(--shadow-xs)",
          color: "var(--foreground)",
          fontFamily: "var(--font-sans)",
          fontSize: 13,
          cursor: "pointer",
          ...style,
        }}
      >
        {opts.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
