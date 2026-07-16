/* VolumeView — client-side vtk.js volume rendering of the DICOM volume.

   Fetches the downsampled raw uint8 volume from the backend (with X-Dims /
   X-Spacing headers), builds a vtkImageData and renders it with a CT-style
   color + opacity transfer function. Lazy-loaded so vtk.js volume code only
   ships when this view is opened. */

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

export function VolumeView({ sessionId }: { sessionId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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

        // CT-angio style transfer function: dark low intensities, warm bone/vessel highs.
        const ctf = vtkColorTransferFunction.newInstance();
        ctf.addRGBPoint(0, 0.0, 0.0, 0.0);
        ctf.addRGBPoint(70, 0.5, 0.15, 0.1);
        ctf.addRGBPoint(130, 0.9, 0.55, 0.35);
        ctf.addRGBPoint(200, 1.0, 0.85, 0.7);
        ctf.addRGBPoint(255, 1.0, 1.0, 1.0);

        const otf = vtkPiecewiseFunction.newInstance();
        otf.addPoint(0, 0.0);
        otf.addPoint(60, 0.0);
        otf.addPoint(110, 0.18);
        otf.addPoint(180, 0.5);
        otf.addPoint(255, 0.85);

        const prop = actor.getProperty();
        prop.setRGBTransferFunction(0, ctf);
        prop.setScalarOpacity(0, otf);
        prop.setInterpolationTypeToLinear();
        prop.setShade(true);
        prop.setAmbient(0.25);
        prop.setDiffuse(0.7);
        prop.setSpecular(0.3);
        prop.setScalarOpacityUnitDistance(0, 2.0);

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
      fsrw.delete();
    };
  }, [sessionId]);

  return (
    <div ref={containerRef} style={{ position: "absolute", inset: 0 }}>
      {(loading || error) && (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(168,184,198,0.6)", fontSize: 13, pointerEvents: "none" }}>
          {error ? `Volumen no disponible: ${error}` : "Cargando volumen 3D…"}
        </div>
      )}
    </div>
  );
}
