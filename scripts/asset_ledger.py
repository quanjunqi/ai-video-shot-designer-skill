#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
asset_ledger.py — 项目级机器可读图片资产台账。

本脚本用独立的 asset-ledger.json 把 <Subject N>、canonical 资产、派生图和生成单元
串成可验证来源链，避免与 v3 project-ledger.json 的共同创作快照混为同一事实源：

  - 每个资产分配稳定 asset_id（a01、a02…），绑定 H3 标签、kind、模型、视觉状态；
  - 默认用 register-user-file 登记用户在外部模型生成并回传的图片；
  - 同一标签只允许一个有效 canonical；派生图的 derived_from 必须解析到已存在且未失败的源资产；
  - 单元表只登记图片资产规划与必选资产；视频任务、成片、用户决定和实际尾帧来源
    只写入 director workflow manifest。

纯标准库实现，核心逻辑是纯函数，便于 unittest 直接调用。

用法：
  python3 scripts/asset_ledger.py init 片名 [--path P] [--style STYLE-01]
  python3 scripts/asset_ledger.py register-user-file image.png --kind canonical --contract contract.json --tags "Subject 1" --role character
  python3 scripts/asset_ledger.py mark a03 --state 用户确认
  python3 scripts/asset_ledger.py unit 1 --status 待生成 --required "Subject 1,Subject 4"
  python3 scripts/asset_ledger.py validate [--path P]
  python3 scripts/asset_ledger.py show [--json]
默认台账路径：outputs/stage2/metadata/asset-ledger.json。若该文件尚不存在但旧版
project_ledger.json 已存在，则自动读取旧文件；显式 --path 始终优先。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_LEDGER = ROOT / "outputs" / "stage2" / "metadata" / "asset-ledger.json"
LEGACY_LEDGER = ROOT / "outputs" / "stage2" / "metadata" / "project_ledger.json"
DEFAULT_LEDGER = LEGACY_LEDGER if LEGACY_LEDGER.exists() and not ASSET_LEDGER.exists() else ASSET_LEDGER
SCHEMA_VERSION = 2

CANONICAL_MODEL = "gpt-image-2"
DERIVED_MODEL = "nano-banana-2-2k"
CANONICAL_PURPOSE = "canonical-text"
DERIVED_PURPOSE = "reference-derived"
SOURCE_KINDS = {"canonical", "tailframe"}
BLOCKED_STATES = {"失败", "历史失败", "历史失败，禁止复用"}
PASS_STATES = {"用户确认"}
ALL_STATES = {"待视觉确认", "待用户确认", "视觉通过", "用户确认", "失败", "历史失败", "历史失败，禁止复用"}
UNIT_STATES = {"规划锁定", "待生成"}
ASSET_TYPES = {
    "character", "scene", "directional_prop", "screen_text", "environment_state",
    "appearance_state", "game_ip", "vfx_state", "composition_reference",
    "actual_tailframe", "audio",
}
PROMPT_OPERATIONS = {"canonical_create", "reference_edit", "composition_create"}
STYLE_APPLICATIONS = {"project-texture-lock", "inherit-source"}
COMMON_CONTRACT_FIELDS = {
    "asset_type", "identity_scope", "required_view", "required_elements",
    "forbidden_elements", "topology", "state", "variable_regions",
    "usage_scope", "upload_policy", "provenance", "review_contract",
}
SPECIALIZED_CONTRACT_FIELDS = {
    "character": {"identity_invariants", "costume_closed_set", "anatomy_topology",
                  "required_views", "expression_baseline", "environment_prop_exclusions"},
    "scene": {"world_directions", "space_boundary", "fixed_anchors",
              "fixed_furniture_closed_set", "walkable_zones", "forbidden_zones",
              "door_window_states", "light_source_anchors", "occupancy_state", "camera_view"},
    "directional_prop": {"required_visible_surface", "forbidden_visible_surface",
                         "interaction_surface", "orientation", "reading_direction",
                         "allowed_state_transitions"},
    "screen_text": {"physical_carrier_asset_id", "display_region", "allowed_exact_text",
                    "forbidden_extra_text", "same_device_lineage"},
    "environment_state": {"scene_asset_id", "allowed_changes", "fixed_invariants"},
    "appearance_state": {"character_asset_id", "allowed_changes", "identity_invariants"},
    "game_ip": {"gameplay_camera", "map_direction", "ui_regions", "ui_world_separation",
                "character_state", "event_order", "conversion_forbidden"},
    "vfx_state": {"source_entity_asset_id", "trigger", "intensity_curve", "effect_radius",
                  "environment_response", "end_state"},
    "composition_reference": {"shot_id", "scene_id", "canonical_asset_ids"},
    "actual_tailframe": {"source_unit_id", "source_video_asset_id", "timestamp", "frame_hash"},
    "audio": {"source_identity", "content_scope", "duration_seconds", "channels"},
}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _model_policy() -> dict:
    load_dotenv(ROOT / ".env")
    return {
        "text_model": os.getenv("PEARAPI_TEXT_MODEL", CANONICAL_MODEL),
        "reference_model": os.getenv("PEARAPI_REFERENCE_MODEL", DERIVED_MODEL),
    }


def new_ledger(project: str, style_lock: str = "STYLE-01") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "style_lock": style_lock,
        "model_policy": _model_policy(),
        "assets": {},
        "units": {},
    }


def load_ledger(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_ledger(ledger: dict, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def ledger_lock(path):
    """Serialize each CLI read-modify-write transaction for one ledger."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _next_asset_id(ledger: dict) -> str:
    nums = [int(m.group(1)) for a in ledger["assets"] if (m := re.fullmatch(r"a(\d+)", a))]
    return f"a{(max(nums) + 1 if nums else 1):02d}"


def _all_refs(asset: dict):
    return list(asset.get("source_urls", [])) + list(asset.get("local_files", [])) + [asset["asset_id"]]


def resolve_source(ledger: dict, ref: str):
    """把一个来源引用（URL / 本地路径 / asset_id）解析到台账资产，找不到返回 None。"""
    ref = (ref or "").strip()
    if not ref:
        return None
    for asset in ledger["assets"].values():
        if ref == asset["asset_id"] or ref in asset.get("source_urls", []) or ref in asset.get("local_files", []):
            return asset["asset_id"]
    return None


def _classify(model: str, purpose: str, policy: dict | None = None) -> str:
    policy = policy or _model_policy()
    if model == policy["text_model"] and purpose == CANONICAL_PURPOSE:
        return "canonical"
    if model == policy["reference_model"] and purpose == DERIVED_PURPOSE:
        return "derived"
    return "unknown"


def _identity_keys(tags, role):
    tags = sorted(tags or [])
    return tuple(tags) if tags else (f"role:{role or 'unknown'}",)


def find_canonical_identities(ledger: dict):
    """返回 {(tags/role): [asset_id,...]}，只统计未被历史失败取代的 canonical。"""
    table = {}
    for asset in ledger["assets"].values():
        if asset["kind"] != "canonical" or asset.get("visual_state") in BLOCKED_STATES:
            continue
        key = tuple(asset.get("identity", []))
        table.setdefault(key, []).append(asset["asset_id"])
    return table


def register_from_metadata(ledger: dict, metadata: dict, tags=(), role=None,
                           visual_state="待视觉确认", allow_orphan=False,
                           asset_contract=None):
    """从 pearapi result.json 登记一项资产，返回 (asset_id, report)。失败抛 ValueError。"""
    req = metadata.get("_request", {}) if isinstance(metadata, dict) else {}
    model, purpose = req.get("model"), req.get("purpose")
    kind = _classify(model, purpose, ledger.get("model_policy"))
    if kind == "unknown":
        raise ValueError(f"无法识别的模型/用途组合：model={model!r}, purpose={purpose!r}")

    source_urls = []
    for item in metadata.get("data", []) if isinstance(metadata.get("data"), list) else []:
        if isinstance(item, dict) and item.get("url"):
            source_urls.append(item["url"])
    raw_sources = req.get("source_images") or req.get("derived_from") or []
    if isinstance(raw_sources, str):
        raw_sources = [raw_sources]

    identity = list(_identity_keys(tags, role))
    report = {"kind": kind, "resolved": [], "unresolved": [], "errors": []}

    if kind == "canonical" and raw_sources:
        raise ValueError("canonical 文生图不应携带来源图片，携带来源说明它不是纯文生 canonical")
    if kind == "derived" and not raw_sources:
        raise ValueError("派生图必须至少携带一个实际来源图片引用")

    # canonical 身份唯一：同一标签不得重复建立有效 canonical（独立重画同一身份）。
    if kind == "canonical":
        existing = find_canonical_identities(ledger)
        clash = existing.get(tuple(identity), [])
        if clash:
            raise ValueError(f"标签/身份 {identity} 已存在 canonical 资产 {clash}；"
                             "禁止用文生图独立重画同一身份，如需换版请先把旧版标记为历史失败")

    resolved = []
    if kind == "derived":
        for ref in raw_sources:
            asset_id = resolve_source(ledger, ref)
            if asset_id is None:
                report["unresolved"].append(ref)
                continue
            source = ledger["assets"][asset_id]
            if source["kind"] not in SOURCE_KINDS:
                report["errors"].append(f"来源 {asset_id} 的 kind={source['kind']}，派生图只允许来自 canonical/尾帧")
            if source.get("visual_state") in BLOCKED_STATES:
                report["errors"].append(f"来源 {asset_id} 处于 {source.get('visual_state')}，禁止作为派生来源")
            resolved.append(asset_id)
        if report["unresolved"] and not allow_orphan:
            raise ValueError("以下来源未在台账登记，无法构成可追溯来源链：" + "；".join(report["unresolved"]))
        if report["errors"]:
            raise ValueError("；".join(report["errors"]))

    asset_id = _next_asset_id(ledger)
    asset = {
        "asset_id": asset_id,
        "kind": kind,
        "identity": identity,
        "tags": sorted(set(tags or [])),
        "role": role,
        "model": model,
        "purpose": purpose,
        "source_urls": sorted(set(source_urls)),
        "raw_sources": list(raw_sources),
        "derived_from": resolved,
        "unresolved_sources": report["unresolved"],
        "local_files": metadata.get("local_files", []) if isinstance(metadata, dict) else [],
        "shot": req.get("shot"),
        "style": ledger.get("style_lock", "STYLE-01"),
        "visual_state": visual_state,
        "asset_contract": asset_contract,
    }
    ledger["assets"][asset_id] = asset
    report["asset_id"] = asset_id
    report["resolved"] = resolved
    return asset_id, report


def register_user_file(ledger: dict, path: Path, kind: str, tags=(), role=None,
                       source_ids=(), asset_contract=None, model_label="user-selected"):
    """Register an image generated and judged outside the Skill."""
    if kind not in {"canonical", "derived"}:
        raise ValueError("用户回传图片 kind 只能是 canonical 或 derived")
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"用户回传文件不存在：{path}")
    identity = list(_identity_keys(tags, role))
    if kind == "canonical":
        clash = find_canonical_identities(ledger).get(tuple(identity), [])
        if clash:
            raise ValueError(f"标签/身份 {identity} 已存在有效 canonical 资产 {clash}")
        if source_ids:
            raise ValueError("canonical 用户回传图不应声明派生来源")
    resolved = []
    if kind == "derived":
        if not source_ids:
            raise ValueError("derived 用户回传图必须声明至少一个来源 asset_id")
        for source_id in source_ids:
            source = ledger.get("assets", {}).get(source_id)
            if source is None:
                raise ValueError(f"用户回传图来源不存在：{source_id}")
            if source.get("visual_state") in BLOCKED_STATES:
                raise ValueError(f"用户回传图来源 {source_id} 已失败，禁止派生")
            resolved.append(source_id)
    asset_id = _next_asset_id(ledger)
    contract = dict(asset_contract or {})
    provenance = dict(contract.get("provenance") or {})
    provenance["derived_from"] = resolved
    if kind == "canonical":
        provenance["lineage_root_asset_id"] = asset_id
    contract["provenance"] = provenance
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    ledger["assets"][asset_id] = {
        "asset_id": asset_id,
        "kind": kind,
        "identity": identity,
        "tags": sorted(set(tags or [])),
        "role": role,
        "model": model_label,
        "purpose": "user-generated",
        "generation_owner": "user",
        "source_urls": [],
        "raw_sources": list(source_ids),
        "derived_from": resolved,
        "unresolved_sources": [],
        "local_files": [str(path)],
        "file_sha256": digest,
        "shot": None,
        "style": ledger.get("style_lock", "STYLE-01"),
        "visual_state": "待用户确认",
        "asset_contract": contract,
    }
    return asset_id, digest


def upsert_unit(ledger: dict, unit, status=None, required=None, timeline=None,
                video_asset=None, decision_statement=None, decided_at=None):
    entry = ledger["units"].setdefault(str(unit), {})
    if video_asset or decision_statement or decided_at:
        raise ValueError("图片资产台账不记录视频任务或用户决定；请写入 director workflow manifest")
    if status:
        if status not in UNIT_STATES:
            raise ValueError(f"非法图片台账单元状态：{status}；视频状态由 director workflow manifest 管理")
        entry["status"] = status
    if required is not None:
        entry["required"] = required
    if timeline:
        entry["timeline"] = timeline
    return entry


def mark_state(ledger: dict, asset_id: str, state: str):
    if asset_id not in ledger["assets"]:
        raise KeyError(f"台账不存在资产 {asset_id}")
    if state not in ALL_STATES:
        raise ValueError(f"非法视觉状态：{state}")
    ledger["assets"][asset_id]["visual_state"] = state
    return ledger["assets"][asset_id]


def validate_asset_contract(asset: dict):
    """Validate a semantic asset contract without pretending to inspect pixels."""
    issues = []
    aid = asset.get("asset_id", "<unknown>")
    contract = asset.get("asset_contract")
    if not isinstance(contract, dict):
        return [("asset-contract-missing", f"{aid} 缺少机器可读 asset_contract")]
    missing = sorted(COMMON_CONTRACT_FIELDS - set(contract))
    if missing:
        issues.append(("asset-contract-incomplete", f"{aid} 通用资产契约缺少字段: {missing}"))
        return issues
    asset_type = contract.get("asset_type")
    if asset_type not in ASSET_TYPES:
        issues.append(("asset-contract-type-invalid", f"{aid} asset_type 非法: {asset_type!r}"))
        return issues
    specialized_missing = sorted(SPECIALIZED_CONTRACT_FIELDS[asset_type] - set(contract))
    if specialized_missing:
        issues.append(("asset-contract-specialized-incomplete",
                       f"{aid} 的 {asset_type} 契约缺少字段: {specialized_missing}"))

    operation = contract.get("prompt_operation")
    style_application = contract.get("style_application")
    if operation is not None or style_application is not None:
        if operation not in PROMPT_OPERATIONS:
            issues.append(("asset-contract-prompt-operation-invalid",
                           f"{aid} prompt_operation 非法: {operation!r}"))
        if style_application not in STYLE_APPLICATIONS:
            issues.append(("asset-contract-style-application-invalid",
                           f"{aid} style_application 非法: {style_application!r}"))
        if operation == "canonical_create" and style_application != "project-texture-lock":
            issues.append(("asset-contract-canonical-style-invalid",
                           f"{aid} canonical_create 必须使用 project-texture-lock"))
        if operation == "reference_edit" and style_application != "inherit-source":
            issues.append(("asset-contract-reference-style-invalid",
                           f"{aid} reference_edit 必须使用 inherit-source，不得重新注入全局风格锁"))

    required = set(contract.get("required_elements") or [])
    forbidden = set(contract.get("forbidden_elements") or [])
    if required & forbidden:
        issues.append(("asset-contract-element-conflict",
                       f"{aid} 同时要求并禁止元素: {sorted(required & forbidden)}"))
    topology = contract.get("topology")
    if not isinstance(topology, dict) or not isinstance(topology.get("object_count"), int) \
            or topology.get("object_count", 0) < 1:
        issues.append(("asset-contract-topology-invalid", f"{aid} topology.object_count 必须为正整数"))
        topology = topology if isinstance(topology, dict) else {}
    visible = set(topology.get("visible_surfaces") or [])
    for group in topology.get("mutually_exclusive_surface_groups") or []:
        overlap = visible & set(group if isinstance(group, list) else [])
        if len(overlap) > 1:
            issues.append(("asset-contract-mutually-exclusive-surfaces",
                           f"{aid} 单张资产同时声明互斥可见面: {sorted(overlap)}"))
    required_surface = set(contract.get("required_visible_surface") or [])
    forbidden_surface = set(contract.get("forbidden_visible_surface") or [])
    if required_surface - visible:
        issues.append(("asset-contract-required-surface-missing",
                       f"{aid} topology.visible_surfaces 缺少所需可见面: {sorted(required_surface - visible)}"))
    if visible & forbidden_surface:
        issues.append(("asset-contract-forbidden-surface-visible",
                       f"{aid} 声明了禁止出现的可见面: {sorted(visible & forbidden_surface)}"))

    provenance = contract.get("provenance")
    if not isinstance(provenance, dict) or "lineage_root_asset_id" not in provenance \
            or "derived_from" not in provenance:
        issues.append(("asset-contract-provenance-incomplete", f"{aid} provenance 缺少谱系根或来源"))
    elif set(provenance.get("derived_from") or []) != set(asset.get("derived_from") or []):
        issues.append(("asset-contract-provenance-drift", f"{aid} 契约来源与台账 derived_from 不一致"))

    upload = contract.get("upload_policy")
    if not isinstance(upload, dict) or upload.get("mode") not in {
            "identity-only", "lineage-final-only", "conditional", "never-video-input"}:
        issues.append(("asset-contract-upload-policy-invalid", f"{aid} upload_policy.mode 非法"))

    review = contract.get("review_contract")
    if not isinstance(review, dict):
        issues.append(("asset-contract-review-missing", f"{aid} 缺少 review_contract"))
        return issues
    if asset.get("visual_state") in PASS_STATES:
        user = review.get("user_confirmation")
        if review.get("file_check") != "passed":
            issues.append(("asset-contract-file-proof-incomplete",
                           f"{aid} 已由用户确认，但程序文件检查未通过"))
        if not isinstance(user, dict) or user.get("status") != "confirmed" \
                or not user.get("statement") or not user.get("file_sha256"):
            issues.append(("asset-contract-user-confirmation-incomplete",
                           f"{aid} 缺少绑定文件哈希的用户确认"))
    user = review.get("user_confirmation")
    return issues


def validate_ledger(ledger: dict):
    """全量一致性校验，返回 [(level, code, msg)]。"""
    issues = []
    err = lambda c, m: issues.append(("ERROR", c, m))
    warn = lambda c, m: issues.append(("WARNING", c, m))
    assets = ledger.get("assets", {})

    # L1/L5 来源链与模型路由
    expected_style = ledger.get("style_lock")
    for aid, asset in assets.items():
        # 已隔离的历史失败资产是“墓碑”：它本身已被禁止使用，不再对其模型路由/
        # 来源链重复报生产可用性错误（失败回归样本可保留在台账中供回溯）。
        if asset.get("visual_state") in BLOCKED_STATES:
            continue
        for code, message in validate_asset_contract(asset):
            err(code, message)
        kind, model = asset["kind"], asset.get("model")
        if expected_style and asset.get("style") != expected_style:
            err("style-mismatch", f"{aid} 的风格锁为 {asset.get('style')}，应为项目锁定的 {expected_style}")
        policy = ledger.get("model_policy") or _model_policy()
        if kind == "canonical" and asset.get("generation_owner") != "user" \
                and model != policy["text_model"]:
            err("canonical-model", f"{aid} 是 canonical 但模型为 {model}，应为 {policy['text_model']}")
        if kind == "derived":
            if asset.get("generation_owner") != "user" and model != policy["reference_model"]:
                err("derived-model", f"{aid} 是派生图但模型为 {model}，应为 {policy['reference_model']}")
            if not asset.get("derived_from") and not asset.get("unresolved_sources"):
                err("derived-no-source", f"{aid} 是派生图却没有解析到任何来源资产")
            for src in asset.get("unresolved_sources", []):
                err("derived-orphan-source", f"{aid} 来源未登记到台账：{src}")
            for src_id in asset.get("derived_from", []):
                src = assets.get(src_id)
                if src is None:
                    err("source-missing", f"{aid} 的来源 {src_id} 在台账中不存在")
                    continue
                if src["kind"] not in SOURCE_KINDS:
                    err("source-kind", f"{aid} 的来源 {src_id} kind={src['kind']}，应为 canonical/tailframe")
                if src.get("visual_state") in BLOCKED_STATES:
                    err("source-blocked", f"{aid} 的来源 {src_id} 处于 {src.get('visual_state')}，禁止派生")

    # 根资产失败后，所有后代无论自身状态如何都必须失效。
    for aid, asset in assets.items():
        if asset.get("visual_state") in BLOCKED_STATES:
            continue
        stack = list(asset.get("derived_from", []))
        seen = set()
        while stack:
            source_id = stack.pop()
            if source_id in seen:
                continue
            seen.add(source_id)
            source = assets.get(source_id)
            if not source:
                continue
            if source.get("visual_state") in BLOCKED_STATES:
                err("ancestor-blocked", f"{aid} 的上游资产 {source_id} 已失败，当前资产必须失效并重新派生")
                break
            stack.extend(source.get("derived_from", []))

    # L2 canonical 身份唯一
    for identity, ids in find_canonical_identities(ledger).items():
        if len(ids) > 1:
            err("duplicate-canonical-identity", f"身份 {list(identity)} 存在多个有效 canonical：{ids}，疑似独立重画同一角色/场景")

    # 标签 → 资产可解析
    tag_to_assets = {}
    for aid, asset in assets.items():
        for tag in asset.get("tags", []):
            tag_to_assets.setdefault(tag, []).append(aid)

    units = ledger.get("units", {})
    ordered = sorted(units, key=lambda x: int(x) if str(x).isdigit() else 999)
    for index, unum in enumerate(ordered):
        entry = units[unum]
        if entry.get("status") not in UNIT_STATES:
            err("unit-video-state-forbidden",
                f"单元{unum} 含视频生产状态 {entry.get('status')!r}；用户决定只能写入 director workflow manifest")
        for field in ("video_asset", "decision_statement", "decided_at"):
            if entry.get(field):
                err("unit-video-authority-duplicate",
                    f"单元{unum} 的 {field} 不得写入图片资产台账")
        for tag in entry.get("required", []):
            candidates = tag_to_assets.get(tag, [])
            if not candidates:
                err("unit-required-missing", f"单元{unum} 必选标签 {tag} 在台账无对应资产")
            elif not any(assets[c].get("visual_state") in PASS_STATES for c in candidates):
                err("unit-asset-not-approved", f"单元{unum} 必选 {tag} 尚未由用户确认")
    return issues


# --------------------------- CLI ---------------------------

def _parse_tags(raw):
    if not raw:
        return []
    return [piece.strip() for piece in re.split(r"[,，、;；]", raw) if piece.strip()]


def main():
    # --path 放在 parent 上，使 `cmd --path X` 与 `--path X cmd` 两种写法都可用。
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--path", type=Path, default=DEFAULT_LEDGER, help="图片资产台账 JSON 路径")
    ap = argparse.ArgumentParser(description="项目级资产台账")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", parents=[parent])
    p_init.add_argument("project")
    p_init.add_argument("--style", default="STYLE-01")
    p_init.add_argument("--force", action="store_true")

    p_reg = sub.add_parser("register", parents=[parent])
    p_reg.add_argument("metadata", type=Path)
    p_reg.add_argument("--tags", default="")
    p_reg.add_argument("--role")
    p_reg.add_argument("--state", default="待视觉确认")
    p_reg.add_argument("--allow-orphan", action="store_true")
    p_reg.add_argument("--contract", type=Path, help="asset_contract JSON 文件")

    p_user = sub.add_parser("register-user-file", parents=[parent])
    p_user.add_argument("file", type=Path)
    p_user.add_argument("--kind", choices=("canonical", "derived"), required=True)
    p_user.add_argument("--tags", default="")
    p_user.add_argument("--role")
    p_user.add_argument("--source", default="", help="derived 来源 asset_id，逗号分隔")
    p_user.add_argument("--contract", type=Path, required=True)
    p_user.add_argument("--model-label", default="user-selected")

    p_mark = sub.add_parser("mark", parents=[parent])
    p_mark.add_argument("asset")
    p_mark.add_argument("--state", required=True)

    p_contract = sub.add_parser("attach-contract", parents=[parent])
    p_contract.add_argument("asset")
    p_contract.add_argument("contract", type=Path)

    p_unit = sub.add_parser("unit", parents=[parent])
    p_unit.add_argument("unit", type=int)
    p_unit.add_argument("--status")
    p_unit.add_argument("--required", default="")
    p_unit.add_argument("--timeline")
    p_unit.add_argument("--video-asset")
    p_unit.add_argument("--decision-statement")
    p_unit.add_argument("--decided-at")

    p_val = sub.add_parser("validate", parents=[parent])
    p_val.add_argument("--json", action="store_true")
    p_show = sub.add_parser("show", parents=[parent])
    p_show.add_argument("--json", action="store_true")

    args = ap.parse_args()

    with ledger_lock(args.path):
        if args.cmd == "init":
            if args.path.exists() and not args.force:
                raise SystemExit(f"台账已存在：{args.path}（--force 覆盖）")
            save_ledger(new_ledger(args.project, args.style), args.path)
            print(f"已初始化台账：{args.path}")
            return

        if not args.path.exists():
            raise SystemExit(f"台账不存在：{args.path}，请先 init")
        ledger = load_ledger(args.path)

        if args.cmd == "register":
            meta = json.loads(args.metadata.read_text(encoding="utf-8"))
            try:
                contract = json.loads(args.contract.read_text(encoding="utf-8")) if args.contract else None
                asset_id, report = register_from_metadata(
                    ledger, meta, tags=_parse_tags(args.tags), role=args.role,
                    visual_state=args.state, allow_orphan=args.allow_orphan,
                    asset_contract=contract)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise SystemExit(f"登记失败：{exc}")
            save_ledger(ledger, args.path)
            print(f"已登记 {asset_id}（{report['kind']}）来源解析={report['resolved']} 未解析={report['unresolved']}")
        elif args.cmd == "register-user-file":
            try:
                contract = json.loads(args.contract.read_text(encoding="utf-8"))
                asset_id, digest = register_user_file(
                    ledger, args.file, args.kind, tags=_parse_tags(args.tags), role=args.role,
                    source_ids=_parse_tags(args.source), asset_contract=contract,
                    model_label=args.model_label)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise SystemExit(f"登记用户回传图片失败：{exc}")
            save_ledger(ledger, args.path)
            print(f"已登记用户回传图片 {asset_id}（{args.kind}）{digest}，等待用户确认")
        elif args.cmd == "mark":
            try:
                mark_state(ledger, args.asset, args.state)
            except (KeyError, ValueError) as exc:
                raise SystemExit(f"标记失败：{exc}")
            save_ledger(ledger, args.path)
            print(f"{args.asset} 视觉状态 → {args.state}")
        elif args.cmd == "attach-contract":
            if args.asset not in ledger["assets"]:
                raise SystemExit(f"台账不存在资产 {args.asset}")
            try:
                contract = json.loads(args.contract.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit(f"读取契约失败：{exc}")
            ledger["assets"][args.asset]["asset_contract"] = contract
            save_ledger(ledger, args.path)
            print(f"{args.asset} 已绑定资产契约：{args.contract}")
        elif args.cmd == "unit":
            try:
                upsert_unit(
                    ledger, args.unit, status=args.status,
                    required=_parse_tags(args.required) or None, timeline=args.timeline,
                    video_asset=args.video_asset,
                    decision_statement=args.decision_statement,
                    decided_at=args.decided_at,
                )
            except ValueError as exc:
                raise SystemExit(f"更新失败：{exc}")
            save_ledger(ledger, args.path)
            print(f"单元{args.unit} 已更新")
        elif args.cmd == "show":
            if args.json:
                print(json.dumps(ledger, ensure_ascii=False, indent=2))
            else:
                print(f"项目：{ledger.get('project')}｜资产 {len(ledger['assets'])} 项｜单元 {len(ledger['units'])} 个")
                for aid, a in sorted(ledger["assets"].items()):
                    print(f"  {aid} {a['kind']:<9} {a.get('tags')} {a.get('model')} -> {a.get('derived_from')} [{a.get('visual_state')}]")
        elif args.cmd == "validate":
            issues = validate_ledger(ledger)
            errs = [i for i in issues if i[0] == "ERROR"]
            if args.json:
                payload = {
                    "path": str(args.path),
                    "errors": [{"code": c, "message": m} for _, c, m in issues if _ == "ERROR"],
                    "warnings": [{"code": c, "message": m} for _, c, m in issues if _ == "WARNING"],
                }
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                for level, code, msg in issues:
                    print(f"  {level:<7} {code}: {msg}")
                print("-" * 48)
                print(f"汇总：ERROR={len(errs)} WARNING={len(issues) - len(errs)}")
            sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
