/* Every screen has a URL now. Before this the active screen lived in a
   `useState`, so Back walked out of the application, a refresh always landed on
   the patient list, and there was no link to send a colleague. */

import { describe, expect, it } from "vitest";
import { SCREEN_PATH, screenFromPath } from "./nav";
import type { Screen } from "./nav";

const SCREENS = Object.keys(SCREEN_PATH) as Screen[];

describe("screen ↔ URL", () => {
  it("round-trips every screen through its path", () => {
    for (const s of SCREENS) {
      expect(screenFromPath(SCREEN_PATH[s])).toBe(s);
    }
  });

  it("gives every screen a distinct path", () => {
    expect(new Set(Object.values(SCREEN_PATH)).size).toBe(SCREENS.length);
  });

  it("keeps every path under /app so the landing route stays free", () => {
    for (const path of Object.values(SCREEN_PATH)) {
      expect(path.startsWith("/app/")).toBe(true);
    }
  });

  it("treats bare /app as the patient list", () => {
    // The landing page links to /app; it must not dead-end.
    expect(screenFromPath("/app")).toBe("patients");
  });

  it("ignores a trailing slash", () => {
    expect(screenFromPath("/app/pacientes/")).toBe("patients");
    expect(screenFromPath("/app/")).toBe("patients");
  });

  it("falls back to the patient list for an unknown path", () => {
    // A stale bookmark should land somewhere usable, not on a blank screen.
    expect(screenFromPath("/app/no-existe")).toBe("patients");
  });
});
