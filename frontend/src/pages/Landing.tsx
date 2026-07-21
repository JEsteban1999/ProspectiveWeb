/* Landing — public marketing/onboarding page for PROSPECTIVE.
   One long scroll: hero → what/why → pipeline video → features → use cases →
   how it works → technology → security → team → disclaimer → CTA.
   "Entrar" routes to the app (/app). Uses the design system, light + dark. */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BorderBeam } from "border-beam";
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
        height: 68,
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "0 24px",
        // Fondo sólido SIEMPRE: así el contenido nunca se transparenta a través
        // del navbar (el bug del "remontado"). Al scrollear se opaca un poco más.
        background: scrolled
          ? "color-mix(in srgb, var(--background) 97%, transparent)"
          : "color-mix(in srgb, var(--background) 90%, transparent)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        borderBottom: `1px solid ${scrolled ? "var(--border)" : "color-mix(in srgb, var(--border) 55%, transparent)"}`,
        boxShadow: scrolled ? "var(--shadow-sm)" : "none",
        transition: "background .2s, border-color .2s, box-shadow .2s",
      }}
    >
      <div style={{ maxWidth: MAXW, margin: "0 auto", width: "100%", display: "flex", alignItems: "center", gap: 14 }}>
        <img className="logo-mark" src={logo} alt="" style={{ height: 42 }} />
        <span style={{ fontWeight: 800, fontSize: 20, letterSpacing: "-0.02em", color: "var(--foreground)" }}>PROSPECTIVE</span>
        <div style={{ flex: 1 }} />
        <nav className="landing-nav-links" style={{ display: "flex", gap: 20, marginRight: 8 }}>
          {links.map(([label, id]) => (
            <a key={id} href={`#${id}`} style={{ fontSize: 12.5, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted-foreground)", textDecoration: "none" }}>
              {label}
            </a>
          ))}
        </nav>
        <ThemeToggle size="sm" />
        <BorderBeam size="sm" colorVariant="ocean" style={{ display: "inline-flex" }}>
          <button
            onClick={onEnter}
            style={{ height: 38, padding: "0 18px", borderRadius: "var(--radius-md)", border: "none", background: "var(--primary)", color: "var(--primary-foreground)", fontWeight: 700, fontSize: 12.5, letterSpacing: "0.04em", textTransform: "uppercase", cursor: "pointer" }}
          >
            Entrar
          </button>
        </BorderBeam>
      </div>
    </div>
  );
}

/* ── Hero ───────────────────────────────────────────────────────────────── */
function Hero({ onEnter }: { onEnter: () => void }) {
  return (
    <div style={{ position: "relative", overflow: "hidden", minHeight: "calc(100vh - 68px)", display: "flex", alignItems: "center", background: "#05090f" }}>
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
            Plataforma de planificación neurovascular · SkullApp
          </div>
          <h1 style={{ fontSize: "clamp(38px, 6vw, 68px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.04, color: "#fff", margin: 0 }}>
            Planificar la cirugía de un aneurisma cerebral, con datos y en 3D
          </h1>
          <p style={{ fontSize: "clamp(16px, 2vw, 20px)", color: "rgba(235,235,235,0.72)", lineHeight: 1.55, marginTop: 22, maxWidth: 640 }}>
            A partir de la tomografía o angiografía del paciente, PROSPECTIVE reconstruye la arteria
            en 3D, localiza y mide el aneurisma, estima su riesgo de rotura y ayuda al médico a elegir
            el mejor tratamiento. Todo en el navegador, sin instalar nada.
          </p>
          <div style={{ display: "flex", gap: 14, marginTop: 34, flexWrap: "wrap" }}>
            <BorderBeam size="sm" colorVariant="ocean" theme="dark" style={{ display: "inline-flex" }}>
              <button
                onClick={onEnter}
                style={{ height: 50, padding: "0 28px", borderRadius: "var(--radius-md)", border: "none", background: "var(--primary)", color: "var(--primary-foreground)", fontWeight: 700, fontSize: 15, cursor: "pointer" }}
              >
                Iniciar sesión
              </button>
            </BorderBeam>
            <a
              href="#pipeline"
              style={{ height: 50, display: "inline-flex", alignItems: "center", padding: "0 24px", borderRadius: "var(--radius-md)", border: "1px solid rgba(139,155,170,0.4)", background: "rgba(5,9,15,0.3)", color: "#fff", fontWeight: 700, fontSize: 15, textDecoration: "none" }}
            >
              Ver el pipeline ↓
            </a>
          </div>
          <div style={{ display: "flex", gap: 26, marginTop: 40, color: "rgba(168,184,198,0.85)", fontSize: 13.5, flexWrap: "wrap" }}>
            <span>Sin instalar nada</span><span style={{ opacity: 0.4 }}>·</span>
            <span>Modelo 3D en el navegador</span><span style={{ opacity: 0.4 }}>·</span>
            <span>Medidas objetivas en milímetros</span>
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
          <H2>Decisiones quirúrgicas con datos, no solo a ojo</H2>
          <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 18 }}>
            Un <b style={{ color: "var(--foreground)" }}>aneurisma cerebral</b> es una dilatación en la
            pared de una arteria del cerebro —como un pequeño globo— que puede romperse y causar una
            hemorragia grave. Antes de tratarlo, el equipo médico debe decidir cómo hacerlo, y hacerlo
            con precisión milimétrica.
          </p>
          <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 14 }}>
            Hoy esa decisión se apoya mucho en mirar las imágenes. PROSPECTIVE convierte el estudio en
            un <b style={{ color: "var(--foreground)" }}>modelo 3D que se puede medir</b>, calcula
            indicadores objetivos de riesgo y sugiere el tratamiento — para que el equipo decida con
            datos y de forma reproducible.
          </p>
          {/* Glosario en lenguaje sencillo de los dos tratamientos posibles */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 22 }}>
            {([
              ["Clipaje quirúrgico", "Cirugía abierta: se coloca un pequeño clip metálico en la base del aneurisma para cerrarlo."],
              ["Tratamiento endovascular", "Sin abrir el cráneo: por dentro de la arteria, con un catéter, se rellena o cubre el aneurisma."],
            ] as [string, string][]).map(([t, d]) => (
              <div key={t} style={{ background: "var(--muted)", borderRadius: "var(--radius-md)", padding: "12px 14px" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)" }}>{t}</div>
                <div style={{ fontSize: 12.5, color: "var(--muted-foreground)", marginTop: 4, lineHeight: 1.5 }}>{d}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {([
            ["TARGET", "Objetivo", "Medidas en milímetros, reproducibles — no estimaciones a ojo."],
            ["STEP_MORPHO", "Con respaldo", "Indicadores de forma y riesgo respaldados por estudios clínicos."],
            ["STEP_PLAN", "Accionable", "Sugiere el tratamiento y el dispositivo, y verifica su colocación."],
            ["DOC", "Trazable", "Informe en PDF y seguimiento del aneurisma en el tiempo."],
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

/* ── Pipeline video ─────────────────────────────────────────────────────────
   Se muestran dos versiones del MISMO explicativo, renderizadas con motores
   distintos (Remotion y HyperFrames), para poder compararlas. */

/** Reproductor con autoplay garantizado: React solo pone el *atributo* muted,
    así que fijamos la propiedad y llamamos a play() en cuanto puede arrancar. */
function PipelinePlayer({ src, label, note }: { src: string; label: string; note: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
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
    <figure style={{ margin: 0, maxWidth: 980, marginLeft: "auto", marginRight: "auto" }}>
      <figcaption style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--brand-slate)" }}>
          {label}
        </span>
        <span style={{ fontSize: 13, color: "var(--muted-foreground)" }}>{note}</span>
      </figcaption>
      <div style={{ position: "relative", borderRadius: "var(--radius-xl)", overflow: "hidden", border: "1px solid var(--border)", boxShadow: "var(--shadow-lg)", background: "#000", aspectRatio: "16 / 9" }}>
        <video
          ref={videoRef}
          src={src}
          autoPlay
          muted
          loop
          playsInline
          controls
          preload="auto"
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        />
      </div>
    </figure>
  );
}

function Pipeline() {
  const steps = ["Carga DICOM", "Segmentación", "Detección", "Morfometría", "Decisión", "Dispositivos", "Informe"];
  return (
    <Section id="pipeline" style={{ background: "var(--background)" }}>
      <div style={{ textAlign: "center", maxWidth: 720, margin: "0 auto 40px" }}>
        <Kicker>El proceso</Kicker>
        <H2>Del estudio de imagen al plan quirúrgico, en siete pasos</H2>
        <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 16 }}>
          Un recorrido animado por el flujo completo de PROSPECTIVE, desde que se cargan las imágenes
          del paciente hasta el informe final.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
        <PipelinePlayer
          src="/media/pipeline.mp4"
          label="Versión A · Remotion"
          note="Composición en React, renderizada frame a frame."
        />
        <PipelinePlayer
          src="/media/pipeline-hf.mp4"
          label="Versión B · HyperFrames"
          note="Mismo contenido, compuesto en HTML + GSAP sobre una línea de tiempo seekable."
        />
      </div>

      <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 32, flexWrap: "wrap" }}>
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
  ["STEP_SEGMENT", "Reconstrucción 3D de las arterias", "Convierte la imagen médica en un modelo 3D de la red arterial. Compatible con TC, resonancia y angiografía rotacional."],
  ["STEP_DETECT", "Detección del aneurisma", "Localiza el aneurisma sobre el modelo y aísla su forma para poder medirla con exactitud."],
  ["STEP_MORPHO", "Medidas e índices de riesgo", "Mide cuello, domo y volumen, y calcula los índices de forma y riesgo usados en la literatura clínica."],
  ["MARK_PERF", "Aviso de arterias sensibles", "Señala las pequeñas arterias (perforantes) cercanas al aneurisma y las clasifica por riesgo según su distancia."],
  ["STEP_PLAN", "Ayuda a la decisión", "Compara cirugía abierta y tratamiento endovascular ponderando 8 factores, y muestra el porqué de cada uno."],
  ["CLIPS", "Planificación del dispositivo", "Catálogos reales de clips, coils y stents; sugiere el dispositivo adecuado y comprueba su colocación en 3D."],
  ["STEP_EXPORT", "Informe y modelo para imprimir", "Genera un informe en PDF del plan quirúrgico y exporta el modelo 3D para impresión."],
  ["GROWTH", "Seguimiento en el tiempo", "Compara estudios del mismo paciente entre controles y avisa automáticamente si el aneurisma crece."],
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
    ["01", "Sube el estudio", "Arrastra la carpeta con las imágenes del paciente (tomografía, resonancia o angiografía). El sistema las prepara automáticamente."],
    ["02", "El sistema analiza", "Reconstruye las arterias en 3D, detecta y mide el aneurisma, y evalúa su riesgo de rotura y las arterias sensibles alrededor."],
    ["03", "Recibes el plan", "Tratamiento recomendado, dispositivo sugerido con su cobertura, informe en PDF y modelo 3D para imprimir."],
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
    ["Web", "Funciona en el navegador, sin instalar nada"],
    ["Servidor", "El cálculo pesado corre en el servidor, no en tu equipo"],
    ["3D", "El modelo se explora en 3D en la propia página"],
    ["Seguro", "Acceso con inicio de sesión y cuentas aprobadas"],
  ];
  return (
    <Section id="tecnologia" style={{ background: "var(--background)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 44, alignItems: "center" }}>
        <div>
          <Kicker>Tecnología</Kicker>
          <H2>La potencia de una estación de trabajo, en una página web</H2>
          <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 16 }}>
            El análisis pesado se hace en el servidor con las mismas herramientas de imagen médica que
            un programa de escritorio profesional; tu navegador solo muestra el resultado en 3D. No hay
            nada que instalar ni configurar.
          </p>
          <div style={{ fontSize: 12.5, color: "var(--muted-foreground)", marginTop: 22, marginBottom: 8 }}>
            Construido sobre tecnologías estándar de la industria:
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {stack.map((s) => (
              <span key={s} style={{ padding: "6px 12px", borderRadius: "var(--radius-full)", background: "var(--muted)", color: "var(--foreground)", fontSize: 12.5, fontWeight: 600, fontFamily: "var(--font-mono)" }}>{s}</span>
            ))}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {stats.map(([v, l]) => (
            <div key={l} style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 18px", boxShadow: "var(--shadow-sm)" }}>
              <div style={{ fontSize: 21, fontWeight: 800, color: "var(--brand-slate)" }}>{v}</div>
              <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 6, lineHeight: 1.45 }}>{l}</div>
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
    ["LOCK", "Acceso seguro", "Cada persona entra con su usuario y contraseña; la sesión queda protegida."],
    ["USER", "Cuentas verificadas", "El registro de un profesional queda pendiente hasta que un administrador lo aprueba."],
    ["FOLDER", "Sin datos personales", "Los pacientes se registran sin nombre ni datos identificativos directos."],
    ["SAVE", "Cada caso, por separado", "El estudio de cada paciente vive en su propio espacio y no se mezcla con otros."],
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
          <H2>Indicadores objetivos, respaldados por la literatura</H2>
          <p style={{ fontSize: 16, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 16 }}>
            PROSPECTIVE no da una opinión: calcula medidas estándar a partir de la geometría real del
            aneurisma y las compara con los umbrales de riesgo publicados.
          </p>
          <p style={{ fontSize: 15, color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 12 }}>
            <b style={{ color: "var(--foreground)" }}>No hace falta conocer estas siglas:</b> el sistema
            las traduce a un nivel de riesgo (bajo · moderado · alto). Se muestran aquí, con su umbral,
            para el especialista que quiera el detalle.
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
    ["CLIPS", "Clips quirúrgicos", "42 modelos, en distintas formas y ángulos, para la cirugía abierta", ["Aesculap Yasargil", "Sugita (Mizuho)", "Codman (DePuy)"]],
    ["COIL", "Coils (rellenos)", "39 modelos que rellenan el aneurisma desde dentro de la arteria", ["Target 360", "GDC", "Axium Prime"]],
    ["STENT", "Stents y desviadores de flujo", "Mallas que se colocan en la arteria para apoyar o desviar el flujo", ["Pipeline (Medtronic)", "Surpass (Stryker)", "FRED · Enterprise 2 · Leo+"]],
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
    ["MAIL", "Correo", "ingprospective@skullapp.tech", "mailto:ingprospective@skullapp.tech"],
    ["PIN", "Institución", "SkullApp", null],
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
          <BorderBeam size="sm" colorVariant="ocean" theme="dark" style={{ display: "inline-flex", marginTop: 28 }}>
            <button
              onClick={onEnter}
              style={{ height: 50, padding: "0 32px", borderRadius: "var(--radius-md)", border: "none", background: "var(--brand-mist)", color: "#1c1c1c", fontWeight: 700, fontSize: 15, cursor: "pointer" }}
            >
              Entrar a la plataforma
            </button>
          </BorderBeam>
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
          <div>SkullApp · Laboratorio de Imagen Médica</div>
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
  // Señala que se entra desde la landing → la app mostrará la pantalla de carga
  // aunque ya haya sesión activa (si no, saltaría el login y no se vería).
  const enter = () => {
    sessionStorage.setItem("prospective.enterLoading", "1");
    navigate("/app");
  };
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
