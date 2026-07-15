/* LoadingScreen — brief branded transition shown right after a successful login,
   while the patient workspace loads. Plays the surgical loading clip (looped,
   muted) behind a progress indicator, then fades out.

   Uses the second desktop video (Multimedia1.mov → loading.mp4), which in the
   desktop app played during login. */

import { useEffect, useState } from "react";
import logo from "../assets/logo.png";

const SHOW_MS = 2200;
const FADE_MS = 450;
const VIDEO_SRC = "/media/loading.mp4";

export function LoadingScreen({ onDone, label = "Preparando el espacio de trabajo…" }: { onDone: () => void; label?: string }) {
  const [fading, setFading] = useState(false);

  useEffect(() => {
    const t1 = window.setTimeout(() => setFading(true), SHOW_MS);
    const t2 = window.setTimeout(onDone, SHOW_MS + FADE_MS);
    return () => { window.clearTimeout(t1); window.clearTimeout(t2); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 900,
        background: "#05090f",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        opacity: fading ? 0 : 1,
        transition: `opacity ${FADE_MS}ms ease`,
      }}
    >
      <video
        src={VIDEO_SRC}
        autoPlay
        muted
        loop
        playsInline
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", opacity: 0.45 }}
      />
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(120% 100% at 50% 40%, rgba(10,18,28,0.55), rgba(5,9,15,0.9))" }} />

      <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <img src={logo} alt="" style={{ height: 34, filter: "invert(1) brightness(1.7)" }} />
          <span style={{ color: "#fff", fontWeight: 800, fontSize: 26, letterSpacing: "-0.02em", textShadow: "0 2px 18px rgba(0,0,0,0.5)" }}>
            PROSPECTIVE
          </span>
        </div>

        {/* Indeterminate progress bar */}
        <div style={{ position: "relative", width: 220, height: 4, borderRadius: 2, background: "rgba(139,155,170,0.25)", overflow: "hidden" }}>
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              width: "35%",
              borderRadius: 2,
              background: "linear-gradient(90deg, transparent, #A8B8C6, transparent)",
              animation: "progress-sweep 1.1s ease-in-out infinite",
            }}
          />
        </div>

        <span style={{ color: "rgba(168,184,198,0.9)", fontSize: 13, letterSpacing: "0.04em" }}>{label}</span>
      </div>
    </div>
  );
}
