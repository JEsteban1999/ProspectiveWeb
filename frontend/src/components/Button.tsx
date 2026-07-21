/* Button — 6 variants (default, outline, secondary, ghost, destructive, link),
   sizes sm/md/lg/icon. Hover darkens ~10%; press fills steel/primary.

   Los botones primarios llevan un halo animado (border-beam). Como el efecto
   envuelve el botón en un contenedor, las propiedades de layout que pase el
   llamador (flex, width, márgenes…) se trasladan al wrapper y el botón se
   estira dentro — si no, un `style={{ flex: 1 }}` dejaría de funcionar. */

import { useState } from "react";
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import { BorderBeam } from "border-beam";
import { useThemeContext } from "../store/theme";

type Variant = "default" | "outline" | "secondary" | "ghost" | "destructive" | "link";
type Size = "sm" | "md" | "lg" | "icon";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
  /** Halo animado. Por defecto solo en el botón primario ("default"). */
  beam?: boolean;
}

/* Propiedades que colocan el botón dentro de su contenedor: van al wrapper. */
const LAYOUT_KEYS = [
  "flex", "flexGrow", "flexShrink", "flexBasis", "width", "minWidth", "maxWidth",
  "alignSelf", "justifySelf", "gridColumn", "gridRow", "order",
  "margin", "marginTop", "marginRight", "marginBottom", "marginLeft", "position", "zIndex",
] as const;

function splitLayout(style?: CSSProperties): { outer: CSSProperties; inner: CSSProperties } {
  const outer: CSSProperties = {};
  const inner: CSSProperties = { ...style };
  for (const k of LAYOUT_KEYS) {
    if (inner[k] !== undefined) {
      (outer as Record<string, unknown>)[k] = inner[k];
      delete inner[k];
    }
  }
  return { outer, inner };
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
  beam,
  ...rest
}: ButtonProps) {
  const [hover, setHover] = useState(false);
  const { theme } = useThemeContext();

  // Halo solo en el botón primario y cuando está habilitado (un botón
  // deshabilitado brillando invita a pulsarlo).
  const withBeam = (beam ?? variant === "default") && !disabled;
  const { outer, inner } = withBeam ? splitLayout(style) : { outer: {}, inner: style ?? {} };

  const btn = (
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
        width: size === "icon" ? HEIGHTS[size] : withBeam ? "100%" : undefined,
        borderRadius: "var(--radius-md)",
        fontFamily: "var(--font-sans)",
        fontSize: size === "sm" ? 13 : 14,
        fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
        transition: "background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), filter var(--dur-fast) var(--ease-out)",
        ...variantStyle(variant, hover, !!disabled),
        ...inner,
      }}
    >
      {leadingIcon}
      {children}
      {trailingIcon}
    </button>
  );

  if (!withBeam) return btn;

  return (
    <BorderBeam
      size="sm"
      colorVariant="ocean"
      theme={theme}
      style={{ display: "inline-flex", ...outer }}
    >
      {btn}
    </BorderBeam>
  );
}
