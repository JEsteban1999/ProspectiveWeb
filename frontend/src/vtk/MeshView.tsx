/* MeshView — render real .vtp meshes served by the backend with vtk.js.

   Loads the vessel tree plus any highlighted candidate dome / device / centreline,
   on the black clinical surface. Optionally supports point picking on the mesh
   surface (for centreline endpoints) and small sphere markers. */

import { useEffect, useRef, useState } from "react";
import { markerRadiusMm, RULER_BEAD_RATIO, RULER_TUBE_RATIO } from "./markerSize";

import "@kitware/vtk.js/Rendering/Profiles/Geometry";
import vtkFullScreenRenderWindow from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
import vtkXMLPolyDataReader from "@kitware/vtk.js/IO/XML/XMLPolyDataReader";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkCellPicker from "@kitware/vtk.js/Rendering/Core/CellPicker";
import vtkSphereSource from "@kitware/vtk.js/Filters/Sources/SphereSource";
import vtkCubeSource from "@kitware/vtk.js/Filters/Sources/CubeSource";
import vtkLineSource from "@kitware/vtk.js/Filters/Sources/LineSource";
import vtkTubeFilter from "@kitware/vtk.js/Filters/General/TubeFilter";
import type { Vector3 } from "@kitware/vtk.js/types";

export interface MeshLayer {
  url: string;
  /** RGB 0–1 */
  color: Vector3;
  opacity?: number;
  /** Names this layer's actor so it can be moved after loading — how the clip
   *  rehearsal animates the body and the two blades without refetching. */
  id?: string;
}

/** Imperative handle for moving named layers, published while the scene lives.
 *  Animation runs through this instead of React state: a matrix per frame
 *  through the component tree would re-render the whole workspace 60 times a
 *  second to move three actors. */
export interface PartsHandle {
  setMatrix(id: string, matrix: number[] | null): void;
  render(): void;
  has(id: string): boolean;
}

export interface MeshMarker {
  pos: [number, number, number];
  color: Vector3;
  /** Multiplier on the shared marker radius. Lets one marker in a set stand out
   *  (a selected perforator) without breaking the scale everything else uses. */
  scale?: number;
}

export interface MeshLine {
  a: [number, number, number];
  b: [number, number, number];
  color: Vector3;
}

/** Standard viewpoints, named for the MPR planes the rest of the app uses.
 *  Mesh coordinates are voxel·spacing with axes (x = columnas, y = filas,
 *  z = cortes), so +z is the superior–inferior axis — the same convention the
 *  MPR strip flips for coronal and sagittal. */
export type CameraView =
  | "fit" | "axial" | "axial_inf" | "coronal" | "coronal_post" | "sagital" | "sagital_izq";

const CAMERA_VIEWS: Record<Exclude<CameraView, "fit">, [[number, number, number], [number, number, number]]> = {
  axial:        [[0, 0,  1], [0, -1, 0]],   // desde superior
  axial_inf:    [[0, 0, -1], [0, -1, 0]],   // desde inferior
  coronal:      [[0, -1, 0], [0, 0,  1]],   // desde anterior
  coronal_post: [[0,  1, 0], [0, 0,  1]],   // desde posterior
  sagital:      [[1,  0, 0], [0, 0,  1]],   // lateral
  sagital_izq:  [[-1, 0, 0], [0, 0,  1]],   // lateral opuesto
};

export interface CropPreview {
  center: [number, number, number];
  radius: number;               // sphere radius / box half-side (mm)
  shape: "sphere" | "box";
  invert: boolean;              // true = the ROI is REMOVED (red), else kept (cyan)
}

interface Handles {
  fsrw: vtkFullScreenRenderWindow;
  renderer: ReturnType<vtkFullScreenRenderWindow["getRenderer"]>;
  renderWindow: ReturnType<vtkFullScreenRenderWindow["getRenderWindow"]>;
  actors: vtkActor[];
  actorByUrl: Map<string, vtkActor>;   // for incremental opacity/color updates
}

export function MeshView({
  layers,
  markers = [],
  lines = [],
  cropPreview = null,
  referenceDiameterMm = null,
  pickMode = false,
  onPick,
  onPickMiss,
  focusUrl,
  registerCapture,
  registerCamera,
  registerParts,
  preserveCamera = false,
}: {
  layers: MeshLayer[];
  markers?: MeshMarker[];
  lines?: MeshLine[];
  /** Translucent sphere/box preview of the crop ROI (null to hide). */
  cropPreview?: CropPreview | null;
  /** Diameter of the structure being marked (mm). Markers scale to it so they
   *  stay smaller than the vessel or dome they sit on. */
  referenceDiameterMm?: number | null;
  /** When true, a left click on the mesh reports the world position via onPick. */
  pickMode?: boolean;
  onPick?: (xyz: [number, number, number]) => void;
  /** Called when a pick click lands on empty space (no surface hit). */
  onPickMiss?: () => void;
  /** URL of a layer to frame the camera on and highlight (e.g. the selected
   *  aneurysm candidate). The view zooms to its region — with local context —
   *  and the layer is lit to stand out. */
  focusUrl?: string;
  /** Registers a function that captures the live viewport as a PNG data URL
   *  (used to embed the 3D scene in the PDF report). Called with null on unmount. */
  registerCapture?: (fn: (() => Promise<string | null>) | null) => void;
  /** Registers a camera controller so the viewer can offer standard views and a
   *  «fit to scene». Called with null on unmount. */
  registerCamera?: (fn: ((view: CameraView) => void) | null) => void;
  /** Publishes a handle for moving named layers, for the clip rehearsal. */
  registerParts?: (h: PartsHandle | null) => void;
  /** Keep the camera across scene rebuilds — used by the live threshold preview so
   *  the view doesn't jump back to the default framing on every mesh update. */
  preserveCamera?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handles = useRef<Handles | null>(null);
  // Set once the geometry is on screen; markers re-render at the new size.
  const [sceneDiagonal, setSceneDiagonal] = useState(0);
  const markerActors = useRef<vtkActor[]>([]);
  // Actors that carry a layer id, so the rehearsal can move them by name.
  const namedActors = useRef<Map<string, vtkActor>>(new Map());
  const cropActor = useRef<vtkActor | null>(null);
  const registerCaptureRef = useRef(registerCapture);
  registerCaptureRef.current = registerCapture;
  const registerCameraRef = useRef(registerCamera);
  registerCameraRef.current = registerCamera;
  const registerPartsRef = useRef(registerParts);
  registerPartsRef.current = registerParts;
  // Camera params kept across scene rebuilds (for the live preview).
  const savedCamera = useRef<{ position: number[]; focalPoint: number[]; viewUp: number[]; parallelScale: number } | null>(null);
  const preserveCameraRef = useRef(preserveCamera);
  preserveCameraRef.current = preserveCamera;

  // Latest pick config, read inside the vtk interactor callback without
  // forcing the scene to rebuild when the pick mode toggles.
  const pickModeRef = useRef(pickMode);
  const onPickRef = useRef(onPick);
  const onPickMissRef = useRef(onPickMiss);
  pickModeRef.current = pickMode;
  onPickRef.current = onPick;
  onPickMissRef.current = onPickMiss;

  // Serialise layers + overlays so each effect only re-runs when it must. The
  // scene rebuilds ONLY when the geometry (URLs) or focus changes — NOT on an
  // opacity/color tweak (those update the existing actors incrementally). This
  // keeps a heavy mesh from reloading (and flashing black) when the pick mode
  // just dims it.
  const key = layers.map((l) => l.url).join(";") + `#${focusUrl ?? ""}`;
  const appearanceKey = layers.map((l) => `${l.url}|${l.color.join(",")}|${l.opacity ?? 1}`).join(";");
  const markerKey = markers.map((m) => `${m.pos.join(",")}|${m.color.join(",")}|${m.scale ?? 1}`).join(";");
  const lineKey = lines.map((l) => `${l.a.join(",")}-${l.b.join(",")}|${l.color.join(",")}`).join(";");
  const cropKey = cropPreview
    ? `${cropPreview.center.join(",")}|${cropPreview.radius}|${cropPreview.shape}|${cropPreview.invert}`
    : "";

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
    handles.current = { fsrw, renderer, renderWindow, actors: [], actorByUrl: new Map() };

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
      } else {
        // Clicked empty space: without feedback the tool looks broken ("I click
        // and nothing happens"), so tell the caller the pick missed the surface.
        onPickMissRef.current?.();
      }
    });

    (async () => {
      let anyGeometry = false;
      let focusBounds: number[] | null = null;
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
          if (layer.id) namedActors.current.set(layer.id, actor);
          const prop = actor.getProperty();
          prop.setColor(...layer.color);
          prop.setOpacity(layer.opacity ?? 1);
          prop.setInterpolationToPhong();

          // Highlight the focused layer (selected candidate): lift it off the
          // dimmed tree with a self-lit glow and a crisp specular sheen.
          if (focusUrl && layer.url === focusUrl) {
            focusBounds = poly.getBounds();
            prop.setAmbient(0.5);
            prop.setDiffuse(0.7);
            prop.setSpecular(0.4);
            prop.setSpecularPower(30);
            prop.setOpacity(1);
          }

          renderer.addActor(actor);
          handles.current?.actors.push(actor);
          handles.current?.actorByUrl.set(layer.url, actor);
          anyGeometry = true;
        } catch (err) {
          // A single failed layer must not blank the whole scene.
          console.warn("MeshView: failed to load", layer.url, err);
        }
      }
      if (cancelled) return;
      if (anyGeometry) {
        // Scene scale for the markers: the union of everything on screen.
        const b = renderer.computeVisiblePropBounds();
        if (b && isFinite(b[0]) && b[1] >= b[0]) {
          const diag = Math.hypot(b[1] - b[0], b[3] - b[2], b[5] - b[4]);
          if (diag > 0) setSceneDiagonal(diag);
        }
        const cam = renderer.getActiveCamera();
        if (preserveCameraRef.current && savedCamera.current) {
          // Live preview refresh: keep the user's current viewpoint.
          const s = savedCamera.current;
          cam.setPosition(s.position[0], s.position[1], s.position[2]);
          cam.setFocalPoint(s.focalPoint[0], s.focalPoint[1], s.focalPoint[2]);
          cam.setViewUp(s.viewUp[0], s.viewUp[1], s.viewUp[2]);
          cam.setParallelScale(s.parallelScale);
          renderer.resetCameraClippingRange();
        } else if (focusBounds && isFinite(focusBounds[0]) && focusBounds[1] >= focusBounds[0]) {
          // Frame the candidate with local context: expand its bounds to a cube
          // around its centre so the surrounding vessel stays visible (needed to
          // place the neck plane), then fit the camera to that.
          const cx = (focusBounds[0] + focusBounds[1]) / 2;
          const cy = (focusBounds[2] + focusBounds[3]) / 2;
          const cz = (focusBounds[4] + focusBounds[5]) / 2;
          const half = Math.max(
            focusBounds[1] - focusBounds[0],
            focusBounds[3] - focusBounds[2],
            focusBounds[5] - focusBounds[4],
          ) * 1.4;
          const r = Math.max(half, 16);
          renderer.resetCamera([cx - r, cx + r, cy - r, cy + r, cz - r, cz + r]);
          cam.elevation(-20);
        } else {
          renderer.resetCamera();
          cam.elevation(-20);
        }
        renderer.updateLightsGeometryToFollowCamera();
      }
      renderWindow.render();
    })();

    // Expose a viewport-capture function (PNG data URL) for the PDF report.
    const capture = async (): Promise<string | null> => {
      const h = handles.current;
      if (!h) return null;
      try {
        const glrw = (h.fsrw as unknown as { getApiSpecificRenderWindow?: () => { captureNextImage: (fmt: string) => Promise<string> } }).getApiSpecificRenderWindow?.();
        if (!glrw) return null;
        const promise = glrw.captureNextImage("image/png");
        h.renderWindow.render();
        return await promise;
      } catch (err) {
        console.warn("MeshView capture failed", err);
        return null;
      }
    };
    registerCaptureRef.current?.(capture);

    // Standard viewpoints. resetCamera() preserves the view direction and up
    // vector, so pointing the camera and refitting is all it takes. Without this
    // the only way back from a lost orientation was to change step and return.
    const setView = (view: CameraView) => {
      const h = handles.current;
      if (!h) return;
      const cam = h.renderer.getActiveCamera();
      if (view !== "fit") {
        const [dir, up] = CAMERA_VIEWS[view];
        cam.setFocalPoint(0, 0, 0);
        cam.setPosition(dir[0], dir[1], dir[2]);
        cam.setViewUp(up[0], up[1], up[2]);
      }
      h.renderer.resetCamera();
      h.renderer.resetCameraClippingRange();
      h.renderer.updateLightsGeometryToFollowCamera();
      h.renderWindow.render();
    };
    registerCameraRef.current?.(setView);

    registerPartsRef.current?.({
      has: (id) => namedActors.current.has(id),
      setMatrix: (id, matrix) => {
        const a = namedActors.current.get(id);
        if (!a) return;
        // null puts the part back where the file has it.
        a.setUserMatrix(matrix as never);
      },
      render: () => handles.current?.renderWindow.render(),
    });

    return () => {
      cancelled = true;
      pickSub.unsubscribe();
      registerCaptureRef.current?.(null);
      registerCameraRef.current?.(null);
      registerPartsRef.current?.(null);
      namedActors.current.clear();
      markerActors.current = [];
      const h = handles.current;
      if (h) {
        // Remember the camera so a preview refresh can restore the viewpoint.
        if (preserveCameraRef.current) {
          try {
            const cam = h.renderer.getActiveCamera();
            savedCamera.current = {
              position: [...cam.getPosition()],
              focalPoint: [...cam.getFocalPoint()],
              viewUp: [...cam.getViewUp()],
              parallelScale: cam.getParallelScale(),
            };
          } catch { /* ignore */ }
        } else {
          savedCamera.current = null;
        }
        h.actors.forEach((a) => h.renderer.removeActor(a));
        // Unbind the interactor's DOM listeners BEFORE delete(). vtk.js does not
        // release them on delete(), so a rebuilt scene (new step / mesh) would
        // leave a "zombie" interactor firing pointer events on a torn-down
        // container → `getBoundingClientRect` of undefined, spamming the console
        // and leaking listeners over a long session.
        try { interactor.unbindEvents(); } catch { /* older vtk.js */ }
        h.fsrw.delete();
      }
      handles.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // ── Appearance (opacity/color): update actors in place, never rebuild the ──
  //    scene — so dimming a heavy mesh (e.g. entering a pick mode) is instant. ─ #
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    let changed = false;
    for (const l of layers) {
      const actor = h.actorByUrl.get(l.url);
      if (!actor) continue;
      const prop = actor.getProperty();
      if (!(focusUrl && l.url === focusUrl)) {   // the focused layer keeps its highlight
        prop.setColor(...l.color);
        prop.setOpacity(l.opacity ?? 1);
      }
      changed = true;
    }
    if (changed) h.renderWindow.render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appearanceKey]);

  // ── Overlays (markers + ruler lines): incremental so a pick never rebuilds ─ #
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    markerActors.current.forEach((a) => h.renderer.removeActor(a));
    markerActors.current = [];

    const rMarker = markerRadiusMm(referenceDiameterMm, sceneDiagonal);

    for (const m of markers) {
      const sphere = vtkSphereSource.newInstance({ radius: rMarker * (m.scale ?? 1), thetaResolution: 16, phiResolution: 16 });
      sphere.setCenter(m.pos[0], m.pos[1], m.pos[2]);
      const mapper = vtkMapper.newInstance();
      mapper.setInputConnection(sphere.getOutputPort());
      const actor = vtkActor.newInstance();
      actor.setMapper(mapper);
      actor.getProperty().setColor(...m.color);
      h.renderer.addActor(actor);
      markerActors.current.push(actor);
    }

    for (const l of lines) {
      const lineSrc = vtkLineSource.newInstance({ point1: l.a, point2: l.b, resolution: 1 });
      const tube = vtkTubeFilter.newInstance({
        radius: rMarker * RULER_TUBE_RATIO, numberOfSides: 10, capping: true,
      });
      tube.setInputConnection(lineSrc.getOutputPort());
      const mapper = vtkMapper.newInstance();
      mapper.setInputConnection(tube.getOutputPort());
      const actor = vtkActor.newInstance();
      actor.setMapper(mapper);
      actor.getProperty().setColor(...l.color);
      h.renderer.addActor(actor);
      markerActors.current.push(actor);
      // Endpoint beads for the ruler.
      for (const p of [l.a, l.b]) {
        const bead = vtkSphereSource.newInstance({
          radius: rMarker * RULER_BEAD_RATIO, thetaResolution: 12, phiResolution: 12,
        });
        bead.setCenter(p[0], p[1], p[2]);
        const bm = vtkMapper.newInstance();
        bm.setInputConnection(bead.getOutputPort());
        const ba = vtkActor.newInstance();
        ba.setMapper(bm);
        ba.getProperty().setColor(...l.color);
        h.renderer.addActor(ba);
        markerActors.current.push(ba);
      }
    }
    h.renderWindow.render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, markerKey, lineKey, sceneDiagonal, referenceDiameterMm]);

  // ── Crop ROI preview: a translucent sphere/box so the crop is not blind ──── #
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    if (cropActor.current) { h.renderer.removeActor(cropActor.current); cropActor.current = null; }

    if (cropPreview && cropPreview.radius > 0) {
      const { center, radius, shape, invert } = cropPreview;
      const src = shape === "sphere"
        ? vtkSphereSource.newInstance({ center, radius, thetaResolution: 32, phiResolution: 32 })
        : vtkCubeSource.newInstance({ center, xLength: radius * 2, yLength: radius * 2, zLength: radius * 2 });
      const mapper = vtkMapper.newInstance();
      mapper.setInputConnection(src.getOutputPort());
      const actor = vtkActor.newInstance();
      actor.setMapper(mapper);
      const prop = actor.getProperty();
      // Red = the ROI is removed; cyan = the ROI is kept.
      prop.setColor(invert ? 0.95 : 0.25, invert ? 0.30 : 0.85, invert ? 0.30 : 0.95);
      prop.setOpacity(0.22);
      prop.setEdgeVisibility(true);
      prop.setEdgeColor(invert ? 0.98 : 0.4, invert ? 0.5 : 0.95, invert ? 0.5 : 1.0);
      prop.setLineWidth(1);
      actor.setPickable(false);   // never intercept surface picks
      h.renderer.addActor(actor);
      cropActor.current = actor;
    }
    h.renderWindow.render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, cropKey]);

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
