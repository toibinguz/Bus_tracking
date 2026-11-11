"""Timezone-free receipt and hashing helpers for closed spool artifacts."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path


RECEIPT_SUFFIX = ".receipt.json"


def file_sha256(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt_path(spool_file: str | Path) -> Path:
    return Path(f"{spool_file}{RECEIPT_SUFFIX}")


def load_receipt(spool_file: str | Path) -> dict[str, str] | None:
    path = receipt_path(spool_file)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_receipt(spool_file: str | Path, hdfs_path: str, payload_sha256: str) -> None:
    path = receipt_path(spool_file)
    temporary_path = Path(f"{path}.tmp")
    temporary_path.write_text(
        json.dumps({"hdfs_path": hdfs_path, "sha256": payload_sha256}, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)
