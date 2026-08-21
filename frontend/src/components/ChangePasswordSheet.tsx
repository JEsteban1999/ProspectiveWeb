/* Cambio de contraseña propia — pide la actual, así una sesión robada no deja
   al dueño fuera de su cuenta. Paridad con auth_manager.change_password del
   escritorio, que la web no tenía. */

import { useState } from "react";
import { api } from "../api/client";
import { Button } from "./Button";
import { Icon } from "./Icon";
import { Input } from "./Input";
import { ErrorNote } from "./PanelHead";
import { Sheet } from "./Sheet";

const MIN_LEN = 8;

export function ChangePasswordSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const reset = () => {
    setCurrent(""); setNext(""); setRepeat("");
    setError(null); setDone(false); setBusy(false);
  };

  const close = () => { reset(); onClose(); };

  // Checked here as well as on the server so the user sees the problem before
  // sending their current password over the wire.
  const tooShort = next.length > 0 && next.length < MIN_LEN;
  const mismatch = repeat.length > 0 && next !== repeat;
  const sameAsOld = next.length > 0 && next === current;
  const canSubmit =
    !busy && current.length > 0 && next.length >= MIN_LEN && next === repeat && !sameAsOld;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await api.changePassword(current, next);
      setDone(true);
      setTimeout(close, 1600);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cambiar la contraseña");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={close} title="Cambiar contraseña" width={400}>
      {done ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--success)", fontSize: 13, fontWeight: 600 }}>
          <Icon name="STATUS_OK" size={16} color="var(--success)" />
          Contraseña actualizada.
        </div>
      ) : (
        <>
          <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 14, lineHeight: 1.5 }}>
            Tu sesión seguirá abierta: el token va firmado sobre tu usuario, no sobre
            la contraseña.
          </div>

          <Input
            label="Contraseña actual"
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
          />
          <div style={{ height: 10 }} />
          <Input
            label={`Nueva contraseña (mín. ${MIN_LEN})`}
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
          />
          <div style={{ height: 10 }} />
          <Input
            label="Repite la nueva contraseña"
            type="password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void submit(); }}
            autoComplete="new-password"
          />

          {(tooShort || mismatch || sameAsOld) && (
            <div style={{ fontSize: 11, color: "var(--warning)", marginTop: 8, lineHeight: 1.45 }}>
              {tooShort && `La nueva contraseña debe tener al menos ${MIN_LEN} caracteres.`}
              {!tooShort && mismatch && "Las dos contraseñas nuevas no coinciden."}
              {!tooShort && !mismatch && sameAsOld && "La nueva contraseña debe ser distinta de la actual."}
            </div>
          )}

          <ErrorNote>{error}</ErrorNote>

          <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
            <Button variant="ghost" onClick={close} style={{ flex: 1 }}>Cancelar</Button>
            <Button
              onClick={() => void submit()}
              disabled={!canSubmit}
              style={{ flex: 1 }}
              leadingIcon={<Icon name="LOCK" size={14} />}
            >
              {busy ? "Guardando…" : "Cambiar"}
            </Button>
          </div>
        </>
      )}
    </Sheet>
  );
}
