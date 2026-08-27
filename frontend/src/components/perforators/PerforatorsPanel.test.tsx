/* The list used to give a distance and a severity with nothing saying WHICH
   vessel a row meant. Clicking a row has to publish that perforator so the 3D
   scene can mark it — that hand-off is what these pin down.

   Nothing is marked until asked for: a dozen markers appearing unbidden around
   the neck cover the geometry they sit on. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const perforators = vi.fn();
vi.mock("../../api/client", () => ({ api: { perforators: (...a: unknown[]) => perforators(...a) } }));

import { PerforatorsPanel } from "./PerforatorsPanel";
import { PlanningProvider, usePlanning } from "../../store/planning";
import type { PerforatorsResult } from "../../api/types";

const result: PerforatorsResult = {
  candidates: [
    {
      id: "prf-001", position_mm: { x: 1, y: 2, z: 3 }, radius_mm: 0.4,
      distance_to_neck_mm: 2.1, risk_level: 1, risk_label: "Alto", risk_color: "#ef4444",
    },
    {
      id: "prf-002", position_mm: { x: 4, y: 5, z: 6 }, radius_mm: 0.4,
      distance_to_neck_mm: 4.4, risk_level: 2, risk_label: "Medio", risk_color: "#eab308",
    },
  ],
  high_count: 1, medium_count: 1, low_count: 0,
  search_radius_mm: 8, zone_radii_mm: [3, 5, 8],
};

/** Renders the panel with a live session, exposing the store to assertions. */
function withSession(seen: { perforators?: unknown[]; visible?: string[]; zones?: unknown }) {
  function Probe({ children }: { children: ReactNode }) {
    const { sessionId, setSession, perforators: p, visiblePerforators, perforatorZones } = usePlanning();
    useEffect(() => { if (!sessionId) setSession("s1"); }, [sessionId, setSession]);
    seen.perforators = p;
    seen.visible = visiblePerforators;
    seen.zones = perforatorZones;
    return <>{children}</>;
  }
  return render(
    <PlanningProvider>
      <Probe><PerforatorsPanel /></Probe>
    </PlanningProvider>,
  );
}

beforeEach(() => {
  perforators.mockReset();
  perforators.mockResolvedValue(result);
});

describe("handing the perforators to the 3D scene", () => {
  it("publishes the candidates so the viewer can mark them", async () => {
    const seen: { perforators?: unknown[] } = {};
    withSession(seen);
    await waitFor(() => expect(seen.perforators).toHaveLength(2));
  });

  it("publishes the risk zones instead of letting the legend invent them", async () => {
    // The viewer legend read «3–6mm / >6mm» for a computation using 3/5/8.
    const seen: { zones?: unknown } = {};
    withSession(seen);
    await waitFor(() => expect(seen.zones).toEqual([3, 5, 8]));
  });

  it("states the real bands in the panel too", async () => {
    withSession({});
    expect(await screen.findByText(/alto <3 mm/)).toBeInTheDocument();
    expect(screen.getByText(/medio 3–5 mm/)).toBeInTheDocument();
  });
});

describe("showing and hiding", () => {
  it("shows none until the user asks", async () => {
    // The whole point of the default: the markers sit on the neck, so putting
    // them all on screen unbidden hides what the user came to look at.
    const seen: { perforators?: unknown[]; visible?: string[] } = {};
    withSession(seen);
    await waitFor(() => expect(seen.perforators).toHaveLength(2));
    expect(seen.visible).toEqual([]);
  });

  it("clicking a row shows that perforator", async () => {
    const seen: { visible?: string[] } = {};
    withSession(seen);
    fireEvent.click(await screen.findByRole("button", { name: /prf-002/ }));
    await waitFor(() => expect(seen.visible).toEqual(["prf-002"]));
  });

  it("clicking it again hides it", async () => {
    const seen: { visible?: string[] } = {};
    withSession(seen);
    const row = await screen.findByRole("button", { name: /prf-001/ });
    fireEvent.click(row);
    await waitFor(() => expect(seen.visible).toEqual(["prf-001"]));
    fireEvent.click(row);
    await waitFor(() => expect(seen.visible).toEqual([]));
  });

  it("several can be shown at once, to compare them", async () => {
    const seen: { visible?: string[] } = {};
    withSession(seen);
    fireEvent.click(await screen.findByRole("button", { name: /prf-001/ }));
    fireEvent.click(await screen.findByRole("button", { name: /prf-002/ }));
    await waitFor(() => expect(seen.visible).toEqual(["prf-001", "prf-002"]));
  });

  it("hiding one leaves the others on screen", async () => {
    const seen: { visible?: string[] } = {};
    withSession(seen);
    fireEvent.click(await screen.findByRole("button", { name: /prf-001/ }));
    fireEvent.click(await screen.findByRole("button", { name: /prf-002/ }));
    fireEvent.click(await screen.findByRole("button", { name: /prf-001/ }));
    await waitFor(() => expect(seen.visible).toEqual(["prf-002"]));
  });

  it("«Mostrar todas» switches every marker on, and off again", async () => {
    const seen: { visible?: string[] } = {};
    withSession(seen);
    const toggle = await screen.findByRole("button", { name: /Mostrar todas/ });
    fireEvent.click(toggle);
    await waitFor(() => expect(seen.visible).toEqual(["prf-001", "prf-002"]));
    fireEvent.click(await screen.findByRole("button", { name: /Ocultar todas/ }));
    await waitFor(() => expect(seen.visible).toEqual([]));
  });

  it("exposes the shown/hidden state to assistive technology", async () => {
    withSession({});
    const row = await screen.findByRole("button", { name: /prf-001/ });
    expect(row).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(row);
    await waitFor(() => expect(row).toHaveAttribute("aria-pressed", "true"));
  });
});

describe("when there is nothing to show", () => {
  it("says so instead of rendering an empty list", async () => {
    perforators.mockResolvedValue({ ...result, candidates: [], high_count: 0, medium_count: 0 });
    withSession({});
    expect(await screen.findByText(/Sin perforantes detectadas/)).toBeInTheDocument();
  });

  it("explains what to run first when the endpoint fails", async () => {
    perforators.mockRejectedValue(new Error("422"));
    withSession({});
    expect(await screen.findByText(/ejecuta primero la detección/)).toBeInTheDocument();
  });
});
