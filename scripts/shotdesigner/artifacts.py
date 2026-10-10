"""Shared case-local artifact path and hashing utilities."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def resolve(root, raw_path):
    root = Path(root).resolve()
    raw = Path(raw_path)
    if raw.is_absolute():
        raise ValueError("artifact paths must be relative to the current case root")
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("artifact path escapes the current case root") from exc
    return path
