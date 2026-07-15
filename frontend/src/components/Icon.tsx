/* PROSPECTIVE iconography — monochrome Unicode BMP glyphs.
   Ported verbatim from prospective/ui/icons.py (_Icons class).
   VS-15 (U+FE0E) forces text (monochrome) presentation; the font stack puts
   "Segoe UI Symbol" first so glyphs always render in currentColor. */

import type { CSSProperties } from "react";

const T = "︎"; // Variation Selector-15: force text/monochrome rendering

export const GLYPHS = {
  // Workflow steps
  STEP_PATIENT: "◻",
  STEP_SEGMENT: "⊕",
  STEP_DETECT: "◎",
  STEP_MORPHO: "∑",
  STEP_PLAN: "✛",
  STEP_EXPORT: "⊟",
  // Navigation & global actions
  HOME: "⌂",
  EDIT: "✏" + T,
  FOLDER: "⊡",
  DOC: "≡",
  SAVE: "⊞",
  PRINT: "⊡",
  ATTACH: "⊕",
  LINK: "⊕",
  REFRESH: "↻",
  LOCK: "⊟",
  SEARCH: "◎",
  AUDIT: "⊟",
  USER: "◻",
  USERS: "≡",
  // 3-D planning sidebar
  CLIPS: "✂" + T,
  FLOW_DIV: "⊛",
  STENT: "⚕" + T,
  STENT_CL: "⚕" + T,
  TRAJECTORY: "⌖",
  CENTERLINE: "∿",
  MEASURE: "↔",
  CUT: "✂" + T,
  SETTINGS: "⚙" + T,
  // Medical / intra-procedure
  CLIP_PLACE: "↓",
  SEED: "⊙",
  GROWTH: "↑",
  COIL: "⊕",
  BRAIN: "✺",
  MARK_PERF: "✦",
  ANNOTATION: "⊞",
  ANGLE_MEAS: "∠",
  MEDICAL_SIGN: "⚕" + T,
  // Visibility / MPR
  EYE: "◉",
  EYE_HIDDEN: "◌",
  MPR_VIEW: "⊞",
  OBLIQUE: "◇",
  // Theme
  THEME_LIGHT: "◐",
  THEME_DARK: "◑",
  // Status
  STATUS_OK: "✓" + T,
  STATUS_WARN: "⚠" + T,
  STATUS_FAIL: "✗" + T,
  WAIT: "↻",
  HINT: "⊕",
  // Contact / web / meta (BMP monochrome glyphs, VS-15 where needed)
  MAIL: "✉" + T,
  PHONE: "☎" + T,
  GLOBE: "◍",
  PIN: "⌖",
  INFO: "ⓘ",
  BOOK: "▤",
  CHART: "▦",
  CLOUD: "☁" + T,
  SPARKLE: "✧",
  VRAR: "◈",
  SHIELD: "⊚",
  DATABASE: "⊟",
  ARROW_RIGHT: "→",
  ARROW_UP_RIGHT: "↗",
  RULER: "↔",
  TARGET: "◎",
} as const;

export type IconName = keyof typeof GLYPHS;

const ICON_FONT =
  "'Segoe UI Symbol', 'Segoe UI', 'Arial Unicode MS', 'DejaVu Sans', sans-serif";

export interface IconProps {
  name: IconName;
  size?: number;
  color?: string;
  style?: CSSProperties;
}

export function Icon({ name, size = 16, color, style }: IconProps) {
  return (
    <span
      aria-hidden
      style={{
        fontFamily: ICON_FONT,
        fontSize: size,
        lineHeight: 1,
        color: color ?? "currentColor",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        userSelect: "none",
        ...style,
      }}
    >
      {GLYPHS[name]}
    </span>
  );
}
