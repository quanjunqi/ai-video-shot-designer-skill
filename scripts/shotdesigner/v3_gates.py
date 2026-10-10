"""Human-review gates for directing, shot, prompt, and video stages."""

from __future__ import annotations


REJECTION_TARGETS = {
    "casting": "casting_brief", "actor": "actor_baseline", "identity": "actor_identity_set",
    "look_plan": "look_state_plan", "look": "look_component", "costume": "costume_worn_view",
    "character_four_view": "character_four_view", "scene_function": "scene_functional_brief",
    "scene_visual": "scene_master",
    "space": "scene_map", "performance": "blocking_plan", "camera": "camera_plan",
    "shot": "shot_plan", "asset": "unit_assets", "prompt": "target_prompt",
    "generation_variance": "generated_video",
}


def _required_arrays(value: object, name: str, fields: tuple[str, ...]) -> list[str]:
    if not isinstance(value, dict):
        return [f"{name} must be an object"]
    missing = [field for field in fields if field not in value]
    if missing:
        return [f"{name} missing fields: {missing}"]
    return [f"{name}.{field} must be an array" for field in fields
            if not isinstance(value.get(field), list)]


def validate_director_analysis(value: object, locked_script_refs: set[str]) -> list[str]:
    fields = ("script_refs", "dramatic_progression", "emotional_curve",
              "character_relationships", "visual_narrative_priorities",
              "continuity_risks", "uncertainties")
    errors = _required_arrays(value, "director analysis", fields)
    if isinstance(value, dict):
        unknown = set(value.get("script_refs", [])) - locked_script_refs
        if unknown:
            errors.append(f"director analysis contains unknown script refs: {sorted(unknown)}")
        forbidden = sorted(set(value) & {"rewrites", "deletions", "added_events", "new_dialogue"})
        if forbidden:
            errors.append(f"director analysis may not alter locked script: {forbidden}")
    return errors


def validate_media_implementation_plan(value: object) -> list[str]:
    fields = ("scene_strategies", "screen_media_strategy", "text_rendering_strategy",
              "vfx_requirements", "sound_requirements", "production_risks", "unknowns")
    errors = _required_arrays(value, "media implementation plan", fields)
    if not isinstance(value, dict) or not isinstance(value.get("scene_strategies"), list):
        return errors
    source_media = {"live_action", "screen_content", "gameplay", "vfx", "mixed"}
    representation_modes = {
        "live_action", "screen_insert", "direct_gameplay", "characterized_performance",
        "composited_vfx", "mixed_media",
    }
    for index, strategy in enumerate(value["scene_strategies"], 1):
        label = f"media implementation plan.scene_strategies[{index}]"
        required = ("scene_id", "script_refs", "source_medium", "representation_mode", "rationale")
        if not isinstance(strategy, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = [field for field in required if not strategy.get(field)]
        if missing:
            errors.append(f"{label} missing fields: {missing}")
            continue
        if not isinstance(strategy["script_refs"], list):
            errors.append(f"{label}.script_refs must be an array")
        if strategy["source_medium"] not in source_media:
            errors.append(f"{label}.source_medium is unsupported")
        if strategy["representation_mode"] not in representation_modes:
            errors.append(f"{label}.representation_mode is unsupported")
        if strategy["source_medium"] == "gameplay" and strategy["representation_mode"] not in {
                "screen_insert", "direct_gameplay", "characterized_performance"}:
            errors.append(f"{label}: gameplay requires an explicit gameplay representation mode")
        if (strategy["source_medium"] == "gameplay"
                and strategy["representation_mode"] == "characterized_performance"
                and strategy.get("approval_required") is not True):
            errors.append(f"{label}: characterized gameplay requires approval_required=true")
    return errors


def validate_production_spec(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["production spec must be an object"]
    required = ("aspect_ratio", "frame_rate", "resolution", "color_pipeline",
                "camera_language", "sound_format", "subtitle_policy", "execution_target")
    missing = [field for field in required if field not in value or value.get(field) in (None, "")]
    return [f"production spec missing fields: {missing}"] if missing else []


def validate_planned_unit_plan(value: object, locked_sequence: list[str]) -> list[str]:
    if not isinstance(value, dict) or value.get("phase") != "PLANNED":
        return ["preliminary unit plan phase must be PLANNED"]
    units = value.get("units")
    if not isinstance(units, list) or not units:
        return ["preliminary unit plan must contain units"]
    errors, coverage = [], []
    for index, unit in enumerate(units, 1):
        uid = unit.get("unit_id", f"units[{index - 1}]") if isinstance(unit, dict) else f"units[{index - 1}]"
        required = ("unit_id", "unit_order", "scene_id", "script_refs", "entry_state",
                    "exit_state", "handoff", "boundary_reason")
        if not isinstance(unit, dict):
            errors.append(f"{uid}: unit must be an object")
            continue
        missing = [field for field in required if field not in unit]
        if missing:
            errors.append(f"{uid}: planned unit missing fields: {missing}")
            continue
        if unit["unit_order"] != index:
            errors.append(f"{uid}: unit_order must be contiguous from 1")
        if not isinstance(unit["script_refs"], list) or not unit["script_refs"]:
            errors.append(f"{uid}: script_refs must be non-empty")
        else:
            coverage.extend(unit["script_refs"])
        if not isinstance(unit["handoff"], dict) or not unit["handoff"].get("to_next"):
            errors.append(f"{uid}: handoff.to_next is required")
        if "shots" in unit or "shot_ids" in unit:
            errors.append(f"{uid}: PLANNED unit must not claim a locked shot design")
    if coverage != locked_sequence:
        errors.append("preliminary unit coverage must exactly preserve locked script order")
    return errors


def validate_editorial_plan(value: object, unit_id: str) -> list[str]:
    if not isinstance(value, dict) or value.get("unit_id") != unit_id:
        return ["editorial plan must bind its unit_id"]
    fields = ("shot_order", "cut_logic", "sound_bridges", "screen_text_cues", "handoff")
    missing = [field for field in fields if field not in value]
    if missing:
        return [f"editorial plan missing fields: {missing}"]
    return [] if all(isinstance(value.get(field), list) for field in fields[:-1]) else [
        "editorial plan shot/cut/sound/text collections must be arrays"]


def validate_executable_unit_plan(value: object, planned: dict, ledger: dict) -> list[str]:
    if not isinstance(value, dict) or value.get("phase") != "EXECUTABLE":
        return ["executable unit plan phase must be EXECUTABLE"]
    if value.get("derived_from") != planned.get("artifact_id"):
        return ["executable unit plan must bind the approved preliminary plan"]
    units = value.get("units")
    if not isinstance(units, list) or not units:
        return ["executable unit plan must contain units"]
    errors = []
    planned_refs = [ref for unit in planned.get("units", []) for ref in unit.get("script_refs", [])]
    executable_refs = []
    for unit in units:
        if not isinstance(unit, dict):
            errors.append("executable units must be objects")
            continue
        uid = unit.get("unit_id")
        required = ("unit_id", "script_refs", "shot_ids", "entry_state", "planned_exit_state",
                    "handoff", "duration_seconds")
        missing = [field for field in required if field not in unit]
        if missing:
            errors.append(f"{uid}: executable unit missing fields: {missing}")
            continue
        executable_refs.extend(unit["script_refs"])
        for artifact_type in ("shot_plan", "editorial_plan"):
            artifact = ledger.get("artifacts", {}).get(f"{artifact_type}:{uid}")
            if not artifact or artifact.get("status") != "USER_APPROVED":
                errors.append(f"{uid}: approved {artifact_type} is required")
        if not unit["shot_ids"]:
            errors.append(f"{uid}: shot_ids must be non-empty")
    if executable_refs != planned_refs:
        errors.append("executable units must preserve preliminary plan script coverage and order")
    return errors


def continuity_source_for_next_unit(unit_id: str, ledger: dict,
                                    planned_exit_state: object) -> dict:
    tail = ledger.get("artifacts", {}).get(f"actual_tailframe:{unit_id}")
    video = ledger.get("artifacts", {}).get(f"generated_video:{unit_id}")
    if tail and tail.get("status") == "USER_APPROVED" and video and video.get("status") == "USER_APPROVED":
        if f"generated_video:{unit_id}" in tail.get("depends_on", []):
            return {"source": "ACTUAL_TAILFRAME", "artifact": tail}
    return {"source": "PLANNED_EXIT_STATE", "state": planned_exit_state}


def require_approved(ledger: dict, keys: list[str]) -> list[str]:
    errors = []
    for key in keys:
        artifact = ledger.get("artifacts", {}).get(key)
        if not artifact or artifact.get("status") != "USER_APPROVED":
            errors.append(f"required approved artifact missing: {key}")
    return errors


def validate_shot_plan(plan: object, locked_script_refs: set[str]) -> list[str]:
    if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list):
        return ["shot plan must contain shots"]
    errors = []
    for shot in plan["shots"]:
        required = ("shot_id", "script_refs", "visible_content", "framing", "camera",
                    "performance", "start_state", "end_state", "cut_reason")
        missing = [field for field in required if field not in shot]
        if missing: errors.append(f"{shot.get('shot_id')}: missing {missing}"); continue
        unknown = set(shot["script_refs"]) - locked_script_refs
        if unknown: errors.append(f"{shot['shot_id']}: unknown script refs {sorted(unknown)}")
    return errors


def validate_unit_delivery(unit: dict, ledger: dict) -> list[str]:
    uid = unit.get("unit_id")
    required = [f"executable_unit_plan:PROJECT", f"shot_plan:{uid}",
                f"editorial_plan:{uid}", f"unit_assets:{uid}", f"target_prompt:{uid}"]
    return require_approved(ledger, required)


def rejection_target(category: str) -> str:
    if category not in REJECTION_TARGETS:
        raise ValueError(f"unsupported rejection category: {category}")
    return REJECTION_TARGETS[category]
