/* A marker has to read smaller than the thing it points at.
 *
 * They were a flat 1.4 mm radius — 2.8 mm across. Cerebral vessels are 1–4 mm
 * wide, so the sphere marking the neck, the dome apex or a seed hid the very
 * feature the clinician was placing it on. */

import { describe, expect, it } from "vitest";
import { markerRadiusMm } from "./markerSize";

const OLD_FIXED_RADIUS = 1.4;

describe("marker size against the candidate", () => {
  it("stays a fraction of the structure it marks", () => {
    // A 7 mm dome gets a marker it can hold; the dome still reads as a dome.
    const r = markerRadiusMm(7, 230);
    expect(r * 2).toBeLessThan(7 / 3);
  });

  it("shrinks for a small candidate instead of swallowing it", () => {
    const small = markerRadiusMm(3, 230);
    const large = markerRadiusMm(13, 230);
    expect(small).toBeLessThan(large);
    expect(small * 2).toBeLessThan(3); // never wider than the candidate itself
  });

  it("never grows back to the old fixed size", () => {
    for (const d of [3, 7, 13, 25, 100]) {
      expect(markerRadiusMm(d, 230)).toBeLessThan(OLD_FIXED_RADIUS);
    }
  });
});

describe("marker size without a candidate", () => {
  it("falls back to the scene and stays well under a vessel calibre", () => {
    // A whole 3D-RA tree spans roughly 230 mm; vessels there are 1–4 mm.
    const r = markerRadiusMm(null, 230);
    expect(r * 2).toBeLessThan(1.5);
    expect(r).toBeGreaterThan(0);
  });

  it("does not vanish on a cropped region of interest", () => {
    // Cropping to 40 mm must not leave a marker too small to see or click.
    expect(markerRadiusMm(null, 40)).toBeGreaterThanOrEqual(0.2);
  });

  it("does not blow up on an oversized volume", () => {
    // A whole-head CT is far larger than an angiographic tree; the marker must
    // not scale with it indefinitely.
    expect(markerRadiusMm(null, 900)).toBeLessThanOrEqual(0.75);
  });

  it("handles an empty scene without producing zero or NaN", () => {
    const r = markerRadiusMm(null, 0);
    expect(Number.isFinite(r)).toBe(true);
    expect(r).toBeGreaterThan(0);
  });
});

describe("monotonicity", () => {
  it("grows with the scene, never shrinks", () => {
    const sizes = [30, 60, 120, 240, 480].map((d) => markerRadiusMm(null, d));
    expect(sizes).toEqual([...sizes].sort((a, b) => a - b));
  });

  it("prefers the candidate over the scene when both are known", () => {
    // Same tiny candidate in a huge scene must still get a small marker.
    expect(markerRadiusMm(3, 900)).toBeLessThan(markerRadiusMm(null, 900));
  });
});
