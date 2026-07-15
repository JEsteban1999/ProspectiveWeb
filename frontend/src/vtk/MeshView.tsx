/* MeshView — render real .vtp meshes served by the backend with vtk.js.

   Loads the vessel tree plus any highlighted candidate dome, on the black
   clinical surface. Camera resets on first geometry; theme-independent
   (imaging surfaces are always black). */

import { useEffect, useRef } from "react";

import "@kitware/vtk.js/Rendering/Profiles/Geometry";
import vtkFullScreenRenderWindow from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
import vtkXMLPolyDataReader from "@kitware/vtk.js/IO/XML/XMLPolyDataReader";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import type { Vector3 } from "@kitware/vtk.js/types";

export interface MeshLayer {
  url: string;
  /** RGB 0–1 */
  color: Vector3;
  opacity?: number;
}

interface Handles {
  fsrw: vtkFullScreenRenderWindow;
  renderer: ReturnType<vtkFullScreenRenderWindow["getRenderer"]>;
  renderWindow: ReturnType<vtkFullScreenRenderWindow["getRenderWindow"]>;
  actors: vtkActor[];
}

export function MeshView({ layers }: { layers: MeshLayer[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handles = useRef<Handles | null>(null);
  // Serialise the layer set so the effect only re-runs when it truly changes.
  const key = layers.map((l) => `${l.url}|${l.color.join(",")}|${l.opacity ?? 1}`).join(";");

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
    handles.current = { fsrw, renderer, renderWindow, actors: [] };

    let cancelled = false;

    (async () => {
      let anyGeometry = false;
      for (const layer of layers) {
        try {
          const reader = vtkXMLPolyDataReader.newInstance();
          await reader.setUrl(layer.url, { binary: true });
          if (cancelled) return;
          const poly = reader.getOutputData();
          if (!poly || poly.getNumberOfPoints() === 0) continue;

          const mapper = vtkMapper.newInstance();
          mapper.setInputData(poly);
          mapper.setScalarVisibility(false); // solid color, not scalar-mapped

          const actor = vtkActor.newInstance();
          actor.setMapper(mapper);
          actor.getProperty().setColor(...layer.color);
          actor.getProperty().setOpacity(layer.opacity ?? 1);
          actor.getProperty().setInterpolationToPhong();

          renderer.addActor(actor);
          handles.current?.actors.push(actor);
          anyGeometry = true;
        } catch (err) {
          // A single failed layer must not blank the whole scene.
          console.warn("MeshView: failed to load", layer.url, err);
        }
      }

      if (cancelled) return;
      if (anyGeometry) {
        renderer.resetCamera();
        const cam = renderer.getActiveCamera();
        cam.elevation(-20);
        renderer.updateLightsGeometryToFollowCamera();
      }
      renderWindow.render();
    })();

    return () => {
      cancelled = true;
      const h = handles.current;
      if (h) {
        h.actors.forEach((a) => h.renderer.removeActor(a));
        h.fsrw.delete();
      }
      handles.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
