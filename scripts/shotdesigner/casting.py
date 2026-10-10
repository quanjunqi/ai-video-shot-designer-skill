"""Role analysis, casting briefs, neutral actors, and identity reference sets."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re


ROLE_PROFILE_FIELDS = (
    "character_id", "script_refs", "script_facts", "dramatic_function",
    "scene_state_requirements", "performance_requirements", "look_state_clues", "unknowns",
)
CASTING_BRIEF_FIELDS = (
    "character_id", "script_refs", "visible_age", "identity_requirements",
    "physical_requirements", "user_constraints", "director_recommendations",
    "unknowns",
)
# Kept readable for old project files, but deliberately excluded from the new
# casting contract. New projects establish one actor baseline first and only
# derive views when a later shot actually needs them.
LEGACY_CASTING_FIELDS = {"required_identity_views", "identity_view_policy"}
CASTING_FORBIDDEN_FIELDS = {
    "performance_tasks", "performance_requirements", "emotion", "acting_style",
    "hair", "makeup", "costume", "wardrobe", "character_history",
}
SUPPORTED_CANDIDATE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
IDENTITY_APPROVAL_MODES = {"set", "per_view"}
IDENTITY_INPUT_POLICIES = {"atomic_video_input", "character_identity_reference", "review_only"}
IDENTITY_BOARD_POLICIES = {"video_input", "review_only"}


def actor_style_text(value: object) -> str:
    if not isinstance(value, dict):
        return str(value).strip()
    for key in ("prompt", "style", "description", "visual_style"):
        if isinstance(value.get(key), str) and value[key].strip():
            return value[key].strip()
    style_lock = value.get("style_lock")
    if isinstance(style_lock, dict):
        actor_safe_keys = ("medium", "capture_character", "grain_and_sharpness", "finishing")
        parts = []
        for key in actor_safe_keys:
            text = str(style_lock.get(key, "")).strip()
            if not text:
                continue
            if key == "grain_and_sharpness":
                text = text.split("；", 1)[0].strip()
            parts.append(text)
        if parts:
            return "；".join(parts)
    return ""


def _validate_script_refs(value: dict, known_script_refs: set[str]) -> list[str]:
    refs = value.get("script_refs")
    if not isinstance(refs, list) or not refs:
        return ["script_refs must be a non-empty array"]
    unknown = set(refs) - known_script_refs
    return [f"script_refs contain unknown IDs: {sorted(unknown)}"] if unknown else []


def validate_role_profile(profile: object, known_script_refs: set[str]) -> list[str]:
    if not isinstance(profile, dict):
        return ["character role profile must be an object"]
    missing = [field for field in ROLE_PROFILE_FIELDS if field not in profile]
    if missing:
        return [f"character role profile missing fields: {missing}"]
    errors = _validate_script_refs(profile, known_script_refs)
    for field in ROLE_PROFILE_FIELDS[2:]:
        if not isinstance(profile.get(field), list):
            errors.append(f"{field} must be an array")
    return errors


def validate_casting_brief(brief: object, known_script_refs: set[str]) -> list[str]:
    if not isinstance(brief, dict):
        return ["casting brief must be an object"]
    errors = []
    missing = [field for field in CASTING_BRIEF_FIELDS if field not in brief]
    if missing:
        return [f"casting brief missing fields: {missing}"]
    errors.extend(_validate_script_refs(brief, known_script_refs))
    for field in CASTING_BRIEF_FIELDS[3:]:
        if not isinstance(brief.get(field), list):
            errors.append(f"{field} must be an array")
    recommendations = brief.get("director_recommendations", [])
    for item in recommendations if isinstance(recommendations, list) else []:
        if not isinstance(item, dict) or not item.get("field") or not item.get("value") or not item.get("rationale"):
            errors.append("each director recommendation must contain field, value, and rationale")
    forbidden = sorted(field for field in CASTING_FORBIDDEN_FIELDS if field in brief)
    if forbidden:
        errors.append(f"casting brief contains non-casting fields: {forbidden}")
    if brief.get("evaluation") or brief.get("ranking"):
        errors.append("casting brief must not rank or evaluate actors")
    policy = brief.get("identity_view_policy")
    if policy is not None:
        if not isinstance(policy, dict):
            errors.append("identity_view_policy must be an object")
        else:
            if policy.get("mode") not in {"minimal_by_shot_need", "explicit"}:
                errors.append("identity_view_policy.mode is unsupported")
            initial = policy.get("initial_views")
            if not isinstance(initial, list) or any(
                    not isinstance(item, str) or not item.strip() for item in initial):
                errors.append("identity_view_policy.initial_views must be an array of non-empty strings")
            elif len(initial) != len(set(initial)):
                errors.append("identity_view_policy.initial_views must be unique")
            conditional = policy.get("conditional_views", {})
            if not isinstance(conditional, dict) or any(
                    not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip()
                    for key, value in conditional.items()):
                errors.append("identity_view_policy.conditional_views must map view names to reasons")
    return errors


def validate_character_requirement(requirement: object, known_script_refs: set[str]) -> list[str]:
    """Backward-compatible function name; v3.1 content is a casting brief."""
    return validate_casting_brief(requirement, known_script_refs)


def actor_candidate_prompt(requirement: dict, style_lock: str) -> str:
    facts = []
    recommendations = {
        str(item.get("field")): str(item.get("value")).strip()
        for item in requirement.get("director_recommendations", [])
        if isinstance(item, dict) and item.get("field") and item.get("value")
    }
    visible_age = recommendations.get("visible_age", str(requirement.get("visible_age", "")).strip())
    visible_age = re.sub(r"[（(][^）)]*(?:待用户确认|导演建议)[^）)]*[）)]", "", visible_age).strip()
    if visible_age and "未指定" not in visible_age:
        facts.append(f"可视年龄{visible_age}")
    for field in ("identity_requirements", "physical_requirements", "user_constraints"):
        for item in requirement.get(field, []):
            clauses = [clause.strip().rstrip("。") for clause in re.split(r"[；;]", str(item))
                       if clause.strip()]
            facts.extend(
                clause for index, clause in enumerate(clauses)
                if index == 0 or not any(marker in clause for marker in ("剧本", "导演建议", "依据"))
            )
    facts.extend(value for field, value in recommendations.items() if field != "visible_age")
    fact_text = "；".join(dict.fromkeys(str(item) for item in facts)) or "仅按剧本已确认的年龄与身份条件"
    return (
        f"生成一张真人演员基准图。角色编号：{requirement['character_id']}。"
        f"客观选角条件：{fact_text}。视觉质感：{style_lock}。"
        "单人，纯灰色中性无缝背景，中性基础服装，无角色妆容，无角色发型设计，"
        "无职业制服，无剧情道具，无场景家具，无表演动作。自然站立，表情中性，"
        "三分之四全身，双臂自然下垂，双手完全离开衣袋，十指完整可见，鞋完整可见，"
        "面部清晰，可判断稳定身份与身体比例。"
        "single frame, no collage, no split-screen, no text."
    )


def actor_candidate_prompt_package(requirement: dict, style_lock: str, count: int | None = None) -> str:
    """Render the external-generation handoff without prescribing the user's workflow."""
    prompt = actor_candidate_prompt(requirement, style_lock)
    return (
        f"# {requirement.get('character_name') or requirement['character_id']} 演员基准图 Prompt\n\n"
        "## Prompt\n\n"
        f"```text\n{prompt}\n```\n\n"
    )


def validate_candidate_image(path: Path) -> list[str]:
    errors = []
    if not path.is_file():
        return [f"candidate image not found: {path}"]
    if path.suffix.lower() not in SUPPORTED_CANDIDATE_IMAGE_SUFFIXES:
        errors.append(f"unsupported candidate image extension: {path.suffix}")
    if path.stat().st_size == 0:
        errors.append("candidate image is empty")
    try:
        from PIL import Image
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            if min(width, height) < 256:
                errors.append(f"candidate image shortest side is below 256px: {width}x{height}")
            if not image.getbbox():
                errors.append("candidate image has no visible pixels")
    except Exception as exc:
        errors.append(f"candidate image cannot be decoded: {exc}")
    return errors


def validate_actor_identity_set(value: object, ledger: dict, casting_brief: dict) -> list[str]:
    if not isinstance(value, dict):
        return ["actor identity set must be an object"]
    character_id = value.get("character_id")
    views = value.get("views")
    if not character_id or not isinstance(views, list) or not views:
        return ["actor identity set requires character_id and non-empty views"]
    errors = []
    actor = ledger.get("artifacts", {}).get(f"actor_baseline:{character_id}")
    if not actor or actor.get("status") != "USER_APPROVED":
        errors.append("approved actor_baseline is required")
        return errors
    approval_mode = value.get("approval_mode", "per_view")
    if approval_mode not in IDENTITY_APPROVAL_MODES:
        return [f"unsupported identity set approval_mode: {approval_mode}"]
    if approval_mode == "set":
        board = value.get("identity_board")
        if board is not None:
            if not isinstance(board, dict):
                errors.append("identity_board must be an object")
            else:
                for field in ("asset_id", "sha256", "path"):
                    if not board.get(field):
                        errors.append(f"identity_board missing {field}")
                if board.get("upload_policy") not in IDENTITY_BOARD_POLICIES:
                    errors.append("identity_board upload_policy must be video_input or review_only")
                if board.get("upload_policy") == "video_input" and board.get("asset_type") != "actor_identity_sheet":
                    errors.append("video-input identity board must have asset_type actor_identity_sheet")
        elif value.get("board_required") is True:
            errors.append("identity_board is required when board_required is true")
    seen = set()
    for view in views:
        if not isinstance(view, dict):
            errors.append("identity views must be objects")
            continue
        view_type = view.get("view_type")
        if not view_type or view_type in seen:
            errors.append("identity view types must be non-empty and unique")
            continue
        seen.add(view_type)
        if approval_mode == "set":
            for field in ("asset_id", "sha256", "path", "derived_from"):
                if not view.get(field):
                    errors.append(f"identity view missing {field}: {view_type}")
            if view.get("input_policy") != "atomic_video_input":
                errors.append(f"identity view must be atomic_video_input: {view_type}")
            if view.get("approval_scope") != "identity_set":
                errors.append(f"identity view must inherit identity_set approval: {view_type}")
        if view_type == "baseline":
            expected = actor
        else:
            expected = ledger.get("artifacts", {}).get(
                f"actor_identity_view:{character_id}:{view_type}")
        if approval_mode == "per_view":
            if not expected or expected.get("status") != "USER_APPROVED":
                errors.append(f"approved identity view is required: {view_type}")
                continue
            if (view.get("artifact_id"), view.get("sha256")) != (
                    expected.get("artifact_id"), expected.get("sha256")):
                errors.append(f"identity view does not bind approved artifact: {view_type}")
        elif expected and expected.get("status") == "USER_APPROVED" and (
                view.get("asset_id"), view.get("sha256")) != (
                    expected.get("artifact_id"), expected.get("sha256")):
            errors.append(f"identity view does not bind registered artifact: {view_type}")
        if view.get("derived_from") != actor.get("artifact_id"):
            errors.append(f"identity view must derive from actor baseline: {view_type}")
    policy = casting_brief.get("identity_view_policy")
    if isinstance(policy, dict):
        required_views = policy.get("initial_views", [])
    else:
        required_views = casting_brief.get("required_identity_views", [])
    required = set(required_views) | {"baseline"}
    missing = sorted(required - seen)
    if missing:
        errors.append(f"actor identity set missing required views: {missing}")
    return errors


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return "sha256:" + digest


def finalize_batch(character_id: str, batch_id: str, prompt: str,
                   candidates: list[dict], metadata: dict, artifact_root: Path | None = None,
                   depends_on: list[str] | None = None) -> dict:
    normalized = []
    for item in candidates:
        path = Path(item["path"])
        physical_path = artifact_root / path if artifact_root and not path.is_absolute() else path
        if not physical_path.is_file():
            raise ValueError(f"candidate file not found: {path}")
        normalized.append({**item, "sha256": file_sha256(physical_path), "status": "AWAITING_USER"})
    return {"batch_id": batch_id, "character_id": character_id,
            "batch_status": "AWAITING_USER", "prompt": prompt,
            "generation": metadata, "depends_on": list(dict.fromkeys(depends_on or [])),
            "candidates": normalized, "selected_candidate_id": None}


def select_candidate(batch: dict, candidate_id: str,
                     artifact_root: Path | None = None) -> dict:
    if batch.get("batch_status", "AWAITING_USER") != "AWAITING_USER":
        raise ValueError("candidate batch is not awaiting user selection")
    matches = [item for item in batch.get("candidates", [])
               if isinstance(item, dict) and item.get("candidate_id") == candidate_id]
    if len(matches) != 1:
        raise ValueError(f"candidate not found or duplicated: {candidate_id}")
    selected = matches[0]
    if selected.get("status") != "AWAITING_USER":
        raise ValueError("candidate is not awaiting user selection")
    path = Path(selected["path"])
    physical_path = artifact_root / path if artifact_root and not path.is_absolute() else path
    if not physical_path.is_file():
        raise ValueError(f"selected candidate file not found: {path}")
    if file_sha256(physical_path) != selected.get("sha256"):
        raise ValueError(f"selected candidate file hash changed: {path}")
    return {
        "artifact_id": f"actor-{batch['character_id']}-v1",
        "artifact_type": "actor_baseline",
        "scope_id": batch["character_id"],
        "version": 1,
        "sha256": selected["sha256"],
        "path": selected["path"],
        "depends_on": batch.get(
            "depends_on", [f"casting_brief:{batch['character_id']}"]),
        "selected_from": {"batch_id": batch["batch_id"], "candidate_id": candidate_id},
    }
