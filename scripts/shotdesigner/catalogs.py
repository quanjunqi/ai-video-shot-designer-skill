"""Load director strategy catalogs once for validator modules."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "config" / "directing"


def _load(name):
    path = CATALOG_DIR / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid strategy catalog {path}: {exc}") from exc
    entries = value.get("strategies") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError(f"strategy catalog {path} must contain strategies[]")
    result = {}
    for item in entries:
        if not isinstance(item, dict) or not item.get("id"):
            raise RuntimeError(f"strategy catalog {path} contains an invalid entry")
        if item["id"] in result:
            raise RuntimeError(f"strategy catalog {path} repeats id={item['id']}")
        result[item["id"]] = item
    return result


@lru_cache(maxsize=1)
def shot_strategies():
    return _load("shot-strategies.json")


@lru_cache(maxsize=1)
def coverage_strategies():
    return _load("coverage-strategies.json")
