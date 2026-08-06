/* VolumeView — client-side vtk.js volume rendering of the DICOM volume.

   Fetches the downsampled raw uint8 volume from the backend (with X-Dims /
   X-Spacing headers), builds a vtkImageData and renders it with a selectable
   transfer-function preset. Lazy-loaded so vtk.js volume code only ships when
   this view is opened.

   The raw volume is rescaled to 0–255 (p1–p99) server-side, so the presets —
   ported in intent from rendering/transfer_functions.py — are expressed in the
   normalized 0–255 domain (band emphasis), not absolute HU. */

import { useEffect, useRef, useState } from "react";

import "@kitware/vtk.js/Rendering/Profiles/Volume";
import vtkFullScreenRenderWindow from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
import vtkVolume from "@kitware/vtk.js/Rendering/Core/Volume";
import vtkVolumeMapper from "@kitware/vtk.js/Rendering/Core/VolumeMapper";
import vtkImageData from "@kitware/vtk.js/Common/DataModel/ImageData";
import vtkDataArray from "@kitware/vtk.js/Common/Core/DataArray";
import vtkColorTransferFunction from "@kitware/vtk.js/Rendering/Core/ColorTransferFunction";
import vtkPiecewiseFunction from "@kitware/vtk.js/Common/DataModel/PiecewiseFunction";

import { api } from "../api/client";

interface Preset {
  color: [number, number, number, number][]; // [x, r, g, b] in 0–255
  opacity: [number, number][];                // [x, a]
  lighting: { ambient: number; diffuse: number; specular: number };
}

const PRESETS: Record<string, Preset> = {
  "CTA": {
    color: [[0, 0, 0, 0], [70, 0.5, 0.15, 0.1], [130, 0.9, 0.55, 0.35], [200, 1, 0.85, 0.7], [255, 1, 1, 1]],
    opacity: [[0, 0], [60, 0], [110, 0.18], [180, 0.5], [255, 0.85]],
    lighting: { ambient: 0.25, diffuse: 0.7, specular: 0.3 },
  },
  "Vasos CTA": {
    color: [[0, 0, 0, 0], [90, 0, 0, 0], [120, 1, 0.18, 0.08], [170, 1, 0.6, 0.3], [210, 0, 0, 0], [255, 0, 0, 0]],
    opacity: [[0, 0], [95, 0], [120, 0.75], [160, 0.95], [200, 0.6], [220, 0.08], [255, 0]],
    lighting: { ambient: 0.1, diffuse: 0.95, specular: 0.45 },
  },
  "Cerebro": {
    color: [[0, 0, 0, 0], [40, 0, 0, 0], [70, 0.42, 0.38, 0.38], [110, 0.6, 0.52, 0.5], [160, 0.85, 0.75, 0.65], [255, 1, 1, 1]],
    opacity: [[0, 0], [40, 0], [70, 0.08], [110, 0.16], [160, 0.35], [255, 0.7]],
    lighting: { ambient: 0.25, diffuse: 0.8, specular: 0.15 },
  },
  "Hemorragia": {
    color: [[0, 0, 0, 0], [120, 0, 0, 0], [150, 0.85, 0.65, 0.55], [175, 1, 0.35, 0.1], [200, 1, 0.9, 0.5], [255, 1, 1, 1]],
    opacity: [[0, 0], [130, 0], [150, 0.3], [175, 0.7], [200, 0.9], [255, 0.8]],
    lighting: { ambient: 0.2, diffuse: 0.85, specular: 0.2 },
  },
  "Hueso": {
    color: [[0, 0, 0, 0], [170, 0, 0, 0], [200, 0.88, 0.8, 0.6], [230, 1, 0.95, 0.82], [255, 1, 1, 1]],
    opacity: [[0, 0], [180, 0], [200, 0.3], [230, 0.8], [255, 0.95]],
    lighting: { ambient: 0.15, diffuse: 0.95, specular: 0.45 },
  },
  "Tejido blando": {
    color: [[0, 0, 0, 0], [50, 0, 0, 0], [90, 0.38, 0.22, 0.18], [130, 0.75, 0.55, 0.45], [170, 0.9, 0.78, 0.68], [210, 1, 0.9, 0.7], [240, 0, 0, 0]],
    opacity: [[0, 0], [50, 0], [90, 0.06], [130, 0.18], [170, 0.28], [210, 0.4], [235, 0.05], [255, 0]],
    lighting: { ambient: 0.25, diffuse: 0.85, specular: 0.1 },
  },
};
const PRESET_NAMES = Object.keys(PRESETS);

export function VolumeView({ sessionId }: { sessionId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [preset, setPreset] = useState<string>("CTA");

  // Keep the actor + render window so preset changes update the TF in place.
  const actorRef = useRef<ReturnType<typeof vtkVolume.newInstance> | null>(null);
  const rwRef = useRef<ReturnType<vtkFullScreenRenderWindow["getRenderWindow"]> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const fsrw = vtkFullScreenRenderWindow.newInstance({
      container,
      containerStyle: { width: "100%", height: "100%", position: "absolute", inset: "0" },
      background: [0, 0, 0],
    });
    const renderer = fsrw.getRenderer();
    const renderWindow = fsrw.getRenderWindow();
    rwRef.current = renderWindow;
    let cancelled = false;

    (async () => {
      try {
        const res = await fetch(api.volumeRawUrl(sessionId));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const dims = (res.headers.get("X-Dims") ?? "1,1,1").split(",").map(Number); // [z,y,x]
        const spacing = (res.headers.get("X-Spacing") ?? "1,1,1").split(",").map(Number); // [sz,sy,sx]
        const bytes = new Uint8Array(await res.arrayBuffer());
        if (cancelled) return;

        const imageData = vtkImageData.newInstance();
        imageData.setDimensions([dims[2], dims[1], dims[0]]); // vtk wants (x,y,z)
        imageData.setSpacing([spacing[2], spacing[1], spacing[0]]);
        const scalars = vtkDataArray.newInstance({ name: "scalars", numberOfComponents: 1, values: bytes });
        imageData.getPointData().setScalars(scalars);

        const mapper = vtkVolumeMapper.newInstance();
        mapper.setInputData(imageData);
        mapper.setSampleDistance(0.7);

        const actor = vtkVolume.newInstance();
        actor.setMapper(mapper);
        actorRef.current = actor;

        applyPreset(actor, PRESETS[preset]);
        actor.getProperty().setInterpolationTypeToLinear();
        actor.getProperty().setScalarOpacityUnitDistance(0, 2.0);

        renderer.addVolume(actor);
        renderer.resetCamera();
        renderer.getActiveCamera().elevation(-20);
        renderWindow.render();
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Error cargando el volumen");
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
      actorRef.current = null;
      rwRef.current = null;
      fsrw.delete();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Re-apply the transfer function when the preset changes (no scene rebuild).
  useEffect(() => {
    const actor = actorRef.current;
    const rw = rwRef.current;
    if (!actor || !rw) return;
    applyPreset(actor, PRESETS[preset]);
    rw.render();
  }, [preset]);

  return (
    <div ref={containerRef} style={{ position: "absolute", inset: 0 }}>
      {!loading && !error && (
        <div style={{ position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)", zIndex: 5, display: "flex", gap: 3, background: "rgba(20,24,28,0.72)", borderRadius: 999, padding: 3, flexWrap: "wrap", justifyContent: "center", maxWidth: "90%" }}>
          {PRESET_NAMES.map((name) => (
            <button
              key={name}
              onClick={() => setPreset(name)}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600, borderRadius: 999, border: "none", cursor: "pointer",
                background: preset === name ? "var(--brand-mist, #8B9BAA)" : "transparent",
                color: preset === name ? "#0e1114" : "rgba(200,210,220,0.8)",
              }}
            >
              {name}
            </button>
          ))}
        </div>
      )}
      {(loading || error) && (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(168,184,198,0.6)", fontSize: 13, pointerEvents: "none" }}>
          {error ? `Volumen no disponible: ${error}` : "Cargando volumen 3D…"}
        </div>
      )}
    </div>
  );
}

function applyPreset(actor: ReturnType<typeof vtkVolume.newInstance>, p: Preset) {
  const ctf = vtkColorTransferFunction.newInstance();
  for (const [x, r, g, b] of p.color) ctf.addRGBPoint(x, r, g, b);
  const otf = vtkPiecewiseFunction.newInstance();
  for (const [x, a] of p.opacity) otf.addPoint(x, a);
  const prop = actor.getProperty();
  prop.setRGBTransferFunction(0, ctf);
  prop.setScalarOpacity(0, otf);
  prop.setShade(true);
  prop.setAmbient(p.lighting.ambient);
  prop.setDiffuse(p.lighting.diffuse);
  prop.setSpecular(p.lighting.specular);
}
