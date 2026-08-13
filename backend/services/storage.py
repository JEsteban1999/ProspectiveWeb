"""Durable study storage — pluggable local / S3 backend.

Where uploaded studies live *permanently*, as opposed to `data/sessions/<uuid>`,
which is working scratch space purged by the TTL sweep.

PRIVACY — read before changing paths
------------------------------------
`main.py` mounts `data/` as public StaticFiles, so ANYTHING under `data/` is
downloadable without authentication. DICOM headers carry patient name, national
ID and date of birth, so the local store lives in `study_files/` (a sibling of
`user_files/`, which holds photos/CVs for the same reason) and is only ever
served through authenticated endpoints.

Backend selection (env `STORAGE_BACKEND`):
  "local" (default) — filesystem under STUDY_FILES_ROOT. No credentials needed,
                      so the feature can be built and tested without AWS.
  "s3"              — AWS S3 via boto3. Requires STORAGE_S3_BUCKET; the bucket
                      must be private and encrypted at rest, and objects are
                      handed to clients only as short-lived presigned URLs.

Keys are POSIX-style and backend-agnostic, e.g.
    studies/42/dicom/IM_0018
    studies/42/thumb.png
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# Deliberately NOT under data/ (that path is public — see module docstring).
_DEFAULT_STUDY_FILES_ROOT = Path(__file__).resolve().parents[1] / "study_files"


def study_files_root() -> Path:
    """Archive root, resolved on every call.

    Read dynamically (not frozen at import time) so `STUDY_FILES_ROOT` set by the
    test suite always wins: as a module constant it was captured by whichever
    test imported this module first, and the rest of the suite then archived
    studies 1, 2, 3… into the real store — overwriting a clinician's DICOM and
    preview. Same class of bug as the test database contaminating the dev one.
    """
    return Path(os.environ.get("STUDY_FILES_ROOT") or _DEFAULT_STUDY_FILES_ROOT)

_PRESIGN_TTL_SEC = 300   # short-lived: these URLs expose patient imaging


def study_prefix(study_id: int) -> str:
    return f"studies/{study_id}"


def dicom_key(study_id: int, filename: str) -> str:
    # Flatten any directory structure; DICOM filenames are already unique-ish
    # and a nested upload must not let a key escape its study prefix.
    safe = Path(filename).name
    return f"{study_prefix(study_id)}/dicom/{safe}"


def thumb_key(study_id: int) -> str:
    return f"{study_prefix(study_id)}/thumb.png"


class StorageBackend(Protocol):
    def put_file(self, key: str, src: Path) -> None: ...
    def put_bytes(self, key: str, data: bytes) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list_prefix(self, prefix: str) -> list[str]: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def download_prefix(self, prefix: str, dest_dir: Path) -> int: ...
    def size_bytes(self, prefix: str) -> int: ...


class LocalBackend:
    """Filesystem store. Same key space as S3, so switching is transparent."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        # Resolved per access so a test that redirects the archive after this
        # backend was built still writes to its temp directory.
        return self._root or study_files_root()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        # Guard against '..' in a key escaping the store.
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError(f"Invalid storage key: {key!r}")
        return p

    def put_file(self, key: str, src: Path) -> None:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def put_bytes(self, key: str, data: bytes) -> None:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_prefix(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        if not base.is_dir():
            return []
        return sorted(
            str(p.relative_to(self.root)).replace("\\", "/")
            for p in base.rglob("*") if p.is_file()
        )

    def delete_prefix(self, prefix: str) -> None:
        base = self._path(prefix)
        if base.is_dir():
            shutil.rmtree(base, ignore_errors=True)

    def download_prefix(self, prefix: str, dest_dir: Path) -> int:
        """Materialise every object under `prefix` into `dest_dir`.

        Tries a hard link first: a study is often >1 GB and copying it into every
        working session filled the disk (and DICOM is read-only here, so sharing
        the data is safe). Falls back to a real copy across volumes or on any
        filesystem that refuses links.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for key in self.list_prefix(prefix):
            src, dst = self._path(key), dest_dir / Path(key).name
            if dst.exists():
                dst.unlink()
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
            n += 1
        return n

    def size_bytes(self, prefix: str) -> int:
        return sum(self._path(k).stat().st_size for k in self.list_prefix(prefix))


class S3Backend:
    """AWS S3 store. The bucket MUST be private and encrypted at rest."""

    def __init__(self, bucket: str, prefix: str = "") -> None:
        import boto3  # imported lazily so local dev needs no AWS deps
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._s3 = boto3.client("s3")

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_file(self, key: str, src: Path) -> None:
        self._s3.upload_file(str(src), self.bucket, self._key(key),
                             ExtraArgs={"ServerSideEncryption": "AES256"})

    def put_bytes(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=self._key(key), Body=data,
                            ServerSideEncryption="AES256")

    def get_bytes(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError:
            return False

    def _objects(self, prefix: str) -> list[dict]:
        paginator = self._s3.get_paginator("list_objects_v2")
        out: list[dict] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._key(prefix)):
            out.extend(page.get("Contents", []))
        return out

    def list_prefix(self, prefix: str) -> list[str]:
        cut = len(self.prefix) + 1 if self.prefix else 0
        return sorted(o["Key"][cut:] for o in self._objects(prefix))

    def delete_prefix(self, prefix: str) -> None:
        objs = self._objects(prefix)
        for i in range(0, len(objs), 1000):        # delete_objects caps at 1000
            batch = [{"Key": o["Key"]} for o in objs[i:i + 1000]]
            self._s3.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})

    def download_prefix(self, prefix: str, dest_dir: Path) -> int:
        dest_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for key in self.list_prefix(prefix):
            self._s3.download_file(self.bucket, self._key(key), str(dest_dir / Path(key).name))
            n += 1
        return n

    def size_bytes(self, prefix: str) -> int:
        return sum(int(o.get("Size", 0)) for o in self._objects(prefix))

    def presigned_url(self, key: str, ttl: int = _PRESIGN_TTL_SEC) -> str:
        """Short-lived URL. Never hand out anything longer for patient imaging."""
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(key)},
            ExpiresIn=ttl,
        )


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured backend (singleton)."""
    global _backend
    if _backend is not None:
        return _backend

    kind = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
    if kind == "s3":
        bucket = os.environ.get("STORAGE_S3_BUCKET", "").strip()
        if not bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requires STORAGE_S3_BUCKET")
        _backend = S3Backend(bucket, os.environ.get("STORAGE_S3_PREFIX", ""))
        logger.info("Study storage: S3 bucket %s", bucket)
    else:
        _backend = LocalBackend()
        logger.info("Study storage: local at %s", study_files_root())
    return _backend


def reset_storage_for_tests() -> None:
    global _backend
    _backend = None
