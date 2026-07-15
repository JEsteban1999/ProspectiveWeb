/* Separator — 1px rule. */

import type { CSSProperties } from "react";

export function Separator({ style }: { style?: CSSProperties }) {
  return <div style={{ height: 1, background: "var(--border)", ...style }} />;
}
