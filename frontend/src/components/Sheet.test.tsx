/* A drawer that renders inside a glass surface silently collapses. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Sheet } from "./Sheet";

describe("Sheet", () => {
  it("escapes an ancestor that captures fixed positioning", () => {
    // Regression: the topbar has backdrop-filter, which makes it the containing
    // block for `position: fixed`. A sheet opened from the user menu therefore
    // sized itself against the topbar's 66 px and clipped its own form — the
    // fields were in the DOM at the right size, just outside the visible box.
    // Rendering through a portal on <body> is what prevents that.
    const { container } = render(
      <div style={{ backdropFilter: "blur(8px)", height: 66 }}>
        <Sheet open onClose={() => {}} title="Cambiar contraseña">
          <input aria-label="Contraseña actual" type="password" />
        </Sheet>
      </div>,
    );

    const field = screen.getByLabelText("Contraseña actual");
    expect(field).toBeInTheDocument();
    expect(container.contains(field)).toBe(false);
    expect(document.body.contains(field)).toBe(true);
  });

  it("renders nothing while closed", () => {
    render(
      <Sheet open={false} onClose={() => {}} title="Oculto">
        <p>contenido</p>
      </Sheet>,
    );
    expect(screen.queryByText("contenido")).not.toBeInTheDocument();
  });

  it("shows its title and a way out", () => {
    render(
      <Sheet open onClose={() => {}} title="Editar paciente">
        <p>ficha</p>
      </Sheet>,
    );
    expect(screen.getByText("Editar paciente")).toBeInTheDocument();
    expect(screen.getByLabelText("Cerrar")).toBeInTheDocument();
  });
});
