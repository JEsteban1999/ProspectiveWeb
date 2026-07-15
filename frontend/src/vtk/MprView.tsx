/* MprView — one orthogonal DICOM plane rendered from backend PNG slices.
   Wheel scrolls slices; optional slider. Window/level comes from volume meta
   (overridable). Mirrors the desktop SliceWidget behaviour. */

import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { VolumeMeta } from "../api/types";

const PLANE_LABEL: Record<string, string> = {
  axial: "Axial",
  coronal: "Coronal",
  sagital: "Sagital",
};

function planeCount(meta: VolumeMeta, plane: string): number {
  const [z, y, x] = meta.shape;
  return plane === "axial" ? z : plane === "coronal" ? y : x;
}

export function MprView({
  sessionId,
  meta,
  plane,
  wc,
  ww,
  showSlider = false,
  compact = false,
}: {
  sessionId: string;
  meta: VolumeMeta;
  plane: "axial" | "coronal" | "sagital";
  wc?: number;
  ww?: number;
  showSlider?: boolean;
  compact?: boolean;
}) {
  const count = planeCount(meta, plane);
  const [index, setIndex] = useState(Math.floor(count / 2));
  const ref = useRef<HTMLDivElement>(null);

  // Reset to mid-slice if the volume changes.
  useEffect(() => {
    setIndex(Math.floor(count / 2));
  }, [count, sessionId]);

  const wcv = wc ?? meta.wc;
  const wwv = ww ?? meta.ww;
  const src = api.sliceUrl(sessionId, plane, index, wcv, wwv);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setIndex((i) => Math.max(0, Math.min(count - 1, i + (e.deltaY > 0 ? 1 : -1))));
  };

  return (
    <div
      ref={ref}
      onWheel={onWheel}
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        background: "var(--viewer-bg)",
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <img
        src={src}
        alt={`${plane} ${index}`}
        draggable={false}
        style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", userSelect: "none", imageRendering: "auto" }}
      />

      <span style={{ position: "absolute", top: 8, left: 10, fontSize: compact ? 10 : 11, fontFamily: "var(--font-mono)", color: "rgba(168,184,198,0.85)", pointerEvents: "none", display: "flex", alignItems: "center", gap: 6 }}>
        {PLANE_LABEL[plane]}
      </span>
      <span style={{ position: "absolute", bottom: 8, left: 10, fontSize: compact ? 9 : 10, fontFamily: "var(--font-mono)", color: "rgba(168,184,198,0.7)", pointerEvents: "none" }}>
        {index + 1} / {count}
      </span>
      <span style={{ position: "absolute", bottom: 8, right: 10, fontSize: compact ? 9 : 10, fontFamily: "var(--font-mono)", color: "rgba(168,184,198,0.55)", pointerEvents: "none" }}>
        W {Math.round(wwv)} · L {Math.round(wcv)}
      </span>

      {showSlider && (
        <input
          type="range"
          min={0}
          max={count - 1}
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
          style={{
            position: "absolute",
            bottom: 26,
            left: "50%",
            transform: "translateX(-50%)",
            width: "70%",
            accentColor: "var(--brand-mist)",
          }}
        />
      )}
    </div>
  );
}
