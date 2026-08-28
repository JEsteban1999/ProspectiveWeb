/* The clip panel's job is to be defensible: every clip it offers has to show
   the measurement behind each verdict, and every clip it withholds has to say
   why. A ranked list of names and scores — which is what this replaced — is not
   something a surgeon can check. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const clipSelection = vi.fn();
const clipManufacture = vi.fn();

const buildNavarroClip = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    clipSelection: (...a: unknown[]) => clipSelection(...a),
    clipManufacture: (...a: unknown[]) => clipManufacture(...a),
    buildNavarroClip: (...a: unknown[]) => buildNavarroClip(...a),
  },
}));

import { ClipSelectionPanel } from "./ClipSelection";
import type {
  ClipCandidateOut,
  ClipSelectionResult,
  CustomJawOut,
  ManufactureSpecOut,
} from "../../api/types";

const candidate = (over: Partial<ClipCandidateOut> = {}): ClipCandidateOut => ({
  clip_id: "yasargil-recto-9mm",
  clip_name: "Yasargil Recto 9mm",
  manufacturer: "Yasargil/KS",
  shape: "Recto",
  blade_length_mm: 9,
  closing_force_g: 110,
  score: 88.4,
  verdict: "ok",
  headline: "Cumple todos los criterios",
  coverage_ratio: 1.5,
  safety_margin_mm: 3,
  availability: "stock",
  bend_angle_deg: 0,
  closing_force_min_g: 110,
  closing_force_max_g: 110,
  force_provisional: false,
  criteria: [
    { key: "coverage", label: "Cobertura", verdict: "ok", detail: "Cubre el cuello con 3.0 mm de margen (×1.50)" },
    { key: "force", label: "Fuerza de cierre", verdict: "ok", detail: "110 g dentro de la ventana 100–150 g" },
  ],
  fit: null,
  ...over,
});

const spec: ManufactureSpecOut = {
  blade_length_mm: 27, blade_width_mm: 3.5, blade_height_mm: 3,
  spring_length_mm: 24, shape: "Angulado 90°", angle_deg: 90,
  closing_force_g: 155, fenestration_mm: 0, neck_mm: 20,
  label: "Angulado 90° de 27.0 mm · 155 g",
  reasons: ["Ninguna hoja del catálogo cubre este cuello con margen suficiente"],
  confidence_notes: ["La fuerza de cierre (155 g) es el centro de la ventana heurística"],
  stl_url: null,
};

const result = (over: Partial<ClipSelectionResult> = {}): ClipSelectionResult => ({
  outcome: "stock",
  summary: "1 clip del inventario cumple todos los criterios para un cuello de 6.0 mm.",
  case: {
    neck_mm: 6, dome_height_mm: 8, max_diameter_mm: 11, ar: 1.33, dnr: 1.8,
    parent_artery_mm: 3.2, neck_source: "rim", neck_tilt_deg: 4,
    region: "ACM izquierda", laterality: "izquierda", aneurysm_type: "sacular",
  },
  recommended: [candidate()],
  rejected: [],
  manufacture: null,
  custom_jaw: null,
  caveats: ["Las preferencias clínicas son heurísticas de la literatura."],
  ...over,
});

beforeEach(() => {
  clipSelection.mockReset();
  clipManufacture.mockReset();
});

describe("showing the reasoning, not a score", () => {
  it("shows each criterion with the measurement behind it", async () => {
    clipSelection.mockResolvedValue(result());
    render(<ClipSelectionPanel sessionId="s1" />);

    expect(await screen.findByText("Yasargil Recto 9mm")).toBeInTheDocument();
    // The number, not just the word "Cobertura".
    expect(screen.getByText(/3\.0 mm de margen/)).toBeInTheDocument();
    expect(screen.getByText(/ventana 100–150 g/)).toBeInTheDocument();
  });

  it("leads with the verdict so it is read before the list", async () => {
    clipSelection.mockResolvedValue(result());
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findByText("Hay clip en inventario")).toBeInTheDocument();
  });

  it("reports how many approach angles clear the neighbouring vessels", async () => {
    // A clip clean at one angle out of six is usable but demands precision;
    // reporting only "no collision" hid that entirely.
    clipSelection.mockResolvedValue(result({
      recommended: [candidate({
        fit: {
          collision: false, n_contacts: 0, span_mm: 7.2, neck_coverage_pct: 100,
          clean_rolls: 1, n_rolls: 6, note: "Solo libra los vasos vecinos en 1 de 6 orientaciones",
        },
      })],
    }));
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findByText("1/6")).toBeInTheDocument();
  });
});

describe("when nothing in the inventory fits", () => {
  it("shows the manufacturing specification instead of an empty list", async () => {
    clipSelection.mockResolvedValue(result({
      outcome: "manufacture",
      summary: "Ningún clip del inventario sirve para un cuello de 20.0 mm.",
      recommended: [],
      manufacture: spec,
    }));
    render(<ClipSelectionPanel sessionId="s1" />);

    expect(await screen.findByText("Requiere fabricación")).toBeInTheDocument();
    expect(screen.getByText(/Clip a medida/)).toBeInTheDocument();
    expect(screen.getByText("27.0 mm")).toBeInTheDocument();
    expect(screen.getByText("155 g")).toBeInTheDocument();
  });

  it("states the assumptions a workshop still has to confirm", async () => {
    // A specification that hides its assumptions is worse than one that owns them.
    clipSelection.mockResolvedValue(result({
      outcome: "manufacture", recommended: [], manufacture: spec,
    }));
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findByText("A confirmar antes de fabricar")).toBeInTheDocument();
    expect(screen.getByText(/ventana heurística/)).toBeInTheDocument();
  });

  it("offers a custom alternative even when usable clips exist", async () => {
    // "Marginal" means everything on the shelf carries a caveat; the surgeon
    // should see the alternative rather than assume the top row is a clean fit.
    clipSelection.mockResolvedValue(result({
      outcome: "marginal",
      recommended: [candidate({ verdict: "warn" })],
      manufacture: spec,
    }));
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findByText("Utilizable con reservas")).toBeInTheDocument();
    expect(screen.getByText("Alternativa a medida")).toBeInTheDocument();
  });
});

describe("accountability for what was withheld", () => {
  it("lists the rejected clips with their reason", async () => {
    clipSelection.mockResolvedValue(result({
      rejected: [candidate({
        clip_id: "mini", clip_name: "Yasargil Mini recto", verdict: "fail", score: 0,
        headline: "Hoja de 5 mm insuficiente para un cuello de 6.0 mm",
        criteria: [{
          key: "coverage", label: "Cobertura", verdict: "fail",
          detail: "Hoja de 5 mm insuficiente para un cuello de 6.0 mm (hacen falta ≥ 7.0 mm)",
        }],
      })],
    }));
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findByText(/Por qué se descartaron otros/)).toBeInTheDocument();
  });

  it("surfaces what limits the recommendation", async () => {
    clipSelection.mockResolvedValue(result());
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findByText(/Qué limita esta recomendación/)).toBeInTheDocument();
  });

  it("opens the limitations by default when there is no measured neck", async () => {
    // With no neck there is nothing else on screen worth reading first.
    clipSelection.mockResolvedValue(result({
      outcome: "unmeasured",
      summary: "No hay una medida de cuello fiable.",
      recommended: [], caveats: ["Sin cuello medido no se puede recomendar un clip."],
    }));
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findByText("Falta medir el cuello")).toBeInTheDocument();
    expect(screen.getByText(/Sin cuello medido/)).toBeInTheDocument();
  });
});

describe("failures", () => {
  it("reports an error instead of rendering an empty panel", async () => {
    clipSelection.mockRejectedValue(new Error("backend caído"));
    render(<ClipSelectionPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByText(/backend caído/)).toBeInTheDocument());
  });
});


describe("made-to-order designs", () => {
  const navarro = candidate({
    clip_id: "navarro-t1-16", clip_name: "NAVARRO™ T1 Recto 16.0 mm",
    manufacturer: "NAVARRO™ (UNINAVARRA)", blade_length_mm: 16,
    availability: "made_to_order",
    closing_force_min_g: 120, closing_force_max_g: 200, force_provisional: true,
  });

  it("marks a clip that has to be manufactured for the case", async () => {
    // Not worse than stock — but it is not on a shelf, and the plan needs to
    // account for the lead time.
    clipSelection.mockResolvedValue(result({ recommended: [navarro] }));
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findAllByText("bajo pedido")).not.toHaveLength(0);
  });

  it("shows the force as a band, never as a midpoint", async () => {
    clipSelection.mockResolvedValue(result({ recommended: [navarro] }));
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findByText(/120–200 g/)).toBeInTheDocument();
    expect(screen.queryByText(/160 g/)).not.toBeInTheDocument();
    expect(screen.getByText(/sin caracterizar/)).toBeInTheDocument();
  });
});

describe("sizing a made-to-order clip", () => {
  const custom: CustomJawOut = {
    series: "T1", angle_deg: 0, jaw_mm: 27, nearest_drawn_mm: 22,
    label: "NAVARRO™ T1 Recto, mordaza 27.0 mm",
    reason: "Un cuello de 20.0 mm pide 27.0 mm de mordaza, fuera de las tallas dibujadas (7–22 mm).",
    mesh_url: null, stl_url: null,
  };

  it("offers the exact jaw the neck asks for", async () => {
    clipSelection.mockResolvedValue(result({ custom_jaw: custom }));
    render(<ClipSelectionPanel sessionId="s1" />);
    expect(await screen.findByText("NAVARRO™ T1 Recto, mordaza 27.0 mm")).toBeInTheDocument();
    expect(screen.getByText(/fuera de las tallas dibujadas/)).toBeInTheDocument();
  });

  it("lets the jaw be set by hand as well", async () => {
    // The suggestion is a starting point, not a verdict.
    clipSelection.mockResolvedValue(result({ custom_jaw: custom }));
    render(<ClipSelectionPanel sessionId="s1" />);
    const slider = await screen.findByRole("slider");
    fireEvent.change(slider, { target: { value: "18.5" } });
    // The design-system Slider keeps the value and its unit in separate spans,
    // so the readout is asserted the way that component renders it.
    expect(screen.getByText("18.5")).toBeInTheDocument();
    expect(slider).toHaveValue("18.5");
  });

  it("builds the clip at the chosen jaw", async () => {
    buildNavarroClip.mockResolvedValue({ ...custom, jaw_mm: 27, stl_url: "/x.stl?v=1",
      reason: "Mordaza estirada desde la talla dibujada de 22 mm." });
    clipSelection.mockResolvedValue(result({ custom_jaw: custom }));
    render(<ClipSelectionPanel sessionId="s1" />);
    fireEvent.click(await screen.findByRole("button", { name: /Generar clip/ }));
    await waitFor(() => expect(buildNavarroClip).toHaveBeenCalledWith("s1", 27, 0));
    expect(await screen.findByText(/estirada desde la talla dibujada/)).toBeInTheDocument();
  });

  it("says nothing about a custom size when a drawn one fits", async () => {
    clipSelection.mockResolvedValue(result({ custom_jaw: null }));
    render(<ClipSelectionPanel sessionId="s1" />);
    await screen.findByText("Yasargil Recto 9mm");
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });
});
