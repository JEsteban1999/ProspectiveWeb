/* Estudios — galería de los estudios cargados.

   Rejilla de tarjetas con vista previa (una imagen del estudio) y buscador por
   nombre de paciente o cédula. Al clicar una tarjeta se abre el estudio
   completo. El mismo componente `StudyGallery` se reutiliza dentro de la ficha
   del paciente pasando `patientId`. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { StudyCard } from "../api/types";
import { Badge, riskVariant } from "../components/Badge";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { Input } from "../components/Input";
import { Topbar } from "../components/Topbar";
import { ErrorNote } from "../components/PanelHead";

const STEP_LABELS = ["Carga", "Segmentación", "Detección", "Morfometría", "Decisión", "Dispositivos", "Informe"];

/** Preview image of a study — fetched with the JWT, so it goes through a blob. */
function Thumbnail({ study }: { study: StudyCard }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!study.has_thumbnail) return;
    let alive = true;
    let created: string | null = null;
    api.studyThumbnailObjectUrl(study.id)
      .then((u) => { if (alive) { created = u; setUrl(u); } else URL.revokeObjectURL(u); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; if (created) URL.revokeObjectURL(created); };
  }, [study.id, study.has_thumbnail]);

  const box: React.CSSProperties = {
    width: "100%", aspectRatio: "1 / 1", background: "#000",
    display: "flex", alignItems: "center", justifyContent: "center",
    borderTopLeftRadius: "var(--radius-lg)", borderTopRightRadius: "var(--radius-lg)",
    overflow: "hidden", position: "relative",
  };

  if (url) {
    return (
      <div style={box}>
        <img src={url} alt={`Vista previa de ${study.description}`}
             style={{ width: "100%", height: "100%", objectFit: "contain" }} />
      </div>
    );
  }
  return (
    <div style={{ ...box, color: "var(--muted-foreground)", fontSize: 11, gap: 6, flexDirection: "column" }}>
      <Icon name="FOLDER" size={22} />
      {failed ? "Sin vista previa" : study.has_thumbnail ? "Cargando…" : "Sin archivar"}
    </div>
  );
}

export function StudyGallery({
  patientId,
  caseId,
  onOpen,
  onResume,
  compact = false,
  emptyHint,
}: {
  /** Restrict to one patient (used inside the patient sheet). */
  patientId?: number;
  /** Restrict to one clinical case — a case can hold several acquisitions. */
  caseId?: number;
  onOpen: (study: StudyCard) => void;
  /** Restore the study's saved session instead of starting a new one. */
  onResume?: (study: StudyCard) => void;
  compact?: boolean;
  /** Message shown when this scope has no imaging studies yet. */
  emptyHint?: string;
}) {
  const [studies, setStudies] = useState<StudyCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  // The search goes to the server (debounced). Filtering only on the client
  // searched whatever page happened to be loaded, so on a real archive an older
  // patient came back empty with nothing to explain why.
  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      setLoading(true);
      api.listStudies(q.trim(), patientId, caseId)
        .then((s) => { if (alive) setStudies(s); })
        .catch((e) => { if (alive) setError(e instanceof Error ? e.message : "Error cargando estudios"); })
        .finally(() => { if (alive) setLoading(false); });
    }, q.trim() ? 280 : 0);
    return () => { alive = false; clearTimeout(t); };
  }, [patientId, caseId, q]);

  const rows = studies;

  return (
    <div>
      {!compact && (
        <div style={{ maxWidth: 420, marginBottom: 18 }}>
          <Input
            placeholder="Buscar por paciente, cédula o diagnóstico…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      )}

      <ErrorNote>{error}</ErrorNote>

      {loading ? (
        <div style={{ color: "var(--muted-foreground)", fontSize: 13 }}>Cargando estudios…</div>
      ) : rows.length === 0 ? (
        <div style={{ color: "var(--muted-foreground)", fontSize: compact ? 11 : 13, padding: compact ? "6px 0" : "24px 0", textAlign: compact ? "left" : "center" }}>
          {q.trim()
            ? `Ningún estudio coincide con «${q.trim()}».`
            : (emptyHint ?? "Aún no hay estudios archivados. Carga un DICOM en el pipeline y pulsa «Guardar estudio».")}
        </div>
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: `repeat(auto-fill, minmax(${compact ? 150 : 190}px, 1fr))`,
          gap: 14,
        }}>
          {rows.map((s) => {
            const canResume = !!s.resumable_session_id && !!onResume;
            return (
            <div
              key={s.id}
              title={`${s.patient_name} · ${s.description}`}
              style={{
                display: "flex", flexDirection: "column", textAlign: "left", padding: 0,
                background: "var(--card)", border: "1px solid var(--border)",
                borderRadius: "var(--radius-lg)", overflow: "hidden",
                fontFamily: "var(--font-sans)", boxShadow: "var(--shadow-sm)",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--brand-deep)")}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
            >
              <button
                type="button"
                onClick={() => (canResume ? onResume?.(s) : onOpen(s))}
                style={{ display: "block", padding: 0, border: "none", background: "transparent", cursor: "pointer", width: "100%" }}
              >
                <Thumbnail study={s} />
              </button>
              <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
                {/* Inside a case the patient is already known, so the card leads
                    with what distinguishes one acquisition from another. */}
                {compact ? (
                  <>
                    <div className="truncate" style={{ fontSize: 12, fontWeight: 700, color: "var(--foreground)" }}>
                      {s.description}
                    </div>
                    {s.acquired_at && (
                      <div className="truncate" style={{ fontSize: 10, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                        {s.acquired_at}
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <div className="truncate" style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)" }}>
                      {s.patient_name || "—"}
                    </div>
                    <div className="truncate" style={{ fontSize: 11, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                      {s.hospital_id || "sin HC"}
                    </div>
                    <div className="truncate" style={{ fontSize: 11, color: "var(--muted-foreground)" }}>
                      {s.description}
                    </div>
                  </>
                )}
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 2 }}>
                  {s.modality && <Badge variant="subtle">{s.modality}</Badge>}
                  {s.n_slices > 0 && (
                    <span style={{ fontSize: 10, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                      {s.n_slices} cortes
                    </span>
                  )}
                  {s.rupture_risk_label && (
                    <Badge variant={riskVariant(s.rupture_risk_label as never)}>{s.rupture_risk_label}</Badge>
                  )}
                </div>
                <div style={{ fontSize: 10, color: "var(--muted-foreground)", marginTop: 2 }}>
                  {s.last_step != null
                    ? `Último paso: ${STEP_LABELS[s.last_step] ?? s.last_step}`
                    : s.archived ? "Sin procesar" : "No archivado"}
                </div>

                {/* The card advertises progress, so the primary action has to be
                    the one that keeps it. «Abrir» starts a fresh session at step 1
                    and says so, instead of doing it silently behind one click. */}
                <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                  {canResume && (
                    <button
                      type="button"
                      onClick={() => onResume?.(s)}
                      title={s.last_step != null ? `Reanudar en «${STEP_LABELS[s.last_step] ?? s.last_step}»` : "Reanudar la sesión guardada"}
                      style={{
                        flex: 1, padding: "5px 8px", fontSize: 11, fontWeight: 700,
                        borderRadius: "var(--radius-md)", border: "none", cursor: "pointer",
                        background: "var(--brand-deep)", color: "#fff",
                        fontFamily: "var(--font-sans)", whiteSpace: "nowrap",
                      }}
                    >
                      Reanudar
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onOpen(s)}
                    title={canResume ? "Empezar una sesión nueva desde el paso 1" : undefined}
                    style={{
                      flex: canResume ? "0 0 auto" : 1, padding: "5px 10px", fontSize: 11,
                      fontWeight: 600, borderRadius: "var(--radius-md)",
                      border: "1px solid var(--border)", cursor: "pointer",
                      background: "transparent", color: "var(--foreground)",
                      fontFamily: "var(--font-sans)", whiteSpace: "nowrap",
                    }}
                  >
                    {canResume ? "De cero" : "Abrir"}
                  </button>
                </div>
              </div>
            </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Studies({
  onOpen, onResume, onBack,
}: {
  onOpen: (study: StudyCard) => void;
  onResume: (study: StudyCard) => void;
  onBack: () => void;
}) {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--canvas)" }}>
      <Topbar crumbs={[{ label: "Pacientes", onClick: onBack }, { label: "Estudios" }]}>
        <Button variant="ghost" size="sm" onClick={onBack} leadingIcon={<Icon name="HOME" />}>
          Pacientes
        </Button>
      </Topbar>
      <div style={{ flex: 1, overflowY: "auto" }}>
        <div style={{ maxWidth: 1320, margin: "0 auto", padding: "28px 24px 40px" }}>
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 22, fontWeight: 800, color: "var(--foreground)" }}>Estudios</div>
            <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 2 }}>
              Estudios cargados y archivados · haz clic en uno para abrirlo
            </div>
          </div>
          <StudyGallery onOpen={onOpen} onResume={onResume} />
        </div>
      </div>
    </div>
  );
}
