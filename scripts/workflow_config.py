"""Load workflow state, gate, and schema capability configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config" / "workflow"


def _load(name):
    path = CONFIG_DIR / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid workflow config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"workflow config {path} must be an object")
    return value


@lru_cache(maxsize=1)
def state_config():
    config = _load("states.json")
    states = config.get("states")
    transitions = config.get("transitions")
    required = config.get("required_fields_by_gate")
    if not isinstance(states, list) or not states or len(states) != len(set(states)):
        raise RuntimeError("workflow states must be a non-empty unique list")
    if not isinstance(transitions, dict) or set(transitions) != set(states):
        raise RuntimeError("workflow transitions must define every state exactly once")
    unknown_targets = {
        target for targets in transitions.values() for target in targets if target not in states
    }
    if unknown_targets:
        raise RuntimeError(f"workflow transitions contain unknown states: {sorted(unknown_targets)}")
    if not isinstance(required, dict) or any(gate not in states for gate in required):
        raise RuntimeError("required_fields_by_gate contains an unknown gate")
    return config


@lru_cache(maxsize=1)
def version_config():
    config = _load("versions.json")
    current = config.get("current_schema_version")
    capabilities = config.get("capabilities")
    if not current or not isinstance(capabilities, dict) or current not in capabilities:
        raise RuntimeError("workflow version config does not define current capabilities")
    return config


def states():
    return tuple(state_config()["states"])


def state_at_least(state, minimum):
    ordered = states()
    return state in ordered and minimum in ordered and ordered.index(state) >= ordered.index(minimum)


def can_transition(current, target):
    transitions = state_config()["transitions"]
    return current in transitions and target in transitions[current]


def required_fields_for(state):
    config = state_config()
    fields = list(config["base_required_fields"])
    if state in states():
        for gate, required in config["required_fields_by_gate"].items():
            if state_at_least(state, gate):
                fields.extend(required)
    return tuple(dict.fromkeys(fields))


def schema_capabilities(version):
    key = "1.x" if str(version).startswith("1.") else str(version)
    return frozenset(version_config()["capabilities"].get(key, ()))
