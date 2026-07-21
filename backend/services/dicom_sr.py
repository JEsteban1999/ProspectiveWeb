"""DICOM Structured Report (SR) generator — port of the desktop io/dicom_sr.py.

Produces a Comprehensive SR (SOP Class 1.2.840.10008.5.1.4.1.1.88.33) following
TID 1500 (Measurement Report): patient/study header, aneurysm morphometry (NUM
items, UCUM units), risk assessment (CODE item), and optional device plans.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid

logger = logging.getLogger(__name__)

_SR_COMPREHENSIVE = "1.2.840.10008.5.1.4.1.1.88.33"
_EXPLICIT_VR_LE   = "1.2.840.10008.1.2.1"

_C = {
    "REPORT":      ("113000",    "DCM",   "Imaging Measurement Report"),
    "MORPHOMETRY": ("99PRP001",  "99PRP", "Aneurysm Morphometry"),
    "PLAN":        ("99PRP002",  "99PRP", "Surgical Clip Plan"),
    "TRAJECTORY":  ("99PRP003",  "99PRP", "Approach Trajectory"),
    "CLIP":        ("99PRP004",  "99PRP", "Surgical Clip"),
    "STENT_PLAN":  ("99PRP005",  "99PRP", "Endovascular Device Plan"),
    "STENT":       ("99PRP006",  "99PRP", "Endovascular Device"),
    "COIL_PLAN":   ("99PRP007",  "99PRP", "Embolization Coil Plan"),
    "COIL":        ("99PRP008",  "99PRP", "Embolization Coil"),
    "VOLUME":      ("121216",    "DCM",   "Volume"),
    "AREA":        ("99PRP010",  "99PRP", "Surface Area"),
    "MAX_DIAM":    ("103339001", "SCT",   "Maximum Diameter"),
    "NECK_DIAM":   ("99PRP011",  "99PRP", "Neck Diameter"),
    "DOME_HEIGHT": ("99PRP012",  "99PRP", "Dome Height"),
    "DNR":         ("99PRP013",  "99PRP", "Dome-to-Neck Ratio"),
    "AR":          ("99PRP014",  "99PRP", "Aspect Ratio"),
    "COMPACTNESS": ("99PRP015",  "99PRP", "Compactness (Wadell Sphericity)"),
    "EQ_DIAM":     ("99PRP016",  "99PRP", "Equivalent Sphere Diameter"),
    "RISK":        ("99PRP020",  "99PRP", "Rupture Risk Assessment"),
    "CLIP_MODEL":  ("99PRP030",  "99PRP", "Clip Model"),
    "POS_X":       ("99PRP031",  "99PRP", "Clip Position X"),
    "POS_Y":       ("99PRP032",  "99PRP", "Clip Position Y"),
    "POS_Z":       ("99PRP033",  "99PRP", "Clip Position Z"),
    "CLIP_TYPE":   ("99PRP037",  "99PRP", "Clip Type"),
    "STENT_MODEL": ("99PRP050",  "99PRP", "Device Model"),
    "STENT_TYPE":  ("99PRP051",  "99PRP", "Device Type"),
    "STENT_DIAM":  ("99PRP052",  "99PRP", "Device Nominal Diameter"),
    "STENT_LENGTH":("99PRP053",  "99PRP", "Device Length"),
    "COIL_MODEL":  ("99PRP060",  "99PRP", "Coil Model"),
    "COIL_TYPE":   ("99PRP061",  "99PRP", "Coil Type"),
    "COIL_DIAM":   ("99PRP062",  "99PRP", "Coil Nominal Diameter"),
}

_U = {
    "mm":    ("mm",  "UCUM", "mm"),
    "mm2":   ("mm2", "UCUM", "mm2"),
    "mm3":   ("mm3", "UCUM", "mm3"),
    "cm":    ("cm",  "UCUM", "cm"),
    "deg":   ("deg", "UCUM", "deg"),
    "ratio": ("1",   "UCUM", "no units"),
}

_RISK_CODES = {
    "Alto":     ("723509005", "SCT", "High risk"),
    "Moderado": ("723510000", "SCT", "Intermediate risk"),
    "Bajo":     ("723511001", "SCT", "Low risk"),
}


def _code_ds(code: str, scheme: str, meaning: str) -> Dataset:
    ds = Dataset()
    ds.CodeValue = code
    ds.CodingSchemeDesignator = scheme
    ds.CodeMeaning = meaning
    return ds


def _concept_name(key: str) -> Sequence:
    return Sequence([_code_ds(*_C[key])])


def _num_item(concept_key: str, value: float, unit_key: str, relationship: str = "CONTAINS") -> Dataset:
    item = Dataset()
    item.RelationshipType = relationship
    item.ValueType = "NUM"
    item.ConceptNameCodeSequence = _concept_name(concept_key)
    mv = Dataset()
    mv.NumericValue = f"{value:.4f}"
    mv.MeasurementUnitsCodeSequence = Sequence([_code_ds(*_U[unit_key])])
    item.MeasuredValueSequence = Sequence([mv])
    return item


def _text_item(concept_key: str, text: str, relationship: str = "CONTAINS") -> Dataset:
    item = Dataset()
    item.RelationshipType = relationship
    item.ValueType = "TEXT"
    item.ConceptNameCodeSequence = _concept_name(concept_key)
    item.TextValue = str(text)
    return item


def _code_item(concept_key: str, value_code: str, value_scheme: str, value_meaning: str,
               relationship: str = "CONTAINS") -> Dataset:
    item = Dataset()
    item.RelationshipType = relationship
    item.ValueType = "CODE"
    item.ConceptNameCodeSequence = _concept_name(concept_key)
    item.ConceptCodeSequence = Sequence([_code_ds(value_code, value_scheme, value_meaning)])
    return item


def _container(concept_key: str, children: list[Dataset], continuity: str = "SEPARATE",
               relationship: str = "CONTAINS") -> Dataset:
    item = Dataset()
    item.RelationshipType = relationship
    item.ValueType = "CONTAINER"
    item.ConceptNameCodeSequence = _concept_name(concept_key)
    item.ContinuityOfContent = continuity
    item.ContentSequence = Sequence(children)
    return item


class DicomSRGenerator:
    """Build a DICOM Comprehensive SR from planning data."""

    def __init__(
        self,
        series_meta: dict[str, Any],
        morphometrics: dict[str, Any],
        clips: list[dict[str, Any]] | None = None,
        trajectory: dict[str, Any] | None = None,
        stents: list[dict[str, Any]] | None = None,
        coils: list[dict[str, Any]] | None = None,
        risk_label: str = "",
    ) -> None:
        self._meta = series_meta
        self._morpho = morphometrics
        self._clips = clips or []
        self._traj = trajectory or {}
        self._stents = stents or []
        self._coils = coils or []
        self._risk = risk_label

    def generate(self, output_path: str | Path) -> Path:
        p = Path(output_path)
        if p.suffix.lower() != ".dcm":
            p = p.with_suffix(".dcm")
        p.parent.mkdir(parents=True, exist_ok=True)
        pydicom.dcmwrite(str(p), self._build_dataset())
        logger.info("DICOM SR written: %s", p)
        return p

    def _build_dataset(self) -> FileDataset:
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S.%f")
        sop_instance_uid = generate_uid()

        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = _SR_COMPREHENSIVE
        file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
        file_meta.TransferSyntaxUID = _EXPLICIT_VR_LE

        ds = FileDataset(filename_or_obj=None, dataset={}, file_meta=file_meta, preamble=b"\x00" * 128)

        ds.PatientName = self._meta.get("patient_name", "ANONIMO")
        ds.PatientID = self._meta.get("patient_id", "")
        ds.PatientBirthDate = ""
        ds.PatientSex = ""

        ds.StudyInstanceUID = self._meta.get("study_instance_uid") or generate_uid()
        ds.StudyDate = str(self._meta.get("study_date", date_str)).replace("-", "")
        ds.StudyTime = ""
        ds.ReferringPhysicianName = ""
        ds.StudyID = "1"
        ds.AccessionNumber = ""
        ds.StudyDescription = self._meta.get("study_description", "")

        ds.Modality = "SR"
        ds.SeriesInstanceUID = generate_uid()
        ds.SeriesNumber = "999"
        ds.SeriesDescription = "PROSPECTIVE Surgical Plan"

        ds.Manufacturer = "SkullApp"
        ds.ManufacturerModelName = "PROSPECTIVE"
        ds.SoftwareVersions = "0.1.0"

        ds.SOPClassUID = _SR_COMPREHENSIVE
        ds.SOPInstanceUID = sop_instance_uid
        ds.InstanceNumber = "1"
        ds.ContentDate = date_str
        ds.ContentTime = time_str
        ds.CompletionFlag = "COMPLETE"
        ds.VerificationFlag = "UNVERIFIED"

        ds.ValueType = "CONTAINER"
        ds.ConceptNameCodeSequence = _concept_name("REPORT")
        ds.ContinuityOfContent = "SEPARATE"

        root_items: list[Dataset] = []
        if self._morpho:
            root_items.append(self._build_morphometry_container())
        if self._clips:
            root_items.append(self._build_clip_plan_container())
        if self._stents:
            root_items.append(self._build_stent_plan_container())
        if self._coils:
            root_items.append(self._build_coil_plan_container())
        if self._traj:
            root_items.append(self._build_trajectory_container())

        ds.ContentSequence = Sequence(root_items)
        return ds

    def _build_morphometry_container(self) -> Dataset:
        m = self._morpho
        items: list[Dataset] = []

        def _add(key, field, unit):
            v = m.get(field)
            if v is not None and float(v) != 0.0:
                items.append(_num_item(key, float(v), unit))

        _add("VOLUME", "volume_mm3", "mm3")
        _add("AREA", "surface_area_mm2", "mm2")
        _add("MAX_DIAM", "max_diameter_mm", "mm")
        _add("EQ_DIAM", "eq_sphere_diam_mm", "mm")
        _add("NECK_DIAM", "neck_diameter_mm", "mm")
        _add("DOME_HEIGHT", "dome_height_mm", "mm")
        _add("DNR", "dome_to_neck_ratio", "ratio")
        _add("AR", "aspect_ratio", "ratio")
        _add("COMPACTNESS", "compactness", "ratio")

        if self._risk in _RISK_CODES:
            items.append(_code_item("RISK", *_RISK_CODES[self._risk]))
        return _container("MORPHOMETRY", items)

    def _build_clip_plan_container(self) -> Dataset:
        clip_items: list[Dataset] = []
        for c in self._clips:
            pos = c.get("position_mm", (0, 0, 0))
            clip_items.append(_container("CLIP", [
                _text_item("CLIP_MODEL", c.get("name", "—")),
                _text_item("CLIP_TYPE", "Personalizado" if c.get("is_custom") else "Catálogo"),
                _num_item("POS_X", float(pos[0]), "mm"),
                _num_item("POS_Y", float(pos[1]), "mm"),
                _num_item("POS_Z", float(pos[2]), "mm"),
            ]))
        return _container("PLAN", clip_items)

    def _build_stent_plan_container(self) -> Dataset:
        items: list[Dataset] = []
        for s in self._stents:
            children = [
                _text_item("STENT_MODEL", s.get("name", "—")),
                _text_item("STENT_TYPE", s.get("stent_type", "—")),
            ]
            if s.get("diameter_mm") is not None:
                children.append(_num_item("STENT_DIAM", float(s["diameter_mm"]), "mm"))
            if s.get("length_mm") is not None:
                children.append(_num_item("STENT_LENGTH", float(s["length_mm"]), "mm"))
            items.append(_container("STENT", children))
        return _container("STENT_PLAN", items)

    def _build_coil_plan_container(self) -> Dataset:
        items: list[Dataset] = []
        for c in self._coils:
            children = [
                _text_item("COIL_MODEL", c.get("name", "—")),
                _text_item("COIL_TYPE", c.get("coil_type", "—")),
            ]
            if c.get("diameter_mm") is not None:
                children.append(_num_item("COIL_DIAM", float(c["diameter_mm"]), "mm"))
            items.append(_container("COIL", children))
        return _container("COIL_PLAN", items)

    def _build_trajectory_container(self) -> Dataset:
        tr = self._traj
        entry = tr.get("entry", [0, 0, 0])
        target = tr.get("target", [0, 0, 0])
        return _container("TRAJECTORY", [
            _text_item("CLIP_MODEL", f"Entrada ({entry[0]:.1f}, {entry[1]:.1f}, {entry[2]:.1f})"),
            _text_item("CLIP_MODEL", f"Diana ({target[0]:.1f}, {target[1]:.1f}, {target[2]:.1f})"),
        ])
