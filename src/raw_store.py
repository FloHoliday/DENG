"""Raw zone: the exact API responses, gzip-compressed, with a manifest per unit (briefing §6.6).

Paths are deterministic, so a re-fetch overwrites the same unit and nothing else is ever deleted.
fsspec keeps the location swappable: file://./data/raw now, gs://<bucket>/raw later.
"""

import gzip
import hashlib
import json
import os
from datetime import UTC, datetime

import fsspec
from fsspec.implementations.local import LocalFileSystem

DATA_FILE = "data.json.gz"
MANIFEST_FILE = "_manifest.json"


class RawStore:
    def __init__(self, raw_uri: str):
        self.fs, self.root = fsspec.core.url_to_fs(raw_uri)

    def unit_dir(
        self,
        endpoint: str,
        year: int,
        meeting_key: int | None = None,
        session_key: int | None = None,
        driver_number: int | None = None,
    ) -> str:
        """Metadata units (meetings, sessions) only have a year; session_key is always the race key."""
        parts = [self.root, "openf1", "v1", endpoint, f"year={year}"]
        if session_key is not None:
            parts += [f"meeting_key={meeting_key}", f"session_key={session_key}"]
        if driver_number is not None:
            parts.append(f"driver_number={driver_number}")
        return "/".join(parts)

    def write(self, unit_dir: str, payload: bytes, manifest: dict) -> dict:
        """Store the payload, then the manifest; returns the manifest with sha256, bytes and fetched_at added.

        Data first, manifest last: a manifest therefore always refers to a complete data file.
        """
        manifest = {
            **manifest,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "fetched_at": manifest.get("fetched_at") or datetime.now(UTC).isoformat(),
        }
        self.fs.makedirs(unit_dir, exist_ok=True)
        # mtime=0 keeps the gzip bytes deterministic for identical payloads.
        _atomic_write(
            self.fs, f"{unit_dir}/{DATA_FILE}", gzip.compress(payload, mtime=0)
        )
        _atomic_write(
            self.fs,
            f"{unit_dir}/{MANIFEST_FILE}",
            json.dumps(manifest, indent=2, sort_keys=True).encode(),
        )
        return manifest

    def read_manifest(self, unit_dir: str) -> dict | None:
        path = f"{unit_dir}/{MANIFEST_FILE}"
        if not self.fs.exists(path):
            return None
        return json.loads(self.fs.cat_file(path))

    def read_payload(self, unit_dir: str) -> bytes:
        return gzip.decompress(self.fs.cat_file(f"{unit_dir}/{DATA_FILE}"))

    def read_records(self, unit_dir: str) -> list[dict]:
        return parse_records(self.read_payload(unit_dir))


def parse_records(payload: bytes) -> list[dict]:
    """The records of a stored payload; an empty result (`[]` or the 404 "No results found." body) gives []."""
    data = json.loads(payload)
    return data if isinstance(data, list) else []


def _atomic_write(fs, path: str, data: bytes) -> None:
    """Readers see either the old file or the complete new one, never a partial write."""
    if not isinstance(fs, LocalFileSystem):
        # Object stores (GCS) publish a single upload atomically.
        fs.pipe_file(path, data)
        return
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
