/* PROSPECTIVE — pipeline explainer (Remotion).
   Rendered to /media/pipeline.mp4 and embedded in the landing page.

   Structure: concise intro presenting what PROSPECTIVE is, then each of the 7
   pipeline steps sequentially, then an outro.

   Transitions: each scene fades fully OUT before the next fades IN (fade
   through the persistent background) so two texts are never visible at once —
   no ghosting/overlap. Built per the remotion-best-practices skill:
   interpolate() + Easing.bezier (no spring), inline styles with individual
   transform props, no CSS transitions. */

import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  useCurrentFrame,
} from "remotion";

export const FPS = 30;

// Design-system ease-out (cubic-bezier(0.16, 1, 0.3, 1))
const EASE = Easing.bezier(0.16, 1, 0.3, 1);

const FONT = "'Inter', 'Segoe UI', Arial, sans-serif";
const MONO = "'JetBrains Mono', 'Consolas', monospace";

const C = {
  bg0: "#060b12",
  bg1: "#0c1622",
  white: "#ffffff",
  mist: "#A8B8C6",
  slate: "#6A8399",
  muted: "rgba(168,184,198,0.78)",
};

interface Step {
  n: string;
  title: string;
  desc: string;
  metric: string;
}

const STEPS: Step[] = [
  { n: "01", title: "Carga DICOM", desc: "Sube el estudio del paciente", metric: "CTA · MRA · 3DRA" },
  { n: "02", title: "Segmentación vascular 3D", desc: "Marching Cubes sobre VTK", metric: "≈ 285 000 vértices" },
  { n: "03", title: "Detección de aneurismas", desc: "Curvatura gaussiana v6", metric: "candidatos + domo aislado" },
  { n: "04", title: "Morfometría", desc: "Medidas e índices clínicos", metric: "Ø 6.2 mm · cuello 2.9 · AR 1.42" },
  { n: "05", title: "Decisión terapéutica", desc: "Motor de 8 factores", metric: "CLIP 72%  ·  ENDO 28%" },
  { n: "06", title: "Planificación de dispositivos", desc: "Catálogos reales", metric: "42 clips · 39 coils · stents" },
  { n: "07", title: "Informe y export", desc: "Documenta y comparte", metric: "PDF · STL · seguimiento" },
];

// ── Timing (scenes are back-to-back; no overlap → no text ghosting) ─────── #
const TITLE_D = 78;
const HOOK_D = 58;
const STEP_D = 70;
const OUTRO_D = 76;
const FADE = 14; // in + out per scene

// Cumulative layout
const OFFSETS: number[] = [];
{
  let acc = 0;
  const durs = [TITLE_D, HOOK_D, ...STEPS.map(() => STEP_D), OUTRO_D];
  for (const d of durs) {
    OFFSETS.push(acc);
    acc += d;
  }
}
export const PIPELINE_DURATION = TITLE_D + HOOK_D + STEPS.length * STEP_D + OUTRO_D;

// ── Shared pieces ───────────────────────────────────────────────────────── #

function Backdrop() {
  const frame = useCurrentFrame();
  const shift = interpolate(frame, [0, PIPELINE_DURATION], [0, 44]);
  return (
    <AbsoluteFill style={{ background: `radial-gradient(90% 70% at 30% 15%, ${C.bg1}, ${C.bg0} 70%)` }}>
      <AbsoluteFill
        style={{
          backgroundImage:
            "linear-gradient(rgba(139,155,170,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(139,155,170,0.05) 1px, transparent 1px)",
          backgroundSize: "52px 52px",
          backgroundPosition: `${shift}px ${shift}px`,
          maskImage: "radial-gradient(80% 80% at 50% 45%, #000, transparent)",
          WebkitMaskImage: "radial-gradient(80% 80% at 50% 45%, #000, transparent)",
        }}
      />
    </AbsoluteFill>
  );
}

function Wordmark() {
  return (
    <div style={{ position: "absolute", top: 48, left: 64, display: "flex", alignItems: "center", gap: 14, zIndex: 10 }}>
      <div style={{ width: 28, height: 28, borderRadius: 8, background: C.mist }} />
      <span style={{ color: C.white, fontFamily: FONT, fontWeight: 800, fontSize: 26, letterSpacing: "-0.02em" }}>PROSPECTIVE</span>
    </div>
  );
}

/** Scene envelope: fade IN over the first FADE frames, hold, fade OUT over the
    last FADE frames. Because scenes are back-to-back, the outgoing scene is at
    opacity 0 before the incoming one appears — no two texts overlap. */
function SceneShell({ dur, children }: { dur: number; children: React.ReactNode }) {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, FADE, dur - FADE, dur], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE,
  });
  return (
    <AbsoluteFill style={{ opacity, alignItems: "center", justifyContent: "center", padding: "0 120px" }}>
      {children}
    </AbsoluteFill>
  );
}

/** Per-element entrance: small upward rise driven by the local frame. */
function rise(frame: number, delay: number, dur = 18) {
  return interpolate(frame, [delay, delay + dur], [26, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE,
  });
}

// ── Scenes ──────────────────────────────────────────────────────────────── #

function TitleScene() {
  const f = useCurrentFrame();
  return (
    <SceneShell dur={TITLE_D}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 26, textAlign: "center" }}>
        <div style={{ translate: `0px ${rise(f, 4)}px`, fontFamily: FONT, fontWeight: 800, fontSize: 104, letterSpacing: "-0.03em", color: C.white, lineHeight: 1 }}>
          PROSPECTIVE
        </div>
        <div style={{ translate: `0px ${rise(f, 16)}px`, fontFamily: FONT, fontSize: 40, color: C.muted, maxWidth: 900, lineHeight: 1.35 }}>
          Planificación quirúrgica de aneurismas cerebrales — objetiva y medible.
        </div>
      </div>
    </SceneShell>
  );
}

function HookScene() {
  const f = useCurrentFrame();
  return (
    <SceneShell dur={HOOK_D}>
      <div style={{ translate: `0px ${rise(f, 4)}px`, textAlign: "center" }}>
        <div style={{ fontFamily: MONO, fontSize: 30, color: C.slate, letterSpacing: "0.28em", marginBottom: 22 }}>EL PIPELINE</div>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 72, letterSpacing: "-0.02em", color: C.white, lineHeight: 1.1, maxWidth: 1000 }}>
          Del DICOM al plan quirúrgico<br />en 7 pasos
        </div>
      </div>
    </SceneShell>
  );
}

function Stepper({ active }: { active: number }) {
  return (
    <div style={{ position: "absolute", bottom: 60, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 16 }}>
      {STEPS.map((_, i) => (
        <div
          key={i}
          style={{
            width: i === active ? 44 : 11,
            height: 11,
            borderRadius: 6,
            background: i === active ? C.mist : i < active ? C.slate : "rgba(139,155,170,0.25)",
          }}
        />
      ))}
    </div>
  );
}

function StepScene({ step, index }: { step: Step; index: number }) {
  const f = useCurrentFrame();
  return (
    <SceneShell dur={STEP_D}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 20, textAlign: "center", maxWidth: 1040 }}>
        <div style={{ translate: `0px ${rise(f, 2, 14)}px`, fontFamily: MONO, fontSize: 30, color: C.slate, letterSpacing: "0.3em" }}>
          PASO {step.n} / 07
        </div>
        <div style={{ translate: `0px ${rise(f, 7)}px`, fontFamily: FONT, fontWeight: 800, fontSize: 74, letterSpacing: "-0.02em", color: C.white, lineHeight: 1.06 }}>
          {step.title}
        </div>
        <div style={{ translate: `0px ${rise(f, 12)}px`, fontFamily: FONT, fontSize: 38, color: C.muted }}>
          {step.desc}
        </div>
        <div
          style={{
            translate: `0px ${rise(f, 17)}px`,
            marginTop: 12,
            padding: "14px 30px",
            borderRadius: 14,
            background: "rgba(139,155,170,0.12)",
            border: "1px solid rgba(139,155,170,0.28)",
            fontFamily: MONO,
            fontSize: 32,
            color: C.mist,
          }}
        >
          {step.metric}
        </div>
      </div>
      <Stepper active={index} />
    </SceneShell>
  );
}

function OutroScene() {
  const f = useCurrentFrame();
  return (
    <SceneShell dur={OUTRO_D}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22, textAlign: "center" }}>
        <div style={{ translate: `0px ${rise(f, 4)}px`, fontFamily: FONT, fontWeight: 800, fontSize: 64, letterSpacing: "-0.02em", color: C.white, lineHeight: 1.1, maxWidth: 1000 }}>
          Planificación neurovascular, medible.
        </div>
        <div style={{ translate: `0px ${rise(f, 16)}px`, fontFamily: MONO, fontSize: 28, color: C.slate }}>
          UniNavarra · Laboratorio de Imagen Médica
        </div>
      </div>
    </SceneShell>
  );
}

// ── Root composition ────────────────────────────────────────────────────── #

export const Pipeline: React.FC = () => {
  const durs = [TITLE_D, HOOK_D, ...STEPS.map(() => STEP_D), OUTRO_D];
  const nodes = [
    <TitleScene key="title" />,
    <HookScene key="hook" />,
    ...STEPS.map((step, i) => <StepScene key={step.n} step={step} index={i} />),
    <OutroScene key="outro" />,
  ];
  return (
    <AbsoluteFill style={{ background: C.bg0 }}>
      <Backdrop />
      <Wordmark />
      {nodes.map((node, i) => (
        <Sequence key={i} from={OFFSETS[i]} durationInFrames={durs[i]}>
          {node}
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
