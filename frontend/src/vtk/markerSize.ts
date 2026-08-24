/* How big a 3D marker should be.
 *
 * Kept apart from MeshView so it can be reasoned about — and tested — without
 * dragging in the vtk.js runtime.
 *
 * The markers used to be a flat 1.4 mm radius: 2.8 mm across, wider than many of
 * the vessels they sit on, so the sphere marking the neck, the dome apex or a
 * grow seed hid the very feature being marked. A pinpoint has to read smaller
 * than what it points at.
 *
 * The size is therefore derived: from the candidate's own diameter when the
 * caller knows it, otherwise from the scene's bounding-box diagonal, so the same
 * marker works on a whole 3D-RA tree and on a 30 mm cropped region.
 */

export const MARKER_FROM_REFERENCE = 0.10;    // of the candidate's diameter
export const MARKER_FROM_SCENE     = 0.0025;  // of the bounding-box diagonal
export const MARKER_MIN_MM         = 0.22;
export const MARKER_MAX_MM         = 0.75;

/** Ruler geometry, kept in proportion to the markers. */
export const RULER_TUBE_RATIO = 0.5;
export const RULER_BEAD_RATIO = 0.9;

export function markerRadiusMm(
  referenceDiameterMm: number | null | undefined,
  sceneDiagonalMm: number,
): number {
  const raw =
    referenceDiameterMm && referenceDiameterMm > 0
      ? referenceDiameterMm * MARKER_FROM_REFERENCE
      : sceneDiagonalMm * MARKER_FROM_SCENE;
  if (!Number.isFinite(raw)) return MARKER_MIN_MM;
  return Math.min(MARKER_MAX_MM, Math.max(MARKER_MIN_MM, raw));
}
