/* Landing — public marketing/onboarding page for PROSPECTIVE.
   One long scroll: hero → what/why → pipeline video → features → use cases →
   how it works → technology → security → team → disclaimer → CTA.
   "Entrar" routes to the app (/app). Uses the design system, light + dark. */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import logo from "../assets/logo.png";
import { Icon } from "../components/Icon";
import type { IconName } from "../components/Icon";
import { ThemeToggle } from "../components/ThemeToggle";

const MAXW = 1320;

function Section({ id, children, style }: { id?: string; children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <section id={id} style={{ padding: "88px 24px", ...style }}>
      <div style={{ maxWidth: MAXW, margin: "0 auto" }}>{children}</div>
    </section>
  );
}

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--brand-slate)", marginBottom: 14 }}>
      {children}
    </div>
  );
}

function H2({ children }: { children: React.ReactNode }) {
  return (
    <h2 style={{ fontSize: "clamp(26px, 3.4vw, 38px)", fontWeight: 800, letterSpacing: "-0.02em", color: "var(--foreground)", lineHeight: 1.12, margin: 0 }}>
      {children}
    </h2>
  );
}

/* ── Sticky nav ─────────────────────────────────────────────────────────── */
function Nav({ onEnter }: { onEnter: () => void }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  const links = [
    ["Qué es", "que-es"],
    ["Pipeline", "pipeline"],
    ["Funcionalidades", "funcionalidades"],
    ["Índices", "indices"],
    ["Tecnología", "tecnologia"],
    ["Contacto", "contacto"],
  ] as const;
  return (
    <div
      style={{
        position: "sticky",
        top: 0,
        zIndex: 100,
        height: 76,
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "0 24px",
        background: scrolled ? "color-mix(in srgb, var(--background) 88%, transparent)" : "transparent",
        backdropFilter: scrolled ? "blur(10px)" : "none",
        borderBottom: scrolled ? "1px solid var(--border)" : "1px solid transparent",
        transition: "background .2s, border-color .2s",
      }}
    >
      <div style={{ maxWidth: MAXW, margin: "0 auto", width: "100%", display: "flex", alignItems: "center", gap: 14 }}>
        <img className="logo-mark" src={logo} alt="" style={{ height: 48 }} />
        <span style={{ fontWeight: 800, fontSize: 21, letterSpacing: "-0.02em", color: "var(--foreground)" }}>PROSPECTIVE</span>
        <div style={{ flex: 1 }} />
        <nav style={{ display: "flex", gap: 20, marginRight: 8 }}>
          {links.map(([label, id]) => (
            <a key={id} href={`#${id}`} style={{ fontSize: 13.5, fontWeight: 600, color: "var(--muted-foreground)", textDecoration: "none" }}>
              {label}
            </a>
          ))}
        </nav>
        <ThemeToggle size="sm" />
        <button
          onClick={onEnter}
          style={{ height: 38, padding: "0 18px", borderRadius: "var(--radius-md)", border: "none", background: "var(--primary)", color: "var(--primary-foreground)", fontWeight: 700, fontSize: 13.5, cursor: "pointer" }}
        >
          Entrar
        </button>
      </div>
    </div>
  );
}

/* ── Hero ───────────────────────────────────────────────────────────────── */
function Hero({ onEnter }: { onEnter: () => void }) {
  return (
    <div style={{ position: "relative", overflow: "hidden", minHeight: "calc(100vh - 64px)", display: "flex", alignItems: "center", background: "#05090f" }}>
      <video
        src="/media/intro.mp4"
        autoPlay
        muted
        loop
        playsInline
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", opacity: 0.42 }}
      />
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(120% 100% at 25% 15%, rgba(22,34,46,0.5), rgba(5,9,15,0.92) 60%)" }} />
      <div style={{ position: "relative", maxWidth: MAXW, margin: "0 auto", padding: "0 24px", width: "100%" }}>
        <div style={{ maxWidth: 760 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 14px", borderRadius: "var(--radius-full)", border: "1px solid rgba(139,155,170,0.35)", background: "rgba(139,155,170,0.08)", color: "rgba(168,184,198,0.95)", fontSize: 12.5, fontWeight: 600, marginBottom: 26 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#3FB950" }} />
            Plataforma de planificación neurovascular · UniNavarra
          </div>
          <h1 style={{ fontSize: "clamp(38px, 6vw, 68px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.04, color: "#fff", margin: 0 }}>
            Detección y simulación quirúrgica de aneurismas cerebrales
          </h1>
          <p style={{ fontSize: "clamp(16px, 2vw, 20px)", color: "rgba(235,235,235,0.72)", lineHeight: 1.55, marginTop: 22, maxWidth: 620 }}>
            Carga el estudio DICOM y PROSPECTIVE segmenta la vasculatura en 3D, detecta el aneurisma,
            lo mide, evalúa el riesgo y te ayuda a decidir entre clipaje y tratamiento endovascular —
            todo en el navegador.
          </p>
          <div style={{ display: "flex", gap: 14, marginTop: 34, flexWrap: "wrap" }}>
            <button
              onClick={onEnter}
              style={{ height: 50, padding: "0 28px", borderRadius: "var(--radius-md)", border: "none", background: "var(--primary)", color: "var(--primary-foreground)", fontWeight: 700, fontSize: 15, cursor: "pointer" }}
            >
              Iniciar sesión
            </button>
            <a
              href="#pipeline"
              style={{ height: 50, display: "inline-flex", alignItems: "center", padding: "0 24px", borderRadius: "var(--radius-md)", border: "1px solid rgba(139,155,170,0.4)", background: "rgba(5,9,15,0.3)", color: "#fff", fontWeight: 700, fontSize: 15, textDecoration: "none" }}
            >
              Ver el pipeline ↓
            </a>
          </div>
          <div style={{ display: "flex", gap: 26, marginTop: 40, color: "rgba(168,184,198,0.8)", fontSize: 13, fontFamily: "var(--font-mono)", flexWrap: "wrap" }}>
            <span>7 pasos de flujo</span><span>·</span><span>VTK · SimpleITK</span><span>·</span><span>Render 3D en navegador</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── What / Why ─────────────────────────────────────────────────────────── */
function What() {
  return (
    <Section id="que-es" style={{ background: "var(--canvas)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 48, alignItems: "center" }}>
        <div>
          <Kicker>Qué es</Kicker>
          <H2>Decisiones quirúrgicas basadas en datos, no solo en la inspección visual</H2>
          <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 18 }}>
            Los aneurismas cerebrales exigen una planificación preoperatoria precisa: elegir entre
            <b style={{ color: "var(--foreground)" }}> clipaje quirúrgico</b> o
            <b style={{ color: "var(--foreground)" }}> tratamiento endovascular</b> depende de la
            morfología exacta del aneurisma, su cuello, su relación con perforantes y el riesgo de rotura.
          </p>
          <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 14 }}>
            PROSPECTIVE convierte el estudio DICOM en un modelo 3D medible y aporta métricas objetivas
            (DNR, AR, BF, PHASES…), un motor de decisión y catálogos reales de dispositivos — para apoyar
            al equipo en cada paso.
          </p>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {([
            ["TARGET", "Objetivo", "Medidas reproducibles en milímetros, no estimaciones a ojo."],
            ["STEP_MORPHO", "Cuantitativo", "Índices morfológicos y de riesgo validados en la literatura."],
            ["STEP_PLAN", "Accionable", "Recomendación clip vs endovascular y planificación de dispositivo."],
            ["DOC", "Trazable", "Informe PDF y seguimiento longitudinal del aneurisma."],
          ] as [IconName, string, string][]).map(([icon, t, d]) => (
            <div key={t} style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "18px 18px", boxShadow: "var(--shadow-sm)" }}>
              <div style={{ width: 40, height: 40, borderRadius: "var(--radius-md)", background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Icon name={icon} size={19} />
              </div>
              <div style={{ fontSize: 14.5, fontWeight: 700, color: "var(--foreground)", marginTop: 10 }}>{t}</div>
              <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 4, lineHeight: 1.5 }}>{d}</div>
            </div>
          ))}
        </div>
      </div>
    </Section>
  );
}

/* ── Pipeline video (Remotion-rendered explainer) ───────────────────────── */
function Pipeline() {
  const steps = ["Carga DICOM", "Segmentación", "Detección", "Morfometría", "Decisión", "Dispositivos", "Informe"];
  const videoRef = useRef<HTMLVideoElement>(null);

  // Guarantee autoplay: set the muted *property* (React only sets the attribute)
  // and call play() once the clip can start, ignoring the harmless promise reject.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = true;
    const tryPlay = () => v.play().catch(() => {});
    tryPlay();
    v.addEventListener("canplay", tryPlay);
    return () => v.removeEventListener("canplay", tryPlay);
  }, []);

  return (
    <Section id="pipeline" style={{ background: "var(--background)" }}>
      <div style={{ textAlign: "center", maxWidth: 720, margin: "0 auto 40px" }}>
        <Kicker>El pipeline</Kicker>
        <H2>Del DICOM al plan quirúrgico en siete pasos</H2>
        <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 16 }}>
          Un recorrido animado por el flujo completo de PROSPECTIVE, desde la carga del estudio
          hasta el informe final.
        </p>
      </div>
      <div style={{ position: "relative", borderRadius: "var(--radius-xl)", overflow: "hidden", border: "1px solid var(--border)", boxShadow: "var(--shadow-lg)", background: "#000", aspectRatio: "16 / 9", maxWidth: 980, margin: "0 auto" }}>
        <video
          ref={videoRef}
          src="/media/pipeline.mp4"
          autoPlay
          muted
          loop
          playsInline
          controls
          preload="auto"
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        />
      </div>
      <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 24, flexWrap: "wrap" }}>
        {steps.map((s, i) => (
          <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--muted-foreground)" }}>
            <span style={{ width: 22, height: 22, borderRadius: "50%", background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700 }}>{i + 1}</span>
            {s}
            {i < steps.length - 1 && <span style={{ color: "var(--border)", marginLeft: 4 }}>→</span>}
          </span>
        ))}
      </div>
    </Section>
  );
}

/* ── Features ───────────────────────────────────────────────────────────── */
const FEATURES: [IconName, string, string][] = [
  ["STEP_SEGMENT", "Segmentación vascular 3D", "Marching Cubes sobre VTK con umbrales auto por modalidad (CTA · MRA · 3DRA) y limpieza de fragmentos."],
  ["STEP_DETECT", "Detección de aneurismas", "Análisis de curvatura gaussiana (v6) con puertas de forma para localizar candidatos y aislar el domo."],
  ["STEP_MORPHO", "Morfometría completa", "Cuello, domo, volumen y los índices clínicos: DNR, AR, BF, UI, EI, NSI, SR y PHASES."],
  ["MARK_PERF", "Riesgo de perforantes", "Detección de arterias perforantes cercanas al cuello y clasificación de riesgo por distancia."],
  ["STEP_PLAN", "Decisión terapéutica", "Motor de 8 factores que pondera clipaje vs endovascular con desglose de cada factor."],
  ["CLIPS", "Planificación de dispositivos", "Catálogos reales: 42 clips, 39 coils y stents/flow-diverters, con recomendación y cobertura."],
  ["STEP_EXPORT", "Informe y export 3D", "Informe PDF de planificación quirúrgica y export de la malla en STL para impresión 3D."],
  ["GROWTH", "Seguimiento longitudinal", "Comparación entre estudios con alerta automática de crecimiento del aneurisma."],
];
function Features() {
  return (
    <Section id="funcionalidades" style={{ background: "var(--canvas)" }}>
      <div style={{ textAlign: "center", maxWidth: 680, margin: "0 auto 44px" }}>
        <Kicker>Funcionalidades</Kicker>
        <H2>Todo el flujo neurovascular en una sola plataforma</H2>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 18 }}>
        {FEATURES.map(([icon, title, desc]) => (
          <div key={title} style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "22px 20px", boxShadow: "var(--shadow-sm)" }}>
            <div style={{ width: 42, height: 42, borderRadius: "var(--radius-md)", background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
              <Icon name={icon} size={20} />
            </div>
            <div style={{ fontSize: 15.5, fontWeight: 700, color: "var(--foreground)" }}>{title}</div>
            <div style={{ fontSize: 13.5, color: "var(--muted-foreground)", marginTop: 6, lineHeight: 1.6 }}>{desc}</div>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ── Use cases ──────────────────────────────────────────────────────────── */
function UseCases() {
  const cases: [IconName, string, string][] = [
    ["STEP_PLAN", "Planificación preoperatoria", "Elige abordaje y dispositivo con medidas objetivas antes de entrar a quirófano."],
    ["USERS", "Comité multidisciplinar (MDT)", "Un lenguaje común de métricas para discutir casos entre neurocirugía y neurorradiología."],
    ["BRAIN", "Docencia y formación", "Los residentes exploran morfología y decisiones sobre casos reales de forma guiada."],
    ["DOC", "Investigación", "Métricas reproducibles y export de mallas para estudios morfológicos y hemodinámicos."],
    ["GROWTH", "Vigilancia de no rotos", "Seguimiento de aneurismas no tratados con alerta de crecimiento entre controles."],
  ];
  return (
    <Section style={{ background: "var(--background)" }}>
      <div style={{ maxWidth: 680, margin: "0 auto 44px", textAlign: "center" }}>
        <Kicker>Para qué sirve</Kicker>
        <H2>De la consulta al quirófano, y del aula al laboratorio</H2>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 18 }}>
        {cases.map(([icon, t, d]) => (
          <div key={t} style={{ display: "flex", gap: 14, padding: "18px 4px" }}>
            <div style={{ width: 40, height: 40, flexShrink: 0, borderRadius: "var(--radius-md)", background: "var(--accent)", color: "var(--accent-foreground)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Icon name={icon} size={19} />
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: "var(--foreground)" }}>{t}</div>
              <div style={{ fontSize: 13.5, color: "var(--muted-foreground)", marginTop: 5, lineHeight: 1.6 }}>{d}</div>
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ── How it works (3 steps) ─────────────────────────────────────────────── */
function HowItWorks() {
  const steps: [string, string, string][] = [
    ["01", "Sube el estudio", "Arrastra la carpeta DICOM (CTA, MRA o 3DRA). El servidor detecta la serie y calcula los umbrales automáticamente."],
    ["02", "El sistema analiza", "Segmenta la vasculatura, detecta el aneurisma, lo mide y evalúa riesgo de rotura y perforantes."],
    ["03", "Recibes el plan", "Recomendación de tratamiento, dispositivo sugerido con cobertura, informe PDF y malla 3D."],
  ];
  return (
    <Section style={{ background: "var(--canvas)" }}>
      <div style={{ maxWidth: 680, margin: "0 auto 44px", textAlign: "center" }}>
        <Kicker>Cómo funciona</Kicker>
        <H2>Tres pasos, sin instalar nada</H2>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 20 }}>
        {steps.map(([n, t, d]) => (
          <div key={n} style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "24px 22px", boxShadow: "var(--shadow-sm)" }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 32, fontWeight: 800, color: "var(--brand-mist)" }}>{n}</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--foreground)", marginTop: 10 }}>{t}</div>
            <div style={{ fontSize: 13.5, color: "var(--muted-foreground)", marginTop: 6, lineHeight: 1.6 }}>{d}</div>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ── Technology ─────────────────────────────────────────────────────────── */
function Technology() {
  const stack = ["VTK", "SimpleITK", "pydicom", "scipy", "FastAPI", "React", "vtk.js", "SQLite"];
  const stats: [string, string][] = [
    ["26", "endpoints REST"],
    ["100%", "procesamiento en servidor"],
    ["3D", "render en el navegador (vtk.js)"],
    ["JWT", "autenticación segura"],
  ];
  return (
    <Section id="tecnologia" style={{ background: "var(--background)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 44, alignItems: "center" }}>
        <div>
          <Kicker>Tecnología</Kicker>
          <H2>Imagen médica de verdad, servida a la web</H2>
          <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 16 }}>
            El procesamiento pesado (segmentación, detección, morfometría) corre en el servidor con las
            mismas librerías que la aplicación de escritorio; el navegador solo renderiza la malla 3D.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 22 }}>
            {stack.map((s) => (
              <span key={s} style={{ padding: "6px 12px", borderRadius: "var(--radius-full)", background: "var(--muted)", color: "var(--foreground)", fontSize: 12.5, fontWeight: 600, fontFamily: "var(--font-mono)" }}>{s}</span>
            ))}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {stats.map(([v, l]) => (
            <div key={l} style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "22px 20px", boxShadow: "var(--shadow-sm)" }}>
              <div style={{ fontSize: 30, fontWeight: 800, fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>{v}</div>
              <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 4 }}>{l}</div>
            </div>
          ))}
        </div>
      </div>
    </Section>
  );
}

/* ── Security + Team + Disclaimer + CTA ──────────────────────────────────── */
function Security() {
  const items: [IconName, string, string][] = [
    ["LOCK", "Autenticación JWT", "Acceso con token firmado; sesión persistente y protegida."],
    ["USER", "Aprobación de cuentas", "El registro profesional queda pendiente hasta que un administrador lo autoriza."],
    ["FOLDER", "Datos pseudonimizados", "Los pacientes se registran sin datos identificativos directos."],
    ["SAVE", "Sesiones aisladas", "Cada estudio vive en su propio espacio temporal en el servidor."],
  ];
  return (
    <Section style={{ background: "var(--canvas)" }}>
      <div style={{ maxWidth: 680, margin: "0 auto 40px", textAlign: "center" }}>
        <Kicker>Seguridad y datos</Kicker>
        <H2>Pensado para un entorno clínico</H2>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 18 }}>
        {items.map(([icon, t, d]) => (
          <div key={t} style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 18px", boxShadow: "var(--shadow-sm)" }}>
            <Icon name={icon} size={20} color="var(--brand-slate)" />
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--foreground)", marginTop: 10 }}>{t}</div>
            <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 5, lineHeight: 1.55 }}>{d}</div>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ── Clinical indices / rigor ───────────────────────────────────────────── */
function Indices() {
  const metrics: [string, string, string][] = [
    ["DNR", "Dome-to-Neck Ratio", "Ø máx / cuello · riesgo ↑ si ≥ 2.0"],
    ["AR", "Aspect Ratio", "altura de domo / cuello · riesgo ↑ si ≥ 1.6"],
    ["BF", "Bottleneck Factor", "Ø domo / cuello · cuello ancho si > 1.5"],
    ["UI", "Undulation Index", "irregularidad del domo · alto si ≥ 0.25"],
    ["EI", "Ellipticity Index", "desviación elíptica · moderado si ≥ 0.35"],
    ["NSI", "Non-Sphericity Index", "1 − esfericidad de Wadell"],
    ["SR", "Size Ratio", "Ø máx / arteria madre · alto si ≥ 3.0"],
    ["PHASES", "Riesgo a 5 años", "escala de Greving et al., Lancet Neurology 2014"],
  ];
  return (
    <Section id="indices" style={{ background: "var(--background)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 44, alignItems: "start" }}>
        <div style={{ position: "sticky", top: 96 }}>
          <Kicker>Rigor clínico</Kicker>
          <H2>Índices morfológicos validados en la literatura</H2>
          <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 16 }}>
            PROSPECTIVE no da una opinión: calcula los índices morfométricos estándar y la escala
            PHASES a partir de la geometría real del aneurisma, con los umbrales de riesgo publicados.
          </p>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 20, fontSize: 13, color: "var(--muted-foreground)" }}>
            <Icon name="BOOK" size={17} color="var(--brand-slate)" />
            Referencias: Greving 2014 · Dhar 2008 · Raghavan 2005 · Wadell
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {metrics.map(([abbr, title, desc]) => (
            <div key={abbr} style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "16px 16px", boxShadow: "var(--shadow-sm)" }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 20, fontWeight: 800, color: "var(--brand-slate)" }}>{abbr}</div>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: "var(--foreground)", marginTop: 6 }}>{title}</div>
              <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginTop: 4, lineHeight: 1.5, fontFamily: "var(--font-mono)" }}>{desc}</div>
            </div>
          ))}
        </div>
      </div>
    </Section>
  );
}

/* ── Device catalogs ────────────────────────────────────────────────────── */
function Devices() {
  const groups: [IconName, string, string, string[]][] = [
    ["CLIPS", "Clips quirúrgicos", "42 modelos · rectos, curvos, angulados, fenestrados", ["Aesculap Yasargil", "Sugita (Mizuho)", "Codman (DePuy)"]],
    ["COIL", "Coils de embolización", "39 modelos · framing, filling, finishing", ["Target 360", "GDC", "Axium Prime"]],
    ["STENT", "Stents y desviadores de flujo", "flow-diverters + stents de coiling asistido", ["Pipeline (Medtronic)", "Surpass (Stryker)", "FRED · Enterprise 2 · Leo+"]],
  ];
  return (
    <Section style={{ background: "var(--canvas)" }}>
      <div style={{ maxWidth: 680, margin: "0 auto 44px", textAlign: "center" }}>
        <Kicker>Dispositivos</Kicker>
        <H2>Catálogos reales de dispositivos neurovasculares</H2>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 18 }}>
        {groups.map(([icon, title, sub, brands]) => (
          <div key={title} style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "24px 22px", boxShadow: "var(--shadow-sm)" }}>
            <div style={{ width: 46, height: 46, borderRadius: "var(--radius-md)", background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
              <Icon name={icon} size={22} />
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--foreground)" }}>{title}</div>
            <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 5, lineHeight: 1.55 }}>{sub}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 14 }}>
              {brands.map((b) => (
                <span key={b} style={{ padding: "4px 10px", borderRadius: "var(--radius-full)", background: "var(--muted)", color: "var(--muted-foreground)", fontSize: 11.5, fontWeight: 600 }}>{b}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ── Roadmap / coming soon ──────────────────────────────────────────────── */
function Roadmap() {
  const items: [IconName, string, string][] = [
    ["CLOUD", "SkullCloud", "Almacenamiento y colaboración de casos en la nube entre centros."],
    ["VRAR", "AR / VR", "Exploración inmersiva de la anatomía vascular y el plan quirúrgico."],
    ["CHART", "Analítica", "Estadísticas agregadas de casos, dispositivos y resultados."],
  ];
  return (
    <Section style={{ background: "var(--background)" }}>
      <div style={{ maxWidth: 680, margin: "0 auto 44px", textAlign: "center" }}>
        <Kicker>Próximamente</Kicker>
        <H2>Hacia dónde va PROSPECTIVE</H2>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 18 }}>
        {items.map(([icon, t, d]) => (
          <div key={t} style={{ position: "relative", background: "var(--card)", border: "1px dashed var(--border)", borderRadius: "var(--radius-lg)", padding: "24px 22px" }}>
            <span style={{ position: "absolute", top: 16, right: 16, display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10.5, fontWeight: 700, color: "var(--brand-slate)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              <Icon name="SPARKLE" size={12} /> Próximamente
            </span>
            <div style={{ width: 44, height: 44, borderRadius: "var(--radius-md)", background: "var(--accent)", color: "var(--accent-foreground)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
              <Icon name={icon} size={21} />
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--foreground)" }}>{t}</div>
            <div style={{ fontSize: 13.5, color: "var(--muted-foreground)", marginTop: 6, lineHeight: 1.6 }}>{d}</div>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ── Contact ────────────────────────────────────────────────────────────── */
function Contact() {
  const rows: [IconName, string, string, string | null][] = [
    ["MAIL", "Correo", "juesnaca99@gmail.com", "mailto:juesnaca99@gmail.com"],
    ["PIN", "Institución", "Fundación Universitaria Navarra (UniNavarra)", null],
    ["BRAIN", "Laboratorio", "Laboratorio de Imagen Médica", null],
  ];
  return (
    <Section id="contacto" style={{ background: "var(--canvas)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 44, alignItems: "center" }}>
        <div>
          <Kicker>Contacto</Kicker>
          <H2>¿Interesado en PROSPECTIVE?</H2>
          <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 16 }}>
            Para acceso, colaboración clínica o de investigación, o cualquier consulta sobre la
            plataforma, escríbenos. El registro profesional lo aprueba el administrador.
          </p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {rows.map(([icon, label, value, href]) => {
            const inner = (
              <div style={{ display: "flex", alignItems: "center", gap: 14, background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "16px 18px", boxShadow: "var(--shadow-sm)" }}>
                <div style={{ width: 42, height: 42, flexShrink: 0, borderRadius: "var(--radius-md)", background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <Icon name={icon} size={20} />
                </div>
                <div>
                  <div style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--muted-foreground)" }}>{label}</div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: "var(--foreground)", marginTop: 2 }}>{value}</div>
                </div>
                {href && <div style={{ flex: 1, textAlign: "right", color: "var(--brand-deep)" }}><Icon name="ARROW_UP_RIGHT" size={16} /></div>}
              </div>
            );
            return href ? (
              <a key={label} href={href} style={{ textDecoration: "none" }}>{inner}</a>
            ) : (
              <div key={label}>{inner}</div>
            );
          })}
        </div>
      </div>
    </Section>
  );
}

function CTA({ onEnter }: { onEnter: () => void }) {
  return (
    <Section style={{ background: "var(--background)" }}>
      <div
        style={{
          position: "relative",
          overflow: "hidden",
          borderRadius: "var(--radius-xl)",
          padding: "64px 32px",
          textAlign: "center",
          background: "radial-gradient(120% 140% at 50% 0%, #16222e, #0a121c 70%)",
          border: "1px solid var(--border)",
        }}
      >
        <div style={{ position: "relative", zIndex: 1, maxWidth: 640, margin: "0 auto" }}>
          <img className="logo-mark" src={logo} alt="" style={{ height: 60, filter: "invert(1) brightness(1.7)" }} />
          <h2 style={{ fontSize: "clamp(26px, 3.6vw, 40px)", fontWeight: 800, letterSpacing: "-0.02em", color: "#fff", margin: "18px 0 0", lineHeight: 1.12 }}>
            Empieza a planificar con PROSPECTIVE
          </h2>
          <p style={{ fontSize: 16, color: "rgba(235,235,235,0.72)", marginTop: 14, lineHeight: 1.6 }}>
            Accede con tu cuenta o solicita el registro profesional. La aprobación la gestiona el administrador.
          </p>
          <button
            onClick={onEnter}
            style={{ marginTop: 28, height: 50, padding: "0 32px", borderRadius: "var(--radius-md)", border: "none", background: "var(--brand-mist)", color: "#1c1c1c", fontWeight: 700, fontSize: 15, cursor: "pointer" }}
          >
            Entrar a la plataforma
          </button>
        </div>
      </div>
    </Section>
  );
}

function Footer() {
  return (
    <footer style={{ borderTop: "1px solid var(--border)", background: "var(--canvas)" }}>
      <div style={{ maxWidth: MAXW, margin: "0 auto", padding: "36px 24px", display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <img className="logo-mark" src={logo} alt="" style={{ height: 40 }} />
          <span style={{ fontWeight: 800, fontSize: 17, color: "var(--foreground)" }}>PROSPECTIVE</span>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 12.5, color: "var(--muted-foreground)", textAlign: "right" }}>
          <div>Fundación Universitaria Navarra (UniNavarra) · Laboratorio de Imagen Médica</div>
          <div style={{ marginTop: 4 }}>
            PROSPECTIVE™ es una herramienta de apoyo a la planificación. No sustituye el juicio clínico.
          </div>
        </div>
      </div>
    </footer>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */
export function Landing() {
  const navigate = useNavigate();
  const enter = () => navigate("/app");
  return (
    <div style={{ background: "var(--canvas)", minHeight: "100%" }}>
      <Nav onEnter={enter} />
      <Hero onEnter={enter} />
      <What />
      <Pipeline />
      <Features />
      <Indices />
      <Devices />
      <UseCases />
      <HowItWorks />
      <Technology />
      <Security />
      <Roadmap />
      <Contact />
      <CTA onEnter={enter} />
      <Footer />
    </div>
  );
}
