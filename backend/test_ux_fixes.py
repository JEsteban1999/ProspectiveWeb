"""Tests for the navigability and usability fixes.

These cover behaviour a user notices rather than an algorithm: that the search
box reaches past the newest page of studies, that a card offering «Reanudar»
really can be resumed, that reverting the preprocessing gives back the original
volume, and that a mis-imported clip can be taken out of the catalogue.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_uxfix_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from main import app
from services.database import Base, SessionLocal, engine
from services.db_models import ImagingStudy, Patient, PlanningSession, Study
from services.sessions import create_session, read_state, session_subdir, write_state

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


# ── Study gallery search ───────────────────────────────────────────────────── #

def _make_patient(db, surname: str, hospital_id: str) -> Patient:
    p = Patient(surname=surname, given_name="Ana", hospital_id=hospital_id, sex="F")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_study(db, patient: Patient, dx: str, description: str) -> ImagingStudy:
    case = Study(patient_id=patient.id, dx_principal=dx)
    db.add(case)
    db.commit()
    db.refresh(case)
    img = ImagingStudy(
        case_id=case.id, patient_id=patient.id,
        description=description, modality="CT",
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


class TestGallerySearch:
    def test_search_reaches_past_the_first_page(self):
        # `q` used to be applied in Python AFTER limit(), so a match older than
        # the newest `limit` rows came back empty with nothing to explain why.
        db = SessionLocal()
        try:
            target = _make_patient(db, "Zaldivar", "HC-BUSCAME")
            _make_study(db, target, "Aneurisma ACM", "Serie antigua")
            noise = _make_patient(db, "Ruido", "HC-RUIDO")
            for i in range(12):
                _make_study(db, noise, f"Caso {i}", f"Serie {i}")
        finally:
            db.close()

        # A limit smaller than the noise added after the target: only a filter
        # applied inside the query can still find it.
        r = client.get("/api/studies", params={"q": "Zaldivar", "limit": 3})
        assert r.status_code == 200, r.text
        names = [c["patient_name"] for c in r.json()]
        assert names and all("Zaldivar" in n for n in names)

    def test_search_matches_the_national_id(self):
        r = client.get("/api/studies", params={"q": "HC-BUSCAME"})
        assert r.status_code == 200
        assert any(c["hospital_id"] == "HC-BUSCAME" for c in r.json())

    def test_search_matches_the_case_diagnosis(self):
        r = client.get("/api/studies", params={"q": "Aneurisma ACM"})
        assert r.status_code == 200
        assert any(c["dx_principal"] == "Aneurisma ACM" for c in r.json())

    def test_a_search_with_no_match_returns_empty_not_everything(self):
        r = client.get("/api/studies", params={"q": "no-existe-este-paciente"})
        assert r.status_code == 200
        assert r.json() == []


class TestResumableSessionOnCards:
    def test_a_card_only_offers_resume_when_the_snapshot_exists(self):
        # The card advertises pipeline progress. Offering «Reanudar» for a session
        # whose files are gone would send the user into a 409.
        db = SessionLocal()
        try:
            p = _make_patient(db, "Restrepo", "HC-RESUME")
            img = _make_study(db, p, "ACoA", "CTA")
            db.add(PlanningSession(
                session_id="sesion-sin-archivos", patient_id=p.id,
                imaging_study_id=img.id, current_step=3,
            ))
            db.commit()
            img_id = img.id
        finally:
            db.close()

        card = next(c for c in client.get("/api/studies").json() if c["id"] == img_id)
        assert card["last_step"] == 3, "the card still shows the progress"
        assert card["resumable_session_id"] is None, "…but must not promise a restore"

    def test_a_study_with_no_session_has_nothing_to_resume(self):
        db = SessionLocal()
        try:
            p = _make_patient(db, "Sinsesion", "HC-NADA")
            img = _make_study(db, p, "Basilar", "RM")
            img_id = img.id
        finally:
            db.close()
        card = next(c for c in client.get("/api/studies").json() if c["id"] == img_id)
        assert card["resumable_session_id"] is None
        assert card["last_step"] is None


# ── Reverting the preprocessing ────────────────────────────────────────────── #

def _session_with_volume(shape=(6, 8, 8), spacing=(1.0, 0.5, 0.5)) -> str:
    """A session whose MPR cache is already primed, standing in for a DICOM load."""
    sid = create_session()
    meshes = session_subdir(sid, "meshes")
    vol = np.random.default_rng(0).normal(400, 50, size=shape).astype(np.float32)
    np.save(meshes / "_volume.npy", vol)
    (meshes / "_volume_meta.json").write_text(json.dumps({
        "shape": [int(x) for x in shape],
        "spacing": [float(s) for s in spacing],
        "wc": 300.0, "ww": 600.0, "modality": "CT",
    }))
    write_state(sid, "dicom.modality", "CT")
    return sid


def _session_with_dicom(nz=4, ny=16, nx=16) -> str:
    """A session holding real single-frame DICOM, so the volume can be rebuilt."""
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    sid = create_session()
    dicom_dir = session_subdir(sid, "dicom")
    series_uid = generate_uid()
    study_uid = generate_uid()
    rng = np.random.default_rng(1)

    for i in range(nz):
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"   # CT Image
        ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.Modality = "CT"
        ds.SeriesDescription = "CTA sintetica"
        ds.PatientName = "TEST^UX"
        ds.PatientID = "HC-UX"
        ds.Rows, ds.Columns = ny, nx
        ds.PixelSpacing = [0.5, 0.5]
        ds.SliceThickness = 1.0
        ds.SpacingBetweenSlices = 1.0
        ds.ImagePositionPatient = [0.0, 0.0, float(i)]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.InstanceNumber = i + 1
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1
        ds.RescaleIntercept = 0
        ds.RescaleSlope = 1
        ds.PixelData = rng.integers(0, 800, size=(ny, nx), dtype=np.int16).tobytes()
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        pydicom.dcmwrite(dicom_dir / f"slice_{i:03d}.dcm", ds, write_like_original=False)

    # Prime the MPR cache the way an upload would, so preprocessing has a volume.
    from services.mpr import ensure_volume_cached
    write_state(sid, "dicom.series_id", series_uid)
    ensure_volume_cached(sid)
    return sid


class TestPreprocessRevert:
    def test_status_reports_what_was_applied(self):
        sid = _session_with_volume()
        assert client.get(f"/api/preprocess/{sid}").json() == {"applied": False, "ops": ""}

        r = client.post(f"/api/preprocess/{sid}", json={"clip_hu": True})
        assert r.status_code == 200, r.text
        body = client.get(f"/api/preprocess/{sid}").json()
        assert body["applied"] is True
        assert "HU" in body["ops"]

    def test_smoothing_note_survives_a_non_ascii_character(self):
        # The note carries a Greek sigma. Session state was written in the
        # platform codepage, so on Windows storing it raised and the whole
        # request came back 500.
        sid = _session_with_volume()
        r = client.post(f"/api/preprocess/{sid}", json={"clip_hu": False, "smooth": True})
        assert r.status_code == 200, r.text
        assert "σ" in client.get(f"/api/preprocess/{sid}").json()["ops"]
        assert "σ" in read_state(sid, "preprocess.ops", "")

    def test_revert_rebuilds_the_volume_from_the_dicom(self):
        sid = _session_with_dicom()
        before = np.load(session_subdir(sid, "meshes") / "_volume.npy").shape
        client.post(f"/api/preprocess/{sid}", json={
            "clip_hu": False, "resample_isotropic": True, "target_spacing_mm": 1.0,
        })
        assert np.load(session_subdir(sid, "meshes") / "_volume.npy").shape != before

        r = client.delete(f"/api/preprocess/{sid}")
        assert r.status_code == 200, r.text
        assert tuple(r.json()["shape_after"]) == before
        assert np.load(session_subdir(sid, "meshes") / "_volume.npy").shape == before
        assert client.get(f"/api/preprocess/{sid}").json()["applied"] is False

    def test_a_failed_rebuild_keeps_the_volume_the_user_has(self):
        # Deleting the cache before proving the DICOM is readable would leave the
        # session with NO volume — strictly worse than the preprocessed one.
        sid = _session_with_volume()   # cached volume, no DICOM behind it
        client.post(f"/api/preprocess/{sid}", json={"clip_hu": True})
        cache = session_subdir(sid, "meshes") / "_volume.npy"
        kept = np.load(cache).copy()

        r = client.delete(f"/api/preprocess/{sid}")
        assert r.status_code == 409
        assert "conserva" in r.json()["detail"]
        assert cache.exists()
        assert np.array_equal(np.load(cache), kept)
        assert not (session_subdir(sid, "meshes") / "_volume_prev.npy").exists()

    def test_reverting_without_a_volume_is_a_clean_409(self):
        sid = create_session()
        r = client.delete(f"/api/preprocess/{sid}")
        assert r.status_code == 409

    def test_missing_session_is_404(self):
        assert client.delete("/api/preprocess/no-such-session").status_code == 404


# ── Custom clip catalogue ──────────────────────────────────────────────────── #

_CUBE_STL = b"solid c\n" + b"".join(
    b"facet normal 0 0 1\n outer loop\n"
    b"  vertex 0 0 0\n  vertex 1 0 0\n  vertex 0 1 0\n"
    b" endloop\nendfacet\n" for _ in range(1)
) + b"endsolid c\n"


def _import_clip(sid: str, name: str) -> str:
    r = client.post(
        f"/api/clips/custom/{sid}",
        files={"file": (name, _CUBE_STL, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    return r.json()["clip_id"]


class TestCustomClipCatalogue:
    def test_an_imported_clip_can_be_removed(self):
        # Importing the wrong file used to leave it in the dropdown for the rest
        # of the session, with the dropdown growing on every retry.
        sid = create_session()
        clip_id = _import_clip(sid, "malo.stl")
        assert [c["clip_id"] for c in client.get(f"/api/clips/custom/{sid}").json()] == [clip_id]

        idx = clip_id.split(":")[1]
        r = client.delete(f"/api/clips/custom/{sid}/{idx}")
        assert r.status_code == 200, r.text
        assert r.json() == []
        assert client.get(f"/api/clips/custom/{sid}").json() == []

    def test_removing_a_clip_deletes_its_geometry(self):
        sid = create_session()
        clip_id = _import_clip(sid, "bueno.stl")
        idx = clip_id.split(":")[1]
        mesh = session_subdir(sid, "meshes") / f"custom_clip_{idx}.vtp"
        assert mesh.exists()

        client.delete(f"/api/clips/custom/{sid}/{idx}")
        assert not mesh.exists()

    def test_a_later_import_never_reuses_a_freed_index(self):
        # The index came from len(registry), so importing after a delete pointed
        # the new entry at the surviving .vtp of a clip the user had removed.
        sid = create_session()
        first = _import_clip(sid, "uno.stl")
        second = _import_clip(sid, "dos.stl")
        client.delete(f"/api/clips/custom/{sid}/{first.split(':')[1]}")

        third = _import_clip(sid, "tres.stl")
        assert third != first and third != second

    def test_removing_a_clip_that_is_not_there_is_404(self):
        sid = create_session()
        assert client.delete(f"/api/clips/custom/{sid}/7").status_code == 404

    def test_listing_needs_a_real_session(self):
        assert client.get("/api/clips/custom/no-such-session").status_code == 404


# ── Session state encoding ─────────────────────────────────────────────────── #

class TestSessionStateEncoding:
    def test_state_round_trips_text_outside_the_windows_codepage(self):
        # Scanner series descriptions and clinical notes carry em dashes, Greek
        # letters and accents. Writing them used to raise on Windows, taking the
        # whole request down with a 500.
        sid = create_session()
        value = "σ 0.5 — CTA cráneo · 3DRA ≥ 512"
        write_state(sid, "dicom.description", value)
        assert read_state(sid, "dicom.description", "") == value

    def test_a_second_key_does_not_corrupt_the_first(self):
        sid = create_session()
        write_state(sid, "a", "ángulo 45°")
        write_state(sid, "b", "µ")
        assert read_state(sid, "a", "") == "ángulo 45°"
        assert read_state(sid, "b", "") == "µ"

    def test_state_written_before_utf8_was_pinned_still_reads(self):
        # An old session file holds cp1252 bytes. Losing one character beats
        # losing the whole session's state to a UnicodeDecodeError.
        sid = create_session()
        write_state(sid, "seg.strategy", "dsa")
        state = Path(session_subdir(sid, "meshes")).parent / "state.txt"
        state.write_bytes("seg.strategy=dsa\ndicom.description=cr\xe1neo\n".encode("cp1252"))
        assert read_state(sid, "seg.strategy", "") == "dsa"
        assert read_state(sid, "dicom.description", "") != ""
