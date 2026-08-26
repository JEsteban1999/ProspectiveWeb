/* The planning store holds one patient's study while the pipeline runs, so what
   it forgets between studies is a patient-safety question, not a tidiness one. */

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ReactNode } from "react";
import { PlanningProvider, usePlanning } from "./planning";
import type { MorphometryResult, SegmentResult } from "../api/types";

const wrapper = ({ children }: { children: ReactNode }) => (
  <PlanningProvider>{children}</PlanningProvider>
);

const fakeMesh: SegmentResult = {
  mesh_url: "/data/x.vtp", voxel_fraction: 0.01, strategy: "dsa", is_dsa: true,
  vertices: 100, faces: 200, kept_fraction: 1, fragments_removed: 0,
  largest_removed_mm3: 0, downsample_factor: 1,
};

const fakeMorpho = { max_diameter_mm: 7.5 } as unknown as MorphometryResult;

describe("switching to another study", () => {
  it("forgets the previous patient's mesh, candidates and morphometry", () => {
    // Regression: the old mesh stayed on screen while the MPR already showed the
    // new study, so measurements of one patient sat next to images of another.
    const { result } = renderHook(() => usePlanning(), { wrapper });

    act(() => {
      result.current.setSession("sesion-1");
      result.current.setSegmentation(fakeMesh);
      result.current.setMorphometry(fakeMorpho);
      result.current.setSelectedCandidate(2);
    });
    expect(result.current.segmentation).not.toBeNull();

    act(() => result.current.reset());

    expect(result.current.sessionId).toBeNull();
    expect(result.current.segmentation).toBeNull();
    expect(result.current.morphometry).toBeNull();
    expect(result.current.candidates).toEqual([]);
  });

  it("also forgets which case and acquisition were being planned", () => {
    // Otherwise "Guardar progreso" on the next study would file it under the
    // previous patient's case.
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => {
      result.current.setCase(42, "Aneurisma ACM");
      result.current.setImagingStudyId(7);
    });
    act(() => result.current.reset());

    expect(result.current.caseId).toBeNull();
    expect(result.current.caseLabel).toBe("");
    expect(result.current.imagingStudyId).toBeNull();
  });
});

describe("re-running a step", () => {
  it("clears everything downstream of the segmentation", () => {
    // Detection, morphometry and the plan are all derived from the mesh; keeping
    // them after a re-segmentation would show numbers from a mesh that is gone.
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => {
      result.current.setMorphometry(fakeMorpho);
      result.current.setSelectedCandidate(3);
      result.current.setCenterlineMesh("/data/cl.vtp");
    });

    act(() => result.current.resetDownstream());

    expect(result.current.morphometry).toBeNull();
    expect(result.current.candidates).toEqual([]);
    expect(result.current.centerlineMesh).toBeNull();
  });

  it("keeps the patient and the session across a downstream reset", () => {
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => {
      result.current.setSession("sesion-viva");
      result.current.setCase(9, "Caso");
    });
    act(() => result.current.resetDownstream());

    expect(result.current.sessionId).toBe("sesion-viva");
    expect(result.current.caseId).toBe(9);
  });
});

describe("3D picking modes", () => {
  it("holds one pick mode at a time", () => {
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => result.current.setPickMode("cl_source"));
    expect(result.current.pickMode).toBe("cl_source");
    act(() => result.current.setPickMode(null));
    expect(result.current.pickMode).toBeNull();
  });
});

describe("placed devices", () => {
  it("keeps one slot per family so a clip and a stent coexist", () => {
    // The store used to hold a single device URL, so planning a stent after a
    // clip hid the clip in the viewer while the report still listed both.
    const { result } = renderHook(() => usePlanning(), { wrapper });

    act(() => {
      result.current.setDeviceMesh("clips", "/data/s/meshes/clips_placed.vtp");
      result.current.setDeviceMesh("stent", "/data/s/meshes/stent_deployed.vtp");
    });

    expect(result.current.deviceMeshes.clips).toContain("clips_placed");
    expect(result.current.deviceMeshes.stent).toContain("stent_deployed");
    expect(result.current.deviceMeshes.coils).toBeNull();
  });

  it("clears one family without touching the others", () => {
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => {
      result.current.setDeviceMesh("clips", "/data/a.vtp");
      result.current.setDeviceMesh("coils", "/data/b.vtp");
    });

    act(() => result.current.clearDeviceMeshes("clips"));

    expect(result.current.deviceMeshes.clips).toBeNull();
    expect(result.current.deviceMeshes.coils).toBe("/data/b.vtp");
  });

  it("clears every family when no kind is given", () => {
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => {
      result.current.setDeviceMesh("clips", "/data/a.vtp");
      result.current.setDeviceMesh("stent", "/data/b.vtp");
    });

    act(() => result.current.clearDeviceMeshes());

    expect(result.current.deviceMeshes).toEqual({ clips: null, coils: null, stent: null });
  });

  it("forgets the devices when the study is reset", () => {
    // Otherwise the next patient's scene opens with the previous plan's hardware.
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => result.current.setDeviceMesh("clips", "/data/a.vtp"));

    act(() => result.current.reset());

    expect(result.current.deviceMeshes.clips).toBeNull();
  });
});

describe("unsaved-changes flag", () => {
  it("starts clean and only turns dirty on a real result", () => {
    const { result } = renderHook(() => usePlanning(), { wrapper });
    expect(result.current.dirty).toBe(false);

    act(() => result.current.setSession("sesion-1"));
    expect(result.current.dirty).toBe(false); // opening a session is not a change

    act(() => result.current.setSegmentation(fakeMesh));
    expect(result.current.dirty).toBe(true);
  });

  it("goes clean again after a save", () => {
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => result.current.setMorphometry(fakeMorpho));
    expect(result.current.dirty).toBe(true);

    act(() => result.current.markSaved());
    expect(result.current.dirty).toBe(false);
  });

  it("lets a rehydrated session be marked clean", () => {
    // Resuming replays the saved results through the same setters a real edit
    // uses, so the store came back dirty and leaving immediately asked to
    // confirm before the user had touched anything. App calls markSaved() once
    // the rehydration finishes, which is what this guarantees is possible.
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => {
      result.current.setSegmentation(fakeMesh);
      result.current.setMorphometry(fakeMorpho);
      result.current.markSaved();
    });

    expect(result.current.dirty).toBe(false);
    expect(result.current.segmentation).not.toBeNull();
  });

  it("forgets unsaved changes when the study is reset", () => {
    const { result } = renderHook(() => usePlanning(), { wrapper });
    act(() => result.current.setSegmentation(fakeMesh));
    act(() => result.current.reset());
    expect(result.current.dirty).toBe(false);
  });
});
