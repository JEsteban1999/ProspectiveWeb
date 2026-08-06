"""Mesh preparation for 3D printing — port of the desktop
prospective/processing/mesh_prep.py (Feature 7).

Fill holes → smooth → optional subdivision → triangulate → scale to target →
mass properties (volume/area) → watertightness check → STL export. Print-bed
presets let the caller verify the model fits a given printer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import vtk

logger = logging.getLogger(__name__)

# Print-bed presets: name → (x_mm, y_mm, z_mm). A dimension of 0 = unlimited.
PRINT_BED_PRESETS: dict[str, tuple[float, float, float]] = {
    "Ender 3 / 3 Pro": (220.0, 220.0, 250.0),
    "Prusa MK4": (250.0, 210.0, 220.0),
    "Bambu Lab X1C": (256.0, 256.0, 256.0),
    "Formlabs Form 3": (145.0, 145.0, 185.0),
    "Ultimaker S3": (230.0, 190.0, 200.0),
    "Personalizado": (0.0, 0.0, 0.0),
}


@dataclass
class PrintPrepResult:
    mesh: vtk.vtkPolyData
    scale_factor: float
    dimensions_mm: tuple[float, float, float]
    volume_cm3: float
    surface_area_cm2: float
    is_watertight: bool
    open_edge_count: int
    warnings: list[str] = field(default_factory=list)

    def fits_in_bed(self, bed: tuple[float, float, float]) -> bool:
        bx, by, bz = bed
        dx, dy, dz = self.dimensions_mm
        if bx > 0 and dx > bx:
            return False
        if by > 0 and dy > by:
            return False
        if bz > 0 and dz > bz:
            return False
        return True

    def export_stl(self, path: str | Path) -> None:
        writer = vtk.vtkSTLWriter()
        writer.SetFileName(str(path))
        writer.SetInputData(self.mesh)
        writer.Write()
        logger.info("PrintPrep: exported STL → %s  (%.2f cm³)", path, self.volume_cm3)


def prepare_mesh_for_print(
    poly_data: vtk.vtkPolyData,
    target_size_mm: float = 80.0,
    smooth_iterations: int = 20,
    smooth_relaxation: float = 0.1,
    fill_holes: bool = True,
    hole_size: float = 5.0,
    subdivide: bool = False,
) -> PrintPrepResult:
    """Prepare *poly_data* for 3D printing. See module docstring for the steps."""
    warnings: list[str] = []
    if poly_data is None or poly_data.GetNumberOfPoints() == 0:
        raise ValueError("La malla está vacía.")

    mesh = poly_data

    # 1. Normals (consistent orientation)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(mesh)
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOff()
    normals.Update()
    mesh = normals.GetOutput()

    # 2. Fill holes
    if fill_holes:
        filler = vtk.vtkFillHolesFilter()
        filler.SetInputData(mesh)
        filler.SetHoleSize(hole_size)
        filler.Update()
        mesh = filler.GetOutput()
        n2 = vtk.vtkPolyDataNormals()
        n2.SetInputData(mesh)
        n2.ConsistencyOn()
        n2.SplittingOff()
        n2.Update()
        mesh = n2.GetOutput()

    # 3. Smooth
    if smooth_iterations > 0:
        smoother = vtk.vtkSmoothPolyDataFilter()
        smoother.SetInputData(mesh)
        smoother.SetNumberOfIterations(smooth_iterations)
        smoother.SetRelaxationFactor(smooth_relaxation)
        smoother.BoundarySmoothingOff()
        smoother.Update()
        mesh = smoother.GetOutput()

    # 4. Optional subdivision
    if subdivide:
        sub = vtk.vtkLinearSubdivisionFilter()
        sub.SetInputData(mesh)
        sub.SetNumberOfSubdivisions(1)
        sub.Update()
        mesh = sub.GetOutput()

    # 5. Triangulate
    tri = vtk.vtkTriangleFilter()
    tri.SetInputData(mesh)
    tri.Update()
    mesh = tri.GetOutput()

    # 6. Scale to target size
    bounds = mesh.GetBounds()
    max_dim = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
    scale_factor = target_size_mm / max_dim if (target_size_mm > 0 and max_dim > 1e-6) else 1.0
    if scale_factor != 1.0:
        transform = vtk.vtkTransform()
        transform.Scale(scale_factor, scale_factor, scale_factor)
        tf = vtk.vtkTransformPolyDataFilter()
        tf.SetInputData(mesh)
        tf.SetTransform(transform)
        tf.Update()
        mesh = tf.GetOutput()

    # 7. Final normals
    fn = vtk.vtkPolyDataNormals()
    fn.SetInputData(mesh)
    fn.ConsistencyOn()
    fn.SplittingOff()
    fn.ComputePointNormalsOn()
    fn.Update()
    mesh = fn.GetOutput()

    # 8. Mass properties
    props = vtk.vtkMassProperties()
    props.SetInputData(mesh)
    props.Update()
    volume_mm3 = props.GetVolume()
    surface_area_mm2 = props.GetSurfaceArea()
    if volume_mm3 < 0:
        volume_mm3 = abs(volume_mm3)
        warnings.append("Volumen negativo calculado — la malla puede tener normales invertidas.")
    volume_cm3 = volume_mm3 / 1000.0
    surface_area_cm2 = surface_area_mm2 / 100.0

    # 9. Watertightness via open (boundary) edges
    feat = vtk.vtkFeatureEdges()
    feat.SetInputData(mesh)
    feat.BoundaryEdgesOn()
    feat.FeatureEdgesOff()
    feat.ManifoldEdgesOff()
    feat.NonManifoldEdgesOff()
    feat.Update()
    open_edge_count = feat.GetOutput().GetNumberOfLines()
    is_watertight = open_edge_count == 0
    if not is_watertight:
        warnings.append(
            f"Malla no hermética: {open_edge_count} bordes abiertos. "
            "Aumenta 'Tamaño máximo de agujero' o repárala externamente antes de imprimir."
        )

    # 10. Scaled dimensions + sanity warnings
    sb = mesh.GetBounds()
    dims = (round(sb[1] - sb[0], 3), round(sb[3] - sb[2], 3), round(sb[5] - sb[4], 3))
    if max(dims) > 300.0:
        warnings.append(f"Dimensión máxima {max(dims):.1f} mm supera 300 mm — verifica la escala.")
    if volume_cm3 < 0.001:
        warnings.append("Volumen calculado muy pequeño — verifica la malla.")

    logger.info(
        "PrintPrep: done — scale=%.4f dims=%s vol=%.3f cm³ watertight=%s",
        scale_factor, dims, volume_cm3, is_watertight,
    )
    return PrintPrepResult(
        mesh=mesh,
        scale_factor=round(scale_factor, 6),
        dimensions_mm=dims,
        volume_cm3=round(volume_cm3, 4),
        surface_area_cm2=round(surface_area_cm2, 4),
        is_watertight=is_watertight,
        open_edge_count=open_edge_count,
        warnings=warnings,
    )
