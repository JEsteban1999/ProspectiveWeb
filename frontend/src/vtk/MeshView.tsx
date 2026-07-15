/* MeshView — render real .vtp meshes served by the backend with vtk.js.

   Loads the vessel tree plus any highlighted candidate dome / device / centreline,
   on the black clinical surface. Optionally supports point picking on the mesh
   surface (for centreline endpoints) and small sphere markers. */

import { useEffect, useRef } from "react";

import "@kitware/vtk.js/Rendering/Profiles/Geometry";
import vtkFullScreenRenderWindow from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
import vtkXMLPolyDataReader from "@kitware/vtk.js/IO/XML/XMLPolyDataReader";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkCellPicker from "@kitware/vtk.js/Rendering/Core/CellPicker";
import vtkSphereSource from "@kitware/vtk.js/Filters/Sources/SphereSource";
import type { Vector3 } from "@kitware/vtk.js/types";

export interface MeshLayer {
  url: string;
  /** RGB 0–1 */
  color: Vector3;
  opacity?: number;
}

export interface MeshMarker {
  pos: [number, number, number];
  color: Vector3;
}

interface Handles {
  fsrw: vtkFullScreenRenderWindow;
  renderer: ReturnType<vtkFullScreenRenderWindow["getRenderer"]>;
  renderWindow: ReturnType<vtkFullScreenRenderWindow["getRenderWindow"]>;
  actors: vtkActor[];
}

export function MeshView({
  layers,
  markers = [],
  pickMode = false,
  onPick,
}: {
  layers: MeshLayer[];
  markers?: MeshMarker[];
  /** When true, a left click on the mesh reports the world position via onPick. */
  pickMode?: boolean;
  onPick?: (xyz: [number, number, number]) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handles = useRef<Handles | null>(null);
  const markerActors = useRef<vtkActor[]>([]);

  // Latest pick config, read inside the vtk interactor callback without
  // forcing the scene to rebuild when the pick mode toggles.
  const pickModeRef = useRef(pickMode);
  const onPickRef = useRef(onPick);
  pickModeRef.current = pickMode;
  onPickRef.current = onPick;

  // Serialise layers + markers so each effect only re-runs when it must.
  const key = layers.map((l) => `${l.url}|${l.color.join(",")}|${l.opacity ?? 1}`).join(";");
  const markerKey = markers.map((m) => `${m.pos.join(",")}|${m.color.join(",")}`).join(";");

  // ── Scene: render window + mesh layers + surface picking ──────────────── #
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

    // Surface point picking — set up immediately so it survives async loads.
    const picker = vtkCellPicker.newInstance();
    picker.setTolerance(0.001);
    const interactor = fsrw.getInteractor();
    const pickSub = interactor.onLeftButtonPress((callData) => {
      if (!pickModeRef.current || !onPickRef.current) return;
      if (callData.pokedRenderer !== renderer) return;
      const pos = callData.position;
      picker.pick([pos.x, pos.y, 0], renderer);
      const hits = picker.getPickedPositions();
      if (hits && hits.length > 0) {
        const [x, y, z] = hits[0];
        onPickRef.current([x, y, z]);
      }
    });

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
      pickSub.unsubscribe();
      markerActors.current = [];
      const h = handles.current;
      if (h) {
        h.actors.forEach((a) => h.renderer.removeActor(a));
        h.fsrw.delete();
      }
      handles.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // ── Markers: managed incrementally so a pick never rebuilds the scene ─── #
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    markerActors.current.forEach((a) => h.renderer.removeActor(a));
    markerActors.current = [];
    for (const m of markers) {
      const sphere = vtkSphereSource.newInstance({ radius: 1.4, thetaResolution: 16, phiResolution: 16 });
      sphere.setCenter(m.pos[0], m.pos[1], m.pos[2]);
      const mapper = vtkMapper.newInstance();
      mapper.setInputConnection(sphere.getOutputPort());
      const actor = vtkActor.newInstance();
      actor.setMapper(mapper);
      actor.getProperty().setColor(...m.color);
      h.renderer.addActor(actor);
      markerActors.current.push(actor);
    }
    h.renderWindow.render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, markerKey]);

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
