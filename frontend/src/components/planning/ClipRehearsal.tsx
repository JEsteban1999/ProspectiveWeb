/* Ensayo de colocación — ver cómo entra el clip y se cierra sobre el cuello.

   El clip colocado se muestra como un hecho consumado: geometría ya puesta.
   Ensayar la maniobra necesita los tres momentos que importan — bajar por el
   corredor con la mordaza abierta, llegar a horcajadas del cuello, y cerrar.

   El movimiento se aplica a las matrices de los actores, no al estado de React:
   una matriz por fotograma atravesando el árbol de componentes volvería a
   pintar el espacio de trabajo sesenta veces por segundo para mover tres
   piezas. El visor publica un manejador y aquí solo se escriben matrices.

   Es una visualización de la colocación prevista, no una simulación: nada aquí
   deforma tejido, modela el aplicador ni dice si el corredor es alcanzable. */

import { mat4, vec3 } from "gl-matrix";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { ClipAnimationResult, Position3D } from "../../api/types";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Card, ErrorNote, SectionLabel } from "../PanelHead";
import { Slider } from "../Slider";
import { usePlanning } from "../../store/planning";
import { neckPlacement } from "./DevicesPanel";

/** Seconds each phase lasts. Travel is the long one; the close is a snap. */
const TRAVEL_SEC = 2.4;
const CLOSE_SEC = 1.0;
const TOTAL_SEC = TRAVEL_SEC + CLOSE_SEC;

const v = (p: Position3D) => vec3.fromValues(p.x, p.y, p.z);
/** Ease so the run in settles rather than stopping dead. */
const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

/** The pose that `pose_transform` builds on the backend, as a matrix.
 *  Local +Z is turned onto the neck normal, then rolled, then translated. */
function poseMatrix(position: vec3, normal: vec3, rollDeg: number): mat4 {
  const n = vec3.normalize(vec3.create(), normal);
  const m = mat4.create();
  mat4.translate(m, m, position);
  const z = vec3.fromValues(0, 0, 1);
  const axis = vec3.cross(vec3.create(), z, n);
  const len = vec3.length(axis);
  if (len > 1e-9) {
    vec3.scale(axis, axis, 1 / len);
    mat4.rotate(m, m, Math.acos(Math.max(-1, Math.min(1, vec3.dot(z, n)))), axis);
  } else if (n[2] < 0) {
    mat4.rotate(m, m, Math.PI, vec3.fromValues(1, 0, 0));
  }
  mat4.rotateZ(m, m, (rollDeg * Math.PI) / 180);
  return m;
}

/** One blade's own turn about the hinge, in the clip's local frame. */
function bladeMatrix(hinge: vec3, axis: vec3, deg: number): mat4 {
  const m = mat4.create();
  mat4.translate(m, m, hinge);
  mat4.rotate(m, m, (deg * Math.PI) / 180, axis);
  mat4.translate(m, m, vec3.negate(vec3.create(), hinge));
  return m;
}

export function ClipRehearsal({ clipId, clipName }: { clipId: string; clipName: string }) {
  const { sessionId, morphometry, clipRehearsal, setClipRehearsal, clipParts,
          trajEntry, trajTarget } = usePlanning();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const raf = useRef<number | null>(null);
  const startedAt = useRef(0);

  /** Put the three parts where they belong at time t (0 = start, 1 = seated). */
  const poseAt = useCallback((t: number, anim: ClipAnimationResult) => {
    if (!clipParts) return;
    const travel = Math.min(1, (t * TOTAL_SEC) / TRAVEL_SEC);
    const close = Math.max(0, ((t * TOTAL_SEC) - TRAVEL_SEC) / CLOSE_SEC);

    // Along the corridor, arriving at the placed pose.
    const from = v(anim.approach_entry);
    const to = v(anim.position);
    const here = vec3.lerp(vec3.create(), from, to, easeOut(travel));
    const world = poseMatrix(here, vec3.fromValues(...(anim.normal as [number, number, number])), anim.rotation_deg);

    // Open on the way in, closed once seated.
    const open = anim.swing_deg * (1 - Math.min(1, close));
    const hinge = v(anim.hinge);
    const axis = vec3.normalize(vec3.create(), vec3.fromValues(...(anim.hinge_axis as [number, number, number])));

    clipParts.setMatrix("clip-body", Array.from(world));
    for (const [id, sign] of [["clip-blade-a", +1], ["clip-blade-b", -1]] as const) {
      const m = mat4.multiply(mat4.create(), world, bladeMatrix(hinge, axis, sign * open));
      clipParts.setMatrix(id, Array.from(m));
    }
    clipParts.render();
  }, [clipParts]);

  const stop = useCallback(() => {
    if (raf.current !== null) cancelAnimationFrame(raf.current);
    raf.current = null;
    setPlaying(false);
  }, []);

  // Drive the clock. The loop reads the animation from a ref-free closure and
  // writes matrices directly; React only learns the progress for the scrubber.
  const play = useCallback((anim: ClipAnimationResult, fromT = 0) => {
    stop();
    setPlaying(true);
    startedAt.current = performance.now() - fromT * TOTAL_SEC * 1000;
    const tick = () => {
      const t = Math.min(1, (performance.now() - startedAt.current) / (TOTAL_SEC * 1000));
      poseAt(t, anim);
      setProgress(t);
      if (t < 1) raf.current = requestAnimationFrame(tick);
      else { raf.current = null; setPlaying(false); }
    };
    raf.current = requestAnimationFrame(tick);
  }, [poseAt, stop]);

  const prepare = useCallback(async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const anim = await api.clipAnimation(sessionId, {
        session_id: sessionId,
        // The SAME pose the placement uses: a rehearsal that ended anywhere else
        // would show a manoeuvre the plan does not agree with.
        placements: [{ clip_id: clipId, ...neckPlacement(morphometry), rotation_deg: 0 }],
        trajectory_entry: trajEntry ? { x: trajEntry[0], y: trajEntry[1], z: trajEntry[2] } : null,
        trajectory_target: trajTarget ? { x: trajTarget[0], y: trajTarget[1], z: trajTarget[2] } : null,
      });
      setClipRehearsal(anim);
      setProgress(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo preparar el ensayo");
    } finally {
      setBusy(false);
    }
  }, [sessionId, clipId, morphometry, trajEntry, trajTarget, setClipRehearsal]);

  // Once the viewer has loaded the three parts, put them at the start.
  useEffect(() => {
    if (clipRehearsal && clipParts?.has("clip-body")) poseAt(0, clipRehearsal);
  }, [clipRehearsal, clipParts, poseAt]);

  // Leaving must not strand the scene mid-manoeuvre with a floating clip.
  useEffect(() => () => {
    if (raf.current !== null) cancelAnimationFrame(raf.current);
    setClipRehearsal(null);
  }, [setClipRehearsal]);

  if (!clipRehearsal) {
    return (
      <div>
        <SectionLabel>Ensayo de colocación</SectionLabel>
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", margin: "4px 0 8px", lineHeight: 1.5 }}>
          Muestra cómo entra {clipName} por el corredor de abordaje, abre la mordaza
          y cierra sobre el cuello.
        </div>
        <ErrorNote>{error}</ErrorNote>
        <Button size="sm" onClick={() => void prepare()} disabled={busy}>
          {busy ? "Preparando…" : "Preparar ensayo"}
        </Button>
      </div>
    );
  }

  const phase = progress * TOTAL_SEC < TRAVEL_SEC ? "Entrando por el corredor" : "Cerrando sobre el cuello";

  return (
    <div>
      <SectionLabel>Ensayo de colocación</SectionLabel>
      <Card style={{ marginTop: 6 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)", flex: 1, minWidth: 0 }}>
            {clipRehearsal.clip_name}
          </div>
          {clipRehearsal.approach_is_default && <Badge variant="subtle">corredor por defecto</Badge>}
        </div>

        <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 4, lineHeight: 1.5 }}>
          {phase} · apertura {clipRehearsal.swing_deg.toFixed(0)}° por hoja
          {clipRehearsal.approach_is_default && (
            <> · sin trayectoria marcada, entra por la normal del cuello desde el lado
              opuesto al domo. Marca Entrada y Diana para usar tu abordaje real.</>
          )}
        </div>

        <div style={{ marginTop: 10 }}>
          <Slider
            label="Momento de la maniobra" min={0} max={100} step={1}
            value={Math.round(progress * 100)} unit=" %"
            onChange={(pct) => { stop(); const t = pct / 100; setProgress(t); poseAt(t, clipRehearsal); }}
          />
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <Button size="sm" onClick={() => (playing ? stop() : play(clipRehearsal, progress >= 1 ? 0 : progress))}>
            {playing ? "Pausar" : progress >= 1 ? "Repetir" : "Reproducir"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { stop(); setProgress(0); poseAt(0, clipRehearsal); }}>
            Al inicio
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { stop(); setClipRehearsal(null); }}>
            Salir del ensayo
          </Button>
        </div>

        {/* La mecánica de apertura no está en el STL: hay que decirlo, no
            insinuar que el movimiento está especificado. */}
        {clipRehearsal.mechanics_assumed && (
          <div style={{ fontSize: 11, color: "var(--warning)", marginTop: 10, lineHeight: 1.5 }}>
            La apertura ({clipRehearsal.swing_deg.toFixed(0)}° por hoja) está supuesta a
            partir de cómo se comportan los clips comerciales: un STL cerrado no
            registra el mecanismo. El punto de giro sí se mide sobre la pieza.
          </div>
        )}
      </Card>
    </div>
  );
}
