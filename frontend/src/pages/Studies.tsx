/* Estudios — galería de los estudios cargados.

   Rejilla de tarjetas con vista previa (una imagen del estudio) y buscador por
   nombre de paciente o cédula. Al clicar una tarjeta se abre el estudio
   completo. El mismo componente `StudyGallery` se reutiliza dentro de la ficha
   del paciente pasando `patientId`. */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { StudyCard } from "../api/types";
import { Badge, riskVariant } from "../components/Badge";
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
  onOpen,
  compact = false,
}: {
  /** Restrict to one patient (used inside the patient sheet). */
  patientId?: number;
  onOpen: (study: StudyCard) => void;
  compact?: boolean;
}) {
  const [studies, setStudies] = useState<StudyCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.listStudies("", patientId)
      .then((s) => { if (alive) setStudies(s); })
      .catch((e) => { if (alive) setError(e instanceof Error ? e.message : "Error cargando estudios"); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [patientId]);

  // Filter on the client: the list is small and it keeps typing instant.
  const rows = useMemo(() => {
    const n = q.trim().toLowerCase();
    if (!n) return studies;
    return studies.filter((s) =>
      `${s.patient_name} ${s.hospital_id} ${s.description} ${s.dx_principal}`.toLowerCase().includes(n),
    );
  }, [studies, q]);

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
        <div style={{ color: "var(--muted-foreground)", fontSize: 13, padding: "24px 0", textAlign: "center" }}>
          {studies.length === 0
            ? "Aún no hay estudios archivados. Carga un DICOM en el pipeline y pulsa «Guardar estudio»."
            : "Ningún estudio coincide con la búsqueda."}
        </div>
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: `repeat(auto-fill, minmax(${compact ? 150 : 190}px, 1fr))`,
          gap: 14,
        }}>
          {rows.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => onOpen(s)}
              title={`${s.patient_name} · ${s.description}`}
              style={{
                display: "flex", flexDirection: "column", textAlign: "left", padding: 0,
                background: "var(--card)", border: "1px solid var(--border)",
                borderRadius: "var(--radius-lg)", overflow: "hidden", cursor: "pointer",
                fontFamily: "var(--font-sans)", boxShadow: "var(--shadow-sm)",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--brand-deep)")}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
            >
              <Thumbnail study={s} />
              <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
                <div className="truncate" style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)" }}>
                  {s.patient_name || "—"}
                </div>
                <div className="truncate" style={{ fontSize: 11, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                  {s.hospital_id || "sin HC"}
                </div>
                <div className="truncate" style={{ fontSize: 11, color: "var(--muted-foreground)" }}>
                  {s.description}
                </div>
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
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Studies({ onOpen }: { onOpen: (study: StudyCard) => void }) {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--canvas)" }}>
      <Topbar />
      <div style={{ flex: 1, overflowY: "auto" }}>
        <div style={{ maxWidth: 1320, margin: "0 auto", padding: "28px 24px 40px" }}>
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 22, fontWeight: 800, color: "var(--foreground)" }}>Estudios</div>
            <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 2 }}>
              Estudios cargados y archivados · haz clic en uno para abrirlo
            </div>
          </div>
          <StudyGallery onOpen={onOpen} />
        </div>
      </div>
    </div>
  );
}
