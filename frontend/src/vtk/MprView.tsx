/* MprView — one orthogonal DICOM plane rendered from backend PNG slices.

   - Wheel scrolls slices (uncontrolled) or reports via onIndexChange (controlled).
   - Left-drag adjusts window/level (→ onWindowLevel), mirroring the desktop
     SliceWidget. Shift/click reports the in-plane position for crosshair sync.
   - An optional crosshair {u,v} (fractional 0–1) is drawn over the image. */

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
  index: controlledIndex,
  onIndexChange,
  crosshair = null,
  onPlaneClick,
  onWindowLevel,
  band = null,
}: {
  sessionId: string;
  meta: VolumeMeta;
  plane: "axial" | "coronal" | "sagital";
  wc?: number;
  ww?: number;
  showSlider?: boolean;
  compact?: boolean;
  /** Threshold-preview band [lower, upper] HU — tints captured voxels live. */
  band?: [number, number] | null;
  /** Controlled slice index. If omitted, the view manages its own. */
  index?: number;
  onIndexChange?: (i: number) => void;
  /** Crosshair position in fractional image coords (0–1), or null. */
  crosshair?: { u: number; v: number } | null;
  /** Reports a click's fractional in-plane position (0–1). */
  onPlaneClick?: (u: number, v: number) => void;
  /** Reports a window/level change from a left-drag. */
  onWindowLevel?: (wc: number, ww: number) => void;
}) {
  const count = planeCount(meta, plane);
  const controlled = controlledIndex !== undefined;
  const [selfIndex, setSelfIndex] = useState(Math.floor(count / 2));
  const index = controlled ? controlledIndex! : selfIndex;
  const setIndex = (i: number) => {
    const c = Math.max(0, Math.min(count - 1, i));
    if (controlled) onIndexChange?.(c);
    else setSelfIndex(c);
  };

  const [loadIndex, setLoadIndex] = useState(index);
  const imgRef = useRef<HTMLImageElement>(null);
  const drag = useRef<{ x: number; y: number; wc: number; ww: number } | null>(null);
  const moved = useRef(false);

  useEffect(() => {
    if (!controlled) setSelfIndex(Math.floor(count / 2));
  }, [count, sessionId, controlled]);

  useEffect(() => {
    const t = setTimeout(() => setLoadIndex(index), 90);
    return () => clearTimeout(t);
  }, [index]);

  const wcv = wc ?? meta.wc;
  const wwv = ww ?? meta.ww;
  const safeLoadIndex = Math.max(0, Math.min(count - 1, loadIndex));
  const src = api.sliceUrl(sessionId, plane, safeLoadIndex, wcv, wwv, band);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setIndex(index + (e.deltaY > 0 ? 1 : -1));
  };

  // Fractional position of the pointer within the actual (letterboxed) image.
  const fracFromEvent = (e: React.MouseEvent): { u: number; v: number } | null => {
    const img = imgRef.current;
    if (!img) return null;
    const r = img.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return null;
    const u = (e.clientX - r.left) / r.width;
    const v = (e.clientY - r.top) / r.height;
    if (u < 0 || u > 1 || v < 0 || v > 1) return null;
    return { u, v };
  };

  const onMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    drag.current = { x: e.clientX, y: e.clientY, wc: wcv, ww: wwv };
    moved.current = false;
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!drag.current || !onWindowLevel) return;
    const dx = e.clientX - drag.current.x;
    const dy = e.clientY - drag.current.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) moved.current = true;
    // Horizontal → window width; vertical → window center (level).
    const nWw = Math.max(1, drag.current.ww + dx * 4);
    const nWc = drag.current.wc - dy * 4;
    onWindowLevel(nWc, nWw);
  };
  const endDrag = (e: React.MouseEvent) => {
    const wasDrag = moved.current;
    drag.current = null;
    if (!wasDrag && onPlaneClick) {
      const f = fracFromEvent(e);
      if (f) onPlaneClick(f.u, f.v);
    }
  };

  return (
    <div
      onWheel={onWheel}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={endDrag}
      onMouseLeave={() => { drag.current = null; }}
      style={{
        position: "relative", width: "100%", height: "100%",
        background: "var(--viewer-bg)", overflow: "hidden",
        display: "flex", alignItems: "center", justifyContent: "center",
        cursor: onWindowLevel ? "crosshair" : "default",
      }}
    >
      <img
        ref={imgRef}
        src={src}
        alt={`${plane} ${index}`}
        draggable={false}
        style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", userSelect: "none" }}
      />

      {/* Crosshair overlay (drawn relative to the image box) */}
      {crosshair && (
        <CrosshairOverlay imgRef={imgRef} u={crosshair.u} v={crosshair.v} />
      )}

      <span style={{ position: "absolute", top: 8, left: 10, fontSize: compact ? 10 : 11, fontFamily: "var(--font-mono)", color: "rgba(168,184,198,0.85)", pointerEvents: "none" }}>
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
          type="range" min={0} max={count - 1} value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
          style={{ position: "absolute", bottom: 26, left: "50%", transform: "translateX(-50%)", width: "70%", accentColor: "var(--brand-mist)" }}
        />
      )}
    </div>
  );
}

/* Crosshair lines positioned over the letterboxed image. Recomputes on layout. */
function CrosshairOverlay({ imgRef, u, v }: { imgRef: React.RefObject<HTMLImageElement | null>; u: number; v: number }) {
  const [box, setBox] = useState<{ left: number; top: number; w: number; h: number } | null>(null);
  useEffect(() => {
    const img = imgRef.current;
    const parent = img?.parentElement;
    if (!img || !parent) return;
    const update = () => {
      const ir = img.getBoundingClientRect();
      const pr = parent.getBoundingClientRect();
      setBox({ left: ir.left - pr.left, top: ir.top - pr.top, w: ir.width, h: ir.height });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(img);
    ro.observe(parent);
    return () => ro.disconnect();
  }, [imgRef, u, v]);
  if (!box) return null;
  const cx = box.left + u * box.w;
  const cy = box.top + v * box.h;
  const color = "rgba(96,180,220,0.7)";
  return (
    <>
      <div style={{ position: "absolute", left: cx, top: box.top, width: 1, height: box.h, background: color, pointerEvents: "none" }} />
      <div style={{ position: "absolute", top: cy, left: box.left, height: 1, width: box.w, background: color, pointerEvents: "none" }} />
    </>
  );
}
