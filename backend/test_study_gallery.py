"""Study gallery: durable archive → listing/filter → preview → reopen.

The pipeline works on `data/sessions/<uuid>`, purged after SESSION_TTL_HOURS, so
a study only survives if its DICOM is copied into durable storage. These tests
cover that round-trip end to end with the local storage backend.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_gallery_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")
os.environ["STORAGE_BACKEND"] = "local"

import numpy as np
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine, SessionLocal
from services.db_models import Patient, Study
from services.sessions import create_session, session_subdir, write_state
from services import mpr as mprmod

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _patient_with_study(name="Galería", hc="HC-GAL-1") -> tuple[int, int]:
    db = SessionLocal()
    try:
        p = Patient(surname=name, given_name="Test", hospital_id=hc)
        db.add(p); db.commit(); db.refresh(p)
        s = Study(patient_id=p.id, description="3D-RA de prueba", dx_principal="Aneurisma ACM")
        db.add(s); db.commit(); db.refresh(s)
        return p.id, s.id
    finally:
        db.close()


from pathlib import Path

# Real DICOM files, needed by the tests that reopen a study: `open` now scans
# the archived files for series, so placeholder bytes are (correctly) rejected.
_CORPUS = Path(r"C:\UniNavarra\Proyectos\Prospective\ProspectiveWeb\Archivos DICOM"
               r"\DICOM-20260714T160737Z-1-001\DICOM")


def _session_with_dicom_and_volume(real_dicom: bool = False) -> str:
    """Session with a couple of DICOM files and a cached volume.

    `real_dicom=True` copies actual files from the corpus (needed when the test
    reopens the study, since that path parses the DICOM headers).
    """
    sid = create_session()
    dicom = session_subdir(sid, "dicom")
    if real_dicom:
        import shutil
        names = [n for n in ("IM_0001", "IM_0002") if (_CORPUS / n).exists()]
        if len(names) < 2:
            import pytest
            pytest.skip("corpus DICOM no disponible")
        for n in names:
            shutil.copy2(_CORPUS / n, dicom / n)
    else:
        (dicom / "IM_0001").write_bytes(b"DICM-fake-1")
        (dicom / "IM_0002").write_bytes(b"DICM-fake-2")

    n = 24
    vol = np.zeros((n, n, n), np.float32)
    vol[8:16, 8:16, 8:16] = 800.0          # a bright block so the thumbnail is not flat
    npy, meta = mprmod._cache_paths(sid)
    np.save(npy, vol)
    meta.write_text('{"shape": [24,24,24], "spacing": [1,1,1], "wc": 300, "ww": 900, "modality": "XA"}')
    mprmod._downsampled_volume.cache_clear()
    write_state(sid, "dicom.modality", "XA")
    write_state(sid, "dicom.n_slices", "24")
    return sid


class TestArchiveAndGallery:
    def test_archive_then_listed_with_preview(self):
        _pid, study_id = _patient_with_study()
        sid = _session_with_dicom_and_volume()

        r = client.post(f"/api/studies/{study_id}/archive", params={"session_id": sid})
        assert r.status_code == 200, r.text
        card = r.json()
        assert card["archived"] is True
        assert card["n_files"] == 2
        assert card["has_thumbnail"] is True
        assert card["modality"] == "XA"
        assert card["n_slices"] == 24

        # The gallery lists it with the patient identity used for filtering.
        cards = client.get("/api/studies").json()
        mine = [c for c in cards if c["id"] == study_id]
        assert mine and mine[0]["hospital_id"] == "HC-GAL-1"

        # Preview is a real PNG served by an authenticated endpoint (not /data).
        t = client.get(f"/api/studies/{study_id}/thumbnail")
        assert t.status_code == 200
        assert t.headers["content-type"] == "image/png"
        assert t.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_survives_session_deletion_and_reopens(self):
        """The point of archiving: the study outlives its working session."""
        from services.sessions import delete_session, session_subdir as sub

        _pid, study_id = _patient_with_study(name="Purga", hc="HC-GAL-2")
        sid = _session_with_dicom_and_volume(real_dicom=True)
        assert client.post(f"/api/studies/{study_id}/archive", params={"session_id": sid}).status_code == 200

        delete_session(sid)                       # simulate the TTL sweep

        r = client.post(f"/api/studies/{study_id}/open")
        assert r.status_code == 200, r.text
        body = r.json()
        new_sid = body["session_id"]
        assert new_sid != sid
        assert body["total_files"] == 2
        # A reopened study must arrive with a series already active, otherwise
        # the pipeline shows an empty panel and cannot continue.
        assert body["series"], "debe activar una serie al reabrir"
        restored = sorted(p.name for p in sub(new_sid, "dicom").iterdir())
        assert restored == ["IM_0001", "IM_0002"]

    def test_filter_by_name_and_hospital_id(self):
        _patient_with_study(name="Filtrable", hc="HC-UNICO-77")
        by_name = client.get("/api/studies", params={"q": "filtrable"}).json()
        by_hc   = client.get("/api/studies", params={"q": "UNICO-77"}).json()
        assert len(by_name) >= 1 and len(by_hc) >= 1
        assert all("Filtrable" in c["patient_name"] for c in by_name)
        assert client.get("/api/studies", params={"q": "no-existe-xyz"}).json() == []

    def test_open_unarchived_study_conflicts(self):
        _pid, study_id = _patient_with_study(name="SinArchivo", hc="HC-GAL-3")
        r = client.post(f"/api/studies/{study_id}/open")
        assert r.status_code == 409          # actionable, not a silent empty session

    def test_unknown_study_404(self):
        assert client.get("/api/studies/999999/thumbnail").status_code == 404
        assert client.post("/api/studies/999999/open").status_code == 404


class TestThumbnailQuality:
    def test_preview_is_not_a_black_image(self):
        """Regression: the first implementation re-did the windowing by hand and
        produced near-black previews on wide-window studies (3D-RA). It now
        delegates to render_slice_png — the same path the MPR viewer uses.
        """
        import io
        import numpy as np
        from PIL import Image
        from services.study_archive import build_thumbnail_png

        sid = _session_with_dicom_and_volume()
        png = build_thumbnail_png(sid)
        assert png, "debe generar una vista previa"

        arr = np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=float)
        assert arr.mean() > 10, f"vista previa casi negra (media {arr.mean():.1f}/255)"
        assert arr.max() - arr.min() > 40, "vista previa sin contraste (imagen plana)"


class TestOpenDoesNotDuplicateData:
    def test_restore_hardlinks_instead_of_copying(self):
        """Opening a study must not duplicate it on disk.

        Regression: studies are ~1 GB, so copying one into every working session
        filled the disk (WinError 112). The local backend hard-links instead —
        same data, no extra space — since the archived DICOM is read-only here.
        """
        import os
        from services.sessions import create_session, session_subdir
        from services.storage import get_storage, dicom_key

        storage = get_storage()
        study_id = 987654
        src_session = create_session()
        f = session_subdir(src_session, "dicom") / "IM_BIG"
        f.write_bytes(b"x" * 4096)
        storage.put_file(dicom_key(study_id, "IM_BIG"), f)

        dest = session_subdir(create_session(), "dicom")
        assert storage.download_prefix(f"studies/{study_id}/dicom", dest) == 1

        out = dest / "IM_BIG"
        assert out.read_bytes() == b"x" * 4096
        # Same inode ⇒ the bytes are shared, not duplicated.
        if hasattr(os, "stat") and os.name == "nt":
            assert out.stat().st_nlink > 1, "debería ser un enlace duro, no una copia"

        storage.delete_prefix(f"studies/{study_id}")


class TestStorageIsolation:
    def test_study_files_are_not_under_public_data_dir(self):
        """DICOM carries PHI and `data/` is mounted as public StaticFiles."""
        from services.storage import STUDY_FILES_ROOT
        assert "data" not in STUDY_FILES_ROOT.parts[-2:], STUDY_FILES_ROOT

    def test_keys_cannot_escape_the_store(self):
        from services.storage import LocalBackend
        import pytest
        b = LocalBackend()
        with pytest.raises(ValueError):
            b.exists("../../etc/passwd")
