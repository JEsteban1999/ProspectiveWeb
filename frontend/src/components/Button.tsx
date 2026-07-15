/* Button — 6 variants (default, outline, secondary, ghost, destructive, link),
   sizes sm/md/lg/icon. Hover darkens ~10%; press fills steel/primary. */

import { useState } from "react";
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";

type Variant = "default" | "outline" | "secondary" | "ghost" | "destructive" | "link";
type Size = "sm" | "md" | "lg" | "icon";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
}

const HEIGHTS: Record<Size, string> = {
  sm: "var(--control-sm)",
  md: "var(--control-md)",
  lg: "var(--control-lg)",
  icon: "var(--control-md)",
};

function variantStyle(v: Variant, hover: boolean, disabled: boolean): CSSProperties {
  const base: CSSProperties = { border: "1px solid transparent" };
  switch (v) {
    case "default":
      return {
        ...base,
        background: hover && !disabled ? "var(--primary-hover)" : "var(--primary)",
        color: "var(--primary-foreground)",
      };
    case "outline":
      return {
        ...base,
        background: hover && !disabled ? "var(--accent)" : "transparent",
        color: hover && !disabled ? "var(--accent-foreground)" : "var(--foreground)",
        border: "1px solid var(--border)",
      };
    case "secondary":
      return {
        ...base,
        background: hover && !disabled ? "var(--accent)" : "var(--secondary)",
        color: "var(--secondary-foreground)",
      };
    case "ghost":
      return {
        ...base,
        background: hover && !disabled ? "var(--accent)" : "transparent",
        color: hover && !disabled ? "var(--accent-foreground)" : "var(--foreground)",
      };
    case "destructive":
      return {
        ...base,
        background: "var(--destructive)",
        color: "var(--destructive-foreground)",
        filter: hover && !disabled ? "brightness(0.9)" : undefined,
      };
    case "link":
      return {
        ...base,
        background: "transparent",
        color: "var(--brand-deep)",
        textDecoration: hover ? "underline" : "none",
        height: "auto",
        padding: 0,
      };
  }
}

export function Button({
  variant = "default",
  size = "md",
  leadingIcon,
  trailingIcon,
  children,
  style,
  disabled,
  ...rest
}: ButtonProps) {
  const [hover, setHover] = useState(false);
  return (
    <button
      {...rest}
      disabled={disabled}
      onMouseEnter={(e) => { setHover(true); rest.onMouseEnter?.(e); }}
      onMouseLeave={(e) => { setHover(false); rest.onMouseLeave?.(e); }}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        height: HEIGHTS[size],
        padding: size === "icon" ? 0 : size === "sm" ? "0 12px" : size === "lg" ? "0 22px" : "0 16px",
        width: size === "icon" ? HEIGHTS[size] : undefined,
        borderRadius: "var(--radius-md)",
        fontFamily: "var(--font-sans)",
        fontSize: size === "sm" ? 13 : 14,
        fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
        transition: "background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), filter var(--dur-fast) var(--ease-out)",
        ...variantStyle(variant, hover, !!disabled),
        ...style,
      }}
    >
      {leadingIcon}
      {children}
      {trailingIcon}
    </button>
  );
}
