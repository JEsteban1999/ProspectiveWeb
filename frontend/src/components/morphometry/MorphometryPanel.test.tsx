/* The morphometry table reports two groups that fail independently.

   The bug this pins: with an open sac mesh the backend nulls the VOLUME group
   but keeps a perfectly good neck. The table gated every field on the combined
   `reliable` flag, so it showed «—» and «sin medir» for a neck of 7.0 mm and a
   DNR of 1.58 — while the 3D legend, which consulted no flag at all, went on
   annotating those same numbers over the scene. One screen, two answers. */

import { render, screen } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({
  api: {
    morphometry: vi.fn().mockRejectedValue(new Error("no auto-run in test")),
    morphometryNeckPlane: vi.fn(),
    longitudinal: vi.fn().mockRejectedValue(new Error("sin seguimiento")),
  },
}));

import { MorphometryPanel } from "./MorphometryPanel";
import { PlanningProvider, usePlanning } from "../../store/planning";
import type { MorphometryResult } from "../../api/types";

/** An open-cap measurement: volume group nulled, neck group measured. */
const openCap: MorphometryResult = {
  volume_mm3: 0, surface_area_mm2: 225.3, eq_sphere_diam_mm: 0,
  max_diameter_mm: 11.0, bbox_w_mm: 8, bbox_h_mm: 6,
  neck_mm: 7.0, dome_height_mm: 7.9,
  dnr: 1.58, ar: 1.13, bf: 1.58,
  compactness: 0, ui: 0, ei: 0, nsi: 0, sr: 0,
  rupture_risk_label: "Moderado",
  reliable: false, volume_valid: false, neck_valid: true,
  neck_source: "auto", neck_tilt_deg: 0, warning: null,
  centroid: { x: 0, y: 0, z: 0 }, principal_axis: [0, 0, 1],
  neck_origin: { x: 0, y: 0, z: 0 },
} as unknown as MorphometryResult;

function withMorphometry(m: MorphometryResult) {
  function Seed({ children }: { children: ReactNode }) {
    const { setSession, setMorphometry, sessionId } = usePlanning();
    useEffect(() => {
      if (!sessionId) { setSession("s1"); setMorphometry(m); }
    }, [sessionId, setSession, setMorphometry]);
    return <>{children}</>;
  }
  return render(
    <PlanningProvider>
      <Seed><MorphometryPanel /></Seed>
    </PlanningProvider>,
  );
}

describe("an open sac mesh with a valid neck", () => {
  it("still shows the neck it measured", async () => {
    withMorphometry(openCap);
    expect(await screen.findByText("7.0")).toBeInTheDocument();
  });

  it("still shows the dome height and the neck-derived ratios", async () => {
    withMorphometry(openCap);
    expect(await screen.findByText("7.9")).toBeInTheDocument();
    // DNR and BF share a definition (Ø máx / cuello), so 1.58 appears twice.
    expect(screen.getAllByText("1.58").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("1.13")).toBeInTheDocument();   // AR
  });

  it("hides the volume it could not measure", async () => {
    withMorphometry(openCap);
    await screen.findByText("7.0");
    // Surface area survives an open mesh; the enclosed volume does not.
    expect(screen.getByText("225.3")).toBeInTheDocument();
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
  });
});

describe("a degenerate neck on a closed sac", () => {
  const badNeck = {
    ...openCap, volume_mm3: 310.2, eq_sphere_diam_mm: 8.4, compactness: 0.72,
    neck_mm: 0, dome_height_mm: 0, dnr: 0, ar: 0, bf: 0,
    volume_valid: true, neck_valid: false,
  } as unknown as MorphometryResult;

  it("shows the volume and hides only the neck group", async () => {
    withMorphometry(badNeck);
    expect(await screen.findByText("310.2")).toBeInTheDocument();
    // The neck-derived rows must not report the zeros they were nulled to.
    expect(screen.getAllByText("sin medir").length).toBeGreaterThanOrEqual(3);
  });
});

describe("a fully valid measurement", () => {
  const good = {
    ...openCap, volume_mm3: 310.2, eq_sphere_diam_mm: 8.4, compactness: 0.72,
    reliable: true, volume_valid: true, neck_valid: true,
  } as unknown as MorphometryResult;

  it("reports both groups with no «sin medir» badges", async () => {
    withMorphometry(good);
    expect(await screen.findByText("7.0")).toBeInTheDocument();
    expect(screen.getByText("310.2")).toBeInTheDocument();
    expect(screen.queryByText("sin medir")).not.toBeInTheDocument();
  });
});
