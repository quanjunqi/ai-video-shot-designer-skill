"""Load and resolve versioned execution adapter configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = ROOT / "config" / "adapters"
REQUIRED_KEYS = {"adapter_id", "prompt_contract", "route", "capabilities", "limits", "prompt"}
ROUTE_KEYS = ("delivery_method", "target_model", "api_platform")


@lru_cache(maxsize=1)
def load_adapters() -> tuple[dict, ...]:
    adapters = []
    contracts = set()
    routes = set()
    for path in sorted(ADAPTER_DIR.glob("*.json")):
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid adapter config {path}: {exc}") from exc
        missing = REQUIRED_KEYS - set(config)
        if missing:
            raise RuntimeError(f"adapter config {path} missing keys: {sorted(missing)}")
        route = config["route"]
        if not isinstance(route, dict) or any(key not in route for key in ROUTE_KEYS):
            raise RuntimeError(f"adapter config {path} has incomplete route")
        route_key = tuple(route[key] for key in ROUTE_KEYS)
        contract = config["prompt_contract"]
        if route_key in routes:
            raise RuntimeError(f"duplicate adapter route: {route_key}")
        if contract in contracts:
            raise RuntimeError(f"duplicate prompt contract: {contract}")
        routes.add(route_key)
        contracts.add(contract)
        config["_source"] = str(path.relative_to(ROOT))
        adapters.append(config)
    if not adapters:
        raise RuntimeError(f"no adapter configs found in {ADAPTER_DIR}")
    return tuple(adapters)


def route_key(delivery_method, target_model, api_platform):
    return delivery_method, target_model, api_platform


def resolve(delivery_method, target_model, api_platform):
    wanted = route_key(delivery_method, target_model, api_platform)
    for config in load_adapters():
        route = config["route"]
        if tuple(route[key] for key in ROUTE_KEYS) == wanted:
            return config
    return None


def by_contract(prompt_contract):
    return next(
        (config for config in load_adapters() if config["prompt_contract"] == prompt_contract),
        None,
    )


def limit(config, name, key=None, default=None):
    value = config.get("limits", {}).get(name) if config else None
    if key is None:
        return value if value is not None else default
    return value.get(key, default) if isinstance(value, dict) else default
