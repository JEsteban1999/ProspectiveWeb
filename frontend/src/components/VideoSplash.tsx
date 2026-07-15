/* VideoSplash — intro clip shown once on app load, then fades out.
   Port of the desktop VideoSplashDialog: plays for up to MAX_MS, skippable by
   click/key, fades out at the end. Muted so autoplay is allowed by browsers. */

import { useEffect, useRef, useState } from "react";

const MAX_MS = 4500;
const FADE_MS = 500;
const VIDEO_SRC = "/media/intro.mp4";

export function VideoSplash({ onDone }: { onDone: () => void }) {
  const [fading, setFading] = useState(false);
  const doneRef = useRef(false);

  const finish = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    setFading(true);
    window.setTimeout(onDone, FADE_MS);
  };

  useEffect(() => {
    const t = window.setTimeout(finish, MAX_MS);
    const onKey = () => finish();
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      onClick={finish}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "#000",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "pointer",
        opacity: fading ? 0 : 1,
        transition: `opacity ${FADE_MS}ms ease`,
      }}
    >
      <video
        src={VIDEO_SRC}
        autoPlay
        muted
        playsInline
        onEnded={finish}
        onError={finish}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
      {/* Brand overlay */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 10,
          pointerEvents: "none",
          background: "radial-gradient(60% 60% at 50% 50%, transparent, rgba(0,0,0,0.55))",
        }}
      >
        <span style={{ color: "#fff", fontWeight: 800, fontSize: 34, letterSpacing: "-0.02em", textShadow: "0 2px 20px rgba(0,0,0,0.6)" }}>
          PROSPECTIVE
        </span>
        <span style={{ color: "rgba(168,184,198,0.9)", fontSize: 13, letterSpacing: "0.18em", textTransform: "uppercase" }}>
          Hybrid Neurovascular Planning · UNINAVARRA
        </span>
      </div>
      <span style={{ position: "absolute", bottom: 22, right: 26, color: "rgba(235,235,235,0.6)", fontSize: 11, fontFamily: "var(--font-mono)", pointerEvents: "none" }}>
        clic para saltar
      </span>
    </div>
  );
}
