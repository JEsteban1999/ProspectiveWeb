/* Input — labelled text field with optional leading icon, hint and invalid state. */

import { useId, useState } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  icon?: ReactNode;
  hint?: string;
  invalid?: boolean;
}

export function Input({ label, icon, hint, invalid, style, ...rest }: InputProps) {
  const id = useId();
  const [focus, setFocus] = useState(false);
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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          height: "var(--control-md)",
          padding: "0 12px",
          borderRadius: "var(--radius-md)",
          background: "var(--background)",
          border: `1px solid ${invalid ? "var(--destructive)" : "var(--input)"}`,
          boxShadow: focus
            ? "0 0 0 3px color-mix(in srgb, var(--ring) 50%, transparent)"
            : "var(--shadow-xs)",
          transition: "box-shadow var(--dur-fast) var(--ease-out)",
        }}
      >
        {icon && <span style={{ color: "var(--muted-foreground)", display: "flex" }}>{icon}</span>}
        <input
          id={id}
          {...rest}
          onFocus={(e) => { setFocus(true); rest.onFocus?.(e); }}
          onBlur={(e) => { setFocus(false); rest.onBlur?.(e); }}
          style={{
            flex: 1,
            minWidth: 0,
            border: "none",
            outline: "none",
            background: "transparent",
            color: "var(--foreground)",
            fontFamily: "var(--font-sans)",
            fontSize: 14,
            ...style,
          }}
        />
      </div>
      {hint && <span style={{ fontSize: 12, color: invalid ? "var(--destructive)" : "var(--muted-foreground)" }}>{hint}</span>}
    </div>
  );
}
