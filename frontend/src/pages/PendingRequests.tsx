/* Solicitudes — admin-only review of pending account requests.
   Lists self-registrations with their professional profile and approve/reject. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PendingUser } from "../api/types";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { Topbar } from "../components/Topbar";
import { ErrorNote, Card } from "../components/PanelHead";

export function PendingRequests({ onBack }: { onBack: () => void }) {
  const [pending, setPending] = useState<PendingUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    api
      .listPending()
      .then(setPending)
      .catch((e) => setError(e instanceof Error ? e.message : "Error cargando solicitudes"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const act = async (id: number, action: "approve" | "reject") => {
    setBusyId(id);
    setError(null);
    try {
      if (action === "approve") await api.approvePending(id);
      else await api.rejectPending(id);
      setPending((p) => p.filter((u) => u.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error procesando la solicitud");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--canvas)" }}>
      <Topbar crumb="Administración / Solicitudes">
        <Button variant="ghost" size="sm" onClick={onBack} leadingIcon={<Icon name="HOME" />}>
          Pacientes
        </Button>
      </Topbar>

      <div style={{ flex: 1, overflowY: "auto", padding: "28px 32px 48px" }}>
        <div style={{ maxWidth: 900, margin: "0 auto" }} className="fade-rise">
          <div style={{ display: "flex", alignItems: "flex-end", marginBottom: 22 }}>
            <div>
              <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", color: "var(--foreground)" }}>
                Solicitudes de registro
              </div>
              <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 2 }}>
                {loading ? "Cargando…" : `${pending.length} pendiente${pending.length === 1 ? "" : "s"} de aprobación`}
              </div>
            </div>
            <div style={{ flex: 1 }} />
            <Button variant="outline" leadingIcon={<Icon name="REFRESH" />} onClick={load}>
              Actualizar
            </Button>
          </div>

          <ErrorNote>{error}</ErrorNote>

          {!loading && pending.length === 0 && (
            <Card style={{ padding: "28px 20px", textAlign: "center" }}>
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 8, color: "var(--muted-foreground)" }}>
                <Icon name="STATUS_OK" size={26} />
              </div>
              <div style={{ color: "var(--muted-foreground)", fontSize: 13 }}>
                No hay solicitudes pendientes.
              </div>
            </Card>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {pending.map((u) => (
              <Card key={u.id} style={{ padding: "18px 20px" }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
                  <span
                    style={{ width: 44, height: 44, borderRadius: "50%", flexShrink: 0, background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 15 }}
                  >
                    {(u.full_name || u.username).slice(0, 2).toUpperCase()}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 15, fontWeight: 700, color: "var(--foreground)" }}>{u.full_name || u.username}</span>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--muted-foreground)" }}>@{u.username}</span>
                      {u.specialty && <Badge variant="subtle">{u.specialty}</Badge>}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "4px 20px", marginTop: 10 }}>
                      {[
                        ["Cargo", u.position],
                        ["Hospital", u.hospital],
                        ["Universidad", u.university],
                        ["ID profesional", u.professional_id],
                        ["Cédula / ID", u.national_id],
                        ["ORCID", u.orcid],
                      ]
                        .filter(([, v]) => v)
                        .map(([k, v]) => (
                          <div key={k} style={{ fontSize: 12 }}>
                            <span style={{ color: "var(--muted-foreground)" }}>{k}: </span>
                            <span style={{ color: "var(--foreground)" }}>{v}</span>
                          </div>
                        ))}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 8, fontFamily: "var(--font-mono)" }}>
                      Solicitado: {new Date(u.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, flexShrink: 0 }}>
                    <Button
                      size="sm"
                      onClick={() => void act(u.id, "approve")}
                      disabled={busyId === u.id}
                      leadingIcon={<Icon name="STATUS_OK" size={13} />}
                    >
                      Aprobar
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => void act(u.id, "reject")}
                      disabled={busyId === u.id}
                      leadingIcon={<Icon name="STATUS_FAIL" size={13} />}
                    >
                      Rechazar
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
