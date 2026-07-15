/* SkullChain audit trail (Feature 5) — admin view of the tamper-evident log
   with an integrity check. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AuditBlock, AuditVerifyResult } from "../api/types";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { Topbar } from "../components/Topbar";
import { PanelHead, SectionLabel, Card, ErrorNote } from "../components/PanelHead";

export function AuditTrail({ onBack }: { onBack: () => void }) {
  const [blocks, setBlocks] = useState<AuditBlock[]>([]);
  const [verify, setVerify] = useState<AuditVerifyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.auditBlocks().then(setBlocks).catch((e) => setError(e instanceof Error ? e.message : "Error"));
  };
  useEffect(load, []);

  const runVerify = async () => {
    setBusy(true);
    setError(null);
    try {
      setVerify(await api.auditVerify());
      load(); // verify appends an INTEGRITY_CHECK block
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error verificando la cadena");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--canvas)" }}>
      <Topbar crumb="Auditoría · SkullChain">
        <Button variant="ghost" size="sm" onClick={onBack} leadingIcon={<Icon name="HOME" />}>Pacientes</Button>
      </Topbar>

      <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px", maxWidth: 1100, width: "100%", margin: "0 auto" }}>
        <PanelHead
          title="Registro de auditoría — SkullChain"
          desc="Cadena de bloques con hash SHA-256; alterar un bloque invalida todos los siguientes."
          right={
            <Button onClick={() => void runVerify()} disabled={busy} leadingIcon={<Icon name="SHIELD" />}>
              {busy ? "Verificando…" : "Verificar integridad"}
            </Button>
          }
        />

        {verify && (
          <Card style={{ padding: "14px 18px", marginBottom: 16, display: "flex", alignItems: "center", gap: 14, borderColor: verify.ok ? "var(--success)" : "var(--destructive)" }}>
            <Icon name={verify.ok ? "STATUS_OK" : "STATUS_WARN"} size={22} color={verify.ok ? "var(--success)" : "var(--destructive)"} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, color: verify.ok ? "var(--success)" : "var(--destructive)" }}>
                {verify.ok ? "Integridad verificada" : `¡${verify.broken.length} bloque(s) corrupto(s)!`}
              </div>
              <div style={{ fontSize: 12, color: "var(--muted-foreground)" }}>{verify.total_blocks} bloques en la cadena</div>
            </div>
            <a href="/api/audit/export" target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>Exportar TXT →</a>
          </Card>
        )}

        {verify && !verify.ok && verify.broken.map((b) => (
          <div key={b.id} style={{ fontSize: 12, color: "var(--destructive)", marginBottom: 4 }}>
            Bloque #{b.id} ({b.action}): {b.reason}
          </div>
        ))}

        <ErrorNote>{error}</ErrorNote>

        <SectionLabel style={{ marginTop: 8 }}>Bloques ({blocks.length})</SectionLabel>
        <div style={{ overflowX: "auto", marginTop: 8 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted-foreground)" }}>
                <th style={{ padding: "6px 8px" }}>#</th>
                <th style={{ padding: "6px 8px" }}>Fecha/Hora (UTC)</th>
                <th style={{ padding: "6px 8px" }}>Usuario</th>
                <th style={{ padding: "6px 8px" }}>Acción</th>
                <th style={{ padding: "6px 8px" }}>Hash bloque</th>
              </tr>
            </thead>
            <tbody>
              {blocks.map((b) => (
                <tr key={b.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "6px 8px", fontFamily: "var(--font-mono)" }}>{b.id}</td>
                  <td style={{ padding: "6px 8px", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{b.iso_ts}</td>
                  <td style={{ padding: "6px 8px" }}>{b.username || "—"}</td>
                  <td style={{ padding: "6px 8px" }}>
                    <Badge variant={b.action === "GENESIS" ? "outline" : b.action === "INTEGRITY_CHECK" ? "subtle" : "secondary"}>{b.action}</Badge>
                  </td>
                  <td style={{ padding: "6px 8px", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{b.block_hash.slice(0, 16)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
