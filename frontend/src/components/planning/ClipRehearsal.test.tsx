/* The rehearsal has to end where the plan puts the clip, and it has to admit
   which part of the motion is assumed. Those two are what make it usable for
   rehearsing rather than merely pretty. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const clipAnimation = vi.fn();
vi.mock("../../api/client", () => ({
  api: {
    clipAnimation: (...a: unknown[]) => clipAnimation(...a),
    clipRecommendations: vi.fn().mockResolvedValue([]),
    listCustomClips: vi.fn().mockResolvedValue([]),
  },
}));

import { ClipRehearsal } from "./ClipRehearsal";
import { PlanningProvider, usePlanning } from "../../store/planning";
import type { ClipAnimationResult, MorphometryResult } from "../../api/types";

const anim: ClipAnimationResult = {
  body_url: "/data/anim_body.vtp?v=1",
  blade_a_url: "/data/anim_blade_a.vtp?v=1",
  blade_b_url: "/data/anim_blade_b.vtp?v=1",
  hinge: { x: 0.4, y: 0, z: 0 },
  hinge_axis: [0, 0, 1],
  swing_deg: 21,
  mechanics_assumed: true,
  approach_entry: { x: 0, y: 0, z: -24 },
  approach_target: { x: 0, y: 0, z: 0 },
  approach_is_default: true,
  position: { x: 1, y: 2, z: 3 },
  normal: [0, 0, 1],
  rotation_deg: 0,
  clip_name: "NAVARRO™ T1 Recto 10.0 mm",
};

const morpho = {
  neck_origin: { x: 1, y: 2, z: 3 },
  principal_axis: [0, 0, 1],
  centroid: { x: 1, y: 2, z: 5 },
  dome_height_mm: 4,
} as unknown as MorphometryResult;

function withSession(seen: { rehearsal?: unknown } = {}) {
  function Seed({ children }: { children: ReactNode }) {
    const { sessionId, setSession, setMorphometry, clipRehearsal } = usePlanning();
    useEffect(() => {
      if (!sessionId) { setSession("s1"); setMorphometry(morpho); }
    }, [sessionId, setSession, setMorphometry]);
    seen.rehearsal = clipRehearsal;
    return <>{children}</>;
  }
  return render(
    <PlanningProvider>
      <Seed><ClipRehearsal clipId="navarro:t1:0:10.0" clipName="NAVARRO T1 10 mm" /></Seed>
    </PlanningProvider>,
  );
}

beforeEach(() => {
  clipAnimation.mockReset();
  clipAnimation.mockResolvedValue(anim);
});

describe("preparing the rehearsal", () => {
  it("offers it before anything is fetched", async () => {
    withSession();
    expect(await screen.findByRole("button", { name: /Preparar ensayo/ })).toBeInTheDocument();
  });

  it("asks the backend for the clip that is actually selected", async () => {
    withSession();
    fireEvent.click(await screen.findByRole("button", { name: /Preparar ensayo/ }));
    await waitFor(() => expect(clipAnimation).toHaveBeenCalled());
    const [sid, req] = clipAnimation.mock.calls[0] as [string, Record<string, unknown>];
    expect(sid).toBe("s1");
    const placements = req.placements as Array<Record<string, unknown>>;
    expect(placements[0].clip_id).toBe("navarro:t1:0:10.0");
  });

  it("ends the run where the plan puts the clip", async () => {
    // A rehearsal that finished anywhere else would show a manoeuvre the plan
    // does not agree with.
    withSession();
    fireEvent.click(await screen.findByRole("button", { name: /Preparar ensayo/ }));
    await waitFor(() => expect(clipAnimation).toHaveBeenCalled());
    const [, req] = clipAnimation.mock.calls[0] as [string, Record<string, unknown>];
    const placements = req.placements as Array<Record<string, unknown>>;
    expect(placements[0].position).toEqual(morpho.neck_origin);
  });

  it("hands the three moving parts to the viewer", async () => {
    const seen: { rehearsal?: unknown } = {};
    withSession(seen);
    fireEvent.click(await screen.findByRole("button", { name: /Preparar ensayo/ }));
    await waitFor(() => expect(seen.rehearsal).not.toBeNull());
  });
});

describe("what the rehearsal admits", () => {
  it("says the opening is assumed, not specified", async () => {
    // A closed STL records no mechanism; implying otherwise would be a claim
    // about a part nobody has characterised.
    withSession();
    fireEvent.click(await screen.findByRole("button", { name: /Preparar ensayo/ }));
    expect(await screen.findByText(/está supuesta/)).toBeInTheDocument();
    expect(screen.getByText(/no registra el mecanismo/)).toBeInTheDocument();
  });

  it("flags a corridor it invented for want of a marked one", async () => {
    withSession();
    fireEvent.click(await screen.findByRole("button", { name: /Preparar ensayo/ }));
    expect(await screen.findByText("corredor por defecto")).toBeInTheDocument();
    expect(screen.getByText(/Marca Entrada y Diana/)).toBeInTheDocument();
  });

  it("says nothing about a default when the corridor was marked", async () => {
    clipAnimation.mockResolvedValue({ ...anim, approach_is_default: false });
    withSession();
    fireEvent.click(await screen.findByRole("button", { name: /Preparar ensayo/ }));
    await screen.findByText(/apertura 21/);
    expect(screen.queryByText("corredor por defecto")).not.toBeInTheDocument();
  });
});

describe("driving it", () => {
  it("can be played and scrubbed", async () => {
    withSession();
    fireEvent.click(await screen.findByRole("button", { name: /Preparar ensayo/ }));
    expect(await screen.findByRole("button", { name: /Reproducir/ })).toBeInTheDocument();
    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "80" } });
    expect(slider).toHaveValue("80");
  });

  it("leaves the rehearsal and puts the scene back", async () => {
    // Otherwise the viewer keeps three loose parts where the placed clip was.
    const seen: { rehearsal?: unknown } = {};
    withSession(seen);
    fireEvent.click(await screen.findByRole("button", { name: /Preparar ensayo/ }));
    await waitFor(() => expect(seen.rehearsal).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /Salir del ensayo/ }));
    await waitFor(() => expect(seen.rehearsal).toBeNull());
  });

  it("reports a failure instead of pretending it prepared", async () => {
    clipAnimation.mockRejectedValue(new Error("malla ilegible"));
    withSession();
    fireEvent.click(await screen.findByRole("button", { name: /Preparar ensayo/ }));
    await waitFor(() => expect(screen.getByText(/malla ilegible/)).toBeInTheDocument());
  });
});
