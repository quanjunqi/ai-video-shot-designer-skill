#!/usr/bin/env python3
"""Generate and select v3 look-development and scene-design candidates."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil

from shotdesigner.casting import file_sha256, validate_candidate_image
from shotdesigner.context_runtime import prepare_context
from shotdesigner.image_generation import ImageGenerationService
from shotdesigner.ledgers.project import apply_review, register_artifact
from shotdesigner.ledgers.reviews import append_review, create_review
from shotdesigner.lookdev import (
    component_is_declared, costume_structure_prompt, fusable_component_types,
    fusion_prompt, validate_component, validate_costume_structure_design,
    validate_fusion_sources, validate_four_view_spec, validate_look_state_plan,
)
from shotdesigner.scene_design import validate_scene_functional_brief


COMPONENT_MODES = {
    "look-component": ("look_component", None),
    "costume-structure": ("costume_structure", "costume"),
    "fabric-detail": ("fabric_detail", "costume"),
    "costume-worn-view": ("costume_worn_view", "costume"),
    "costume-reference": ("costume_reference_analysis", "costume"),
    "hair-batch": ("hair_batch", "hair"),
    "makeup-batch": ("makeup_batch", "makeup"),
    "accessory-batch": ("accessory_batch", "accessories"),
}
WORKFLOW_MODES = ("actor-identity-view", *COMPONENT_MODES, "character-fusion",
                  "character-four-view", "character-atomic-view", "scene-master", "scene-view")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def inside(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError as exc:
        raise SystemExit(f"path must stay inside project root: {path}") from exc


def approved(ledger, key):
    item = ledger.get("artifacts", {}).get(key)
    if not item or item.get("status") != "USER_APPROVED":
        raise SystemExit(f"approved upstream artifact required: {key}")
    return item


def approved_file(ledger, key, root: Path):
    item = approved(ledger, key)
    path = root / item.get("path", "")
    inside(root, path)
    if not path.is_file() or file_sha256(path) != item.get("sha256"):
        raise SystemExit(f"approved upstream artifact file changed: {key}")
    return item, path


def style_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(value, dict):
        for key in ("prompt", "style", "description", "visual_style"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def candidate_batch(root, batch_id, output_type, scope_id, prompt, candidates, metadata, deps,
                    context=None):
    normalized = []
    for item in candidates:
        path = Path(item["path"])
        normalized.append({**item, "path": inside(root, path), "sha256": file_sha256(path),
                           "status": "AWAITING_USER"})
    return {"batch_id": batch_id, "output_artifact_type": output_type, "scope_id": scope_id,
            "prompt": prompt, "generation": metadata, "depends_on": deps,
            "candidates": normalized, "selected_candidate_id": None, "context": context}


def prompt_package(mode, scope_id, prompt, refs, count):
    reference_section = "无。此项为纯文本生成。"
    if refs:
        reference_section = "\n".join(
            f"{index}. `{path}`" for index, path in enumerate(refs, 1))
    return (
        f"# {scope_id} 视觉资产 Prompt\n\n"
        f"类型：`{mode}`\n\n"
        "## 参考图片\n\n"
        f"{reference_section}\n\n"
        "## Prompt\n\n"
        f"```text\n{prompt}\n```\n\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("mode", choices=WORKFLOW_MODES)
    gen.add_argument("spec", type=Path)
    gen.add_argument("project_ledger", type=Path)
    gen.add_argument("batch", type=Path)
    gen.add_argument("output_dir", type=Path)
    gen.add_argument("--project-root", type=Path, required=True)
    gen.add_argument("--count", type=int, default=4)
    gen.add_argument("--style", default="")

    export = sub.add_parser("export-prompt")
    export.add_argument("mode", choices=WORKFLOW_MODES)
    export.add_argument("spec", type=Path)
    export.add_argument("project_ledger", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--project-root", type=Path, required=True)
    export.add_argument("--count", type=int, default=4)

    imp = sub.add_parser("import-candidates")
    imp.add_argument("mode", choices=WORKFLOW_MODES)
    imp.add_argument("spec", type=Path)
    imp.add_argument("project_ledger", type=Path)
    imp.add_argument("batch", type=Path)
    imp.add_argument("output_dir", type=Path)
    imp.add_argument("files", nargs="+", type=Path)
    imp.add_argument("--project-root", type=Path, required=True)

    sel = sub.add_parser("select")
    sel.add_argument("batch", type=Path); sel.add_argument("candidate_id")
    sel.add_argument("project_ledger", type=Path); sel.add_argument("review_ledger", type=Path)
    sel.add_argument("review_id"); sel.add_argument("user_statement")
    sel.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "select":
        inside(args.project_root, args.batch)
        inside(args.project_root, args.project_ledger)
        inside(args.project_root, args.review_ledger)
        batch, ledger = read(args.batch), read(args.project_ledger)
        if batch.get("selected_candidate_id"):
            raise SystemExit("candidate batch already has a user selection")
        candidate = next((item for item in batch["candidates"]
                          if item["candidate_id"] == args.candidate_id), None)
        if not candidate:
            raise SystemExit("candidate not found")
        if candidate.get("status") != "AWAITING_USER":
            raise SystemExit("candidate is not awaiting user selection")
        candidate_path = args.project_root / candidate["path"]
        inside(args.project_root, candidate_path)
        if not candidate_path.is_file() or file_sha256(candidate_path) != candidate.get("sha256"):
            raise SystemExit("selected candidate file is missing or changed")
        key = f"{batch['output_artifact_type']}:{batch['scope_id']}"
        current = ledger.get("artifacts", {}).get(key)
        version = current["version"] + 1 if current else 1
        artifact_id = f"{batch['output_artifact_type']}-{batch['scope_id'].replace(':', '-')}-v{version}"
        ledger = register_artifact(
            ledger, artifact_id=artifact_id, artifact_type=batch["output_artifact_type"],
            scope_id=batch["scope_id"], version=version, sha256=candidate["sha256"],
            path=candidate["path"], depends_on=batch.get("depends_on", []))
        event = create_review(
            review_id=args.review_id, artifact_id=artifact_id,
            artifact_type=batch["output_artifact_type"], scope_id=batch["scope_id"],
            artifact_version=version, artifact_sha256=candidate["sha256"],
            decision="select_candidate", user_statement=args.user_statement)
        ledger = apply_review(ledger, event); append_review(args.review_ledger, event)
        batch["selected_candidate_id"] = args.candidate_id
        for item in batch["candidates"]:
            item["status"] = "USER_SELECTED" if item is candidate else "NOT_SELECTED"
        write(args.batch, batch); write(args.project_ledger, ledger)
        print(json.dumps({"artifact_id": artifact_id, "sha256": candidate["sha256"]}, ensure_ascii=False))
        return 0

    inside(args.project_root, args.spec)
    inside(args.project_root, args.project_ledger)
    spec, ledger = read(args.spec), read(args.project_ledger)
    if args.command != "export-prompt":
        inside(args.project_root, args.batch); inside(args.project_root, args.output_dir)
    refs, deps = [], []
    if args.mode == "actor-identity-view":
        cid, view_type = spec.get("character_id"), spec.get("view_type")
        if not cid or not view_type or not isinstance(spec.get("requirements"), list):
            raise SystemExit("actor identity view requires character_id, view_type, and requirements")
        _, actor_path = approved_file(ledger, f"actor_baseline:{cid}", args.project_root)
        approved_file(ledger, f"casting_brief:{cid}", args.project_root)
        approved_file(ledger, "visual_style:PROJECT", args.project_root)
        approved_file(ledger, "production_spec:PROJECT", args.project_root)
        refs = [actor_path]
        deps = [f"actor_baseline:{cid}", f"casting_brief:{cid}",
                "visual_style:PROJECT", "production_spec:PROJECT"]
        reference_view_types = spec.get("reference_view_types", [])
        if not isinstance(reference_view_types, list) or any(
                not isinstance(item, str) or not item.strip() for item in reference_view_types):
            raise SystemExit("reference_view_types must be an array of non-empty strings")
        if view_type in reference_view_types or len(reference_view_types) != len(set(reference_view_types)):
            raise SystemExit("reference_view_types must be unique and cannot include the output view")
        for reference_view_type in reference_view_types:
            key = f"actor_identity_view:{cid}:{reference_view_type}"
            _, reference_path = approved_file(ledger, key, args.project_root)
            refs.append(reference_path)
            deps.append(key)
        prompt = (f"保持参考演员的唯一身份、脸部结构、肤色、年龄视觉和身体比例，生成 {view_type} 身份参考视图。"
                  f"要求：{'；'.join(spec['requirements'])}。中性基础服装，无角色妆发、无职业服装、无道具、纯灰背景、无文字。")
        output_type, scope = "actor_identity_view", f"{cid}:{view_type}"
    elif args.mode in COMPONENT_MODES:
        errors = validate_component(spec, for_production=True)
        if errors: raise SystemExit("；".join(errors))
        cid, state_id, kind = spec["character_id"], spec["look_state_id"], spec["component_type"]
        output_type, expected_kind = COMPONENT_MODES[args.mode]
        if expected_kind and kind != expected_kind:
            raise SystemExit(f"{args.mode} requires component_type={expected_kind}")
        if args.mode == "look-component" and kind == "makeup":
            raise SystemExit("makeup components must use makeup-batch so the approved actor baseline is applied")
        if spec.get("asset_type") and spec["asset_type"] != output_type:
            raise SystemExit(f"{args.mode} requires asset_type={output_type}")
        plan_artifact, plan_path = approved_file(
            ledger, f"look_state_plan:{cid}", args.project_root)
        plan = read(plan_path)
        plan_errors = validate_look_state_plan(plan)
        if plan_errors or not component_is_declared(spec, plan):
            raise SystemExit("component is not declared by the approved look-state plan")
        requirement_key = f"look_component_requirement:{cid}:{state_id}:{kind}"
        requirement_artifact, _ = approved_file(ledger, requirement_key, args.project_root)
        if requirement_artifact.get("sha256") != file_sha256(args.spec.resolve()):
            raise SystemExit(f"approved component requirement file changed: {requirement_key}")
        approved_file(ledger, "visual_style:PROJECT", args.project_root)
        approved_file(ledger, "production_spec:PROJECT", args.project_root)
        refs = []
        deps = [f"look_state_plan:{cid}", requirement_key, "visual_style:PROJECT"]
        deps.append("production_spec:PROJECT")
        # Only makeup is applied to the selected actor at component-generation time.
        # Costume fit, hair, accessories, and the generic legacy component route
        # remain identity-free; actor identity is introduced by character fusion.
        actor_applied = args.mode == "makeup-batch"
        if actor_applied:
            _, actor_path = approved_file(ledger, f"actor_baseline:{cid}", args.project_root)
            refs = [actor_path]
            deps.insert(0, f"actor_baseline:{cid}")
            prompt = (f"保持参考演员身份，仅将已确认的{kind}组件应用到演员："
                      f"{'；'.join(spec['requirements'])}。"
                      f"禁止变化：{'；'.join(spec['forbidden_changes'])}。"
                      "保持演员脸型、年龄视觉和身体比例，不新增其他造型组件。")
        else:
            prompt = (f"独立设计{kind}组件，不读取、不继承任何演员身份："
                      f"{'；'.join(spec['requirements'])}。"
                      f"禁止变化：{'；'.join(spec['forbidden_changes'])}。"
                      "只锁定组件本身的结构、材质、颜色、比例和细节；纯净背景，无剧情场景，无文字。")
        if args.mode == "costume-reference":
            reference_image = spec.get("reference_image")
            if not isinstance(reference_image, str) or not reference_image.strip():
                raise SystemExit("costume-reference requires reference_image")
            reference_path = args.project_root / reference_image
            inside(args.project_root, reference_path)
            if not reference_path.is_file():
                raise SystemExit(f"reference_image is missing: {reference_image}")
            refs = [reference_path]
            prompt = ("只提取参考图中的服装，不继承模特的脸部、身份、身体比例、姿势或背景。"
                      "将服装整理为干净的服装展示资产，保留廓形、颜色、层次、剪裁、扣件、"
                      "接缝、面料纹理和受光关系；不得新增人物身份、场景、道具或文字。"
                      "输出单张清晰服装资产图，纯净背景。"
                      f"服装需求：{'；'.join(spec['requirements'])}。")
            deps = [f"look_state_plan:{cid}", requirement_key,
                    "visual_style:PROJECT", "production_spec:PROJECT"]
        elif args.mode == "costume-structure":
            structure_errors = validate_costume_structure_design(spec)
            if structure_errors:
                raise SystemExit("；".join(structure_errors))
            prompt = costume_structure_prompt(spec)
        elif args.mode == "fabric-detail":
            _, structure_path = approved_file(
                ledger, f"costume_structure:{cid}:{state_id}:costume", args.project_root)
            refs.append(structure_path)
            deps.append(f"costume_structure:{cid}:{state_id}:costume")
            prompt += "输出服装面料微距细节，锁定纹理、织法、厚薄和受光反应。"
        elif args.mode == "costume-worn-view":
            _, structure_path = approved_file(
                ledger, f"costume_structure:{cid}:{state_id}:costume", args.project_root)
            _, fabric_path = approved_file(
                ledger, f"fabric_detail:{cid}:{state_id}:costume", args.project_root)
            refs.extend([structure_path, fabric_path])
            deps.extend([f"costume_structure:{cid}:{state_id}:costume",
                         f"fabric_detail:{cid}:{state_id}:costume"])
            prompt += ("使用无身份服装人台或中性人体模特展示服装的全身比例、垂坠、褶皱和层次，"
                       "服装完整可见；不得继承任何演员或模特的脸部、身份、体型特征、姿势或背景。")
        elif args.mode == "hair-batch":
            prompt += "生成发型设计候选，可使用无身份头模或发型设计板展示，不出现可识别演员脸部。"
        elif args.mode == "makeup-batch":
            prompt += "生成多个妆容候选，只改变妆容状态，不改变演员身份、发型和服装。"
        elif args.mode == "accessory-batch":
            prompt += "生成多个配饰设计候选，可使用无身份展示模特或静物展示，不继承人物身份。"
        scope = f"{cid}:{state_id}:{kind}"
        if output_type != "look_component":
            scope = f"{cid}:{state_id}:{kind}"
    elif args.mode == "character-fusion":
        cid, state_id, kinds = spec["character_id"], spec["look_state_id"], spec["component_types"]
        _, plan_path = approved_file(ledger, f"look_state_plan:{cid}", args.project_root)
        plan = read(plan_path)
        declared = next((state for state in plan.get("look_states", [])
                         if state.get("look_state_id") == state_id), None)
        all_declared_kinds = fusable_component_types(declared or {})
        requirement_specs = {}
        requirement_keys = []
        absent_kinds = []
        for kind in all_declared_kinds:
            requirement_key = f"look_component_requirement:{cid}:{state_id}:{kind}"
            requirement_artifact = ledger.get("artifacts", {}).get(requirement_key)
            if (not requirement_artifact
                    or requirement_artifact.get("status") != "USER_APPROVED"):
                raise SystemExit(
                    f"approved look component requirement is required: {kind}")
            _, requirement_path = approved_file(ledger, requirement_key, args.project_root)
            requirement = read(requirement_path)
            disposition = requirement.get("production_disposition", "asset_required")
            if disposition not in {"asset_required", "confirmed_absent"}:
                raise SystemExit(
                    f"unsupported component production_disposition: {kind}")
            if disposition == "confirmed_absent":
                requirement_errors = validate_component(requirement)
                if requirement_errors:
                    raise SystemExit("；".join(requirement_errors))
                if (requirement.get("component_type") != kind
                        or not component_is_declared(requirement, plan)):
                    raise SystemExit(
                        f"confirmed-absent component requirement does not match look state: {kind}")
                absent_kinds.append(kind)
            requirement_specs[kind] = requirement
            requirement_keys.append(requirement_key)
        declared_kinds = fusable_component_types(declared or {}, requirement_specs)
        if kinds != declared_kinds:
            raise SystemExit("fusion component_types must exactly match the approved look state")
        component_assets = spec.get("component_assets")
        if isinstance(component_assets, dict) and any(
                kind in component_assets for kind in absent_kinds):
            raise SystemExit("confirmed-absent components cannot declare fusion assets")
        errors, _ = validate_fusion_sources(
            ledger, cid, state_id, kinds, component_assets)
        if errors: raise SystemExit("；".join(errors))
        refs = []
        _, actor_path = approved_file(ledger, f"actor_baseline:{cid}", args.project_root)
        refs.append(actor_path)
        deps = [f"actor_baseline:{cid}", f"look_state_plan:{cid}", *requirement_keys]
        for kind in kinds:
            declared = component_assets.get(kind) if isinstance(component_assets, dict) else None
            keys = declared if isinstance(declared, list) else [declared] if isinstance(declared, str) else [f"look_component:{cid}:{state_id}:{kind}"]
            for key in keys:
                if ":" not in key:
                    key = f"{key}:{cid}:{state_id}:{kind}"
                _, path = approved_file(ledger, key, args.project_root)
                refs.append(path); deps.append(key)
        prompt = fusion_prompt(cid, state_id, kinds, absent_kinds)
        output_type, scope = "canonical_character_look", f"{cid}:{state_id}"
    elif args.mode == "character-four-view":
        errors = validate_four_view_spec(spec)
        if errors: raise SystemExit("；".join(errors))
        cid, state_id = spec["character_id"], spec["look_state_id"]
        _, canonical_path = approved_file(
            ledger, f"canonical_character_look:{cid}:{state_id}", args.project_root)
        _, plan_path = approved_file(ledger, f"look_state_plan:{cid}", args.project_root)
        approved_file(ledger, "visual_style:PROJECT", args.project_root)
        approved_file(ledger, "production_spec:PROJECT", args.project_root)
        refs = [canonical_path]
        deps = [f"canonical_character_look:{cid}:{state_id}", f"look_state_plan:{cid}",
                "visual_style:PROJECT", "production_spec:PROJECT"]
        prompt = ("保持参考图中的五官、脸型、年龄感、发型、妆容、服装、配饰和身材比例。"
                  "生成一张完整的人物四视图资产：左至右依次为标准正面全身、标准90度侧面全身、"
                  "标准全身背面、正面胸部以上脸部特写。人物均自然站立，双手自然下垂，双脚自然站立，"
                  "头部与身体朝向一致，无夸张动作。发型结构清晰，服装廓形、颜色、材质和层次清楚，"
                  "配饰位置固定，背面展示后脑、肩颈和服装背面。纯白背景，光色均匀柔和，"
                  "无分割线、箭头、编号、文字、水印、场景和分镜框；四个视图高度、身材比例一致，"
                  "single image, no collage, no split lines. " + "；".join(spec["requirements"]) +
                  "。禁止：" + "；".join(spec["forbidden"]) + "。作为后续视频生成的默认人物身份与服装参考。")
        output_type, scope = "character_four_view", f"{cid}:{state_id}"
    elif args.mode == "character-atomic-view":
        cid, state_id, view_type = spec.get("character_id"), spec.get("look_state_id"), spec.get("view_type")
        if not cid or not state_id or not view_type or not isinstance(spec.get("requirements"), list):
            raise SystemExit("character atomic view requires character_id, look_state_id, view_type, and requirements")
        _, source_path = approved_file(ledger, f"character_four_view:{cid}:{state_id}", args.project_root)
        refs = [source_path]
        deps = [f"character_four_view:{cid}:{state_id}"]
        prompt = (f"保持参考四视图中的同一角色身份、造型、服装和比例，仅补充 {view_type} 单帧视图。"
                  f"要求：{'；'.join(spec['requirements'])}。无文字、无水印、无动作变化。")
        output_type, scope = "atomic_character_view", f"{cid}:{state_id}:{view_type}"
    elif args.mode == "scene-master":
        errors = validate_scene_functional_brief(spec)
        if errors:
            raise SystemExit("；".join(errors))
        sid = spec["scene_id"]
        requirement, _ = approved_file(
            ledger, f"scene_functional_brief:{sid}", args.project_root)
        if requirement.get("sha256") != file_sha256(args.spec.resolve()):
            raise SystemExit(f"approved scene functional brief file changed: scene_functional_brief:{sid}")
        _, style_path = approved_file(ledger, "visual_style:PROJECT", args.project_root)
        approved_file(ledger, "production_spec:PROJECT", args.project_root)
        visual_requirements = [item["requirement"] for item in spec["visual_implications"]]
        prompt = (f"生成场景 {sid} 的无人母版空镜。视觉落实：{'；'.join(visual_requirements)}。"
                  f"连续性锚点：{'；'.join(spec['continuity_anchors'])}。质感：{style_text(style_path)}。"
                  "无人物，无文字，单帧。")
        output_type, scope = "scene_master", sid
        deps = [f"scene_functional_brief:{sid}", "visual_style:PROJECT", "production_spec:PROJECT"]
    else:
        sid, view_type = spec["scene_id"], spec["view_type"]
        _, master_path = approved_file(ledger, f"scene_master:{sid}", args.project_root)
        refs = [master_path]; deps = [f"scene_master:{sid}"]
        prompt = (f"保持参考场景的门窗数量、家具位置、材质、比例和光线完全一致，"
                  f"只生成同一空间的 {view_type} 补充视图。无人，无文字，单帧。")
        output_type, scope = "scene_view", f"{sid}:{view_type}"
    context_type = {
        "actor-identity-view": "actor_identity_view",
        "character-fusion": "character_fusion",
        "character-four-view": "character_four_view",
        "character-atomic-view": "character_atomic_view",
        "scene-master": "scene_master",
        "scene-view": "scene_view",
        "costume-structure": "costume_structure",
        "fabric-detail": "fabric_detail",
        "costume-worn-view": "costume_worn_view",
        "costume-reference": "costume_reference",
        "hair-batch": "hair_batch",
        "makeup-batch": "makeup_batch",
        "accessory-batch": "accessory_batch",
    }.get(args.mode, "look_component")
    _, ledger, context_ref = prepare_context(
        ledger, context_type, scope, args.project_root,
        artifact_keys=deps, request_path=args.spec,
        variables={
            "character_id": str(spec.get("character_id", "")),
            "scene_id": str(spec.get("scene_id", "")),
            "look_state_id": str(spec.get("look_state_id", "")),
        },
    )
    write(args.project_ledger, ledger)
    if args.command == "export-prompt":
        inside(args.project_root, args.output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            prompt_package(args.mode, scope, prompt, refs, args.count), encoding="utf-8")
        print(json.dumps({"mode": args.mode, "scope_id": scope,
                          "prompt_path": str(args.output)},
                         ensure_ascii=False))
        return 0

    if args.batch.exists():
        raise SystemExit(f"candidate batch already exists: {args.batch}")

    if args.command == "import-candidates":
        if not 1 <= len(args.files) <= 8:
            raise SystemExit("candidate file count must be 1-8")
        errors = []
        for source in args.files:
            errors.extend(f"{source}: {message}" for message in validate_candidate_image(source))
        if errors:
            raise SystemExit("invalid candidate files: " + "；".join(errors))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        candidates, created = [], []
        try:
            for index, source in enumerate(args.files, 1):
                destination = args.output_dir / f"candidate-{index:02d}{source.suffix.lower()}"
                if destination.exists():
                    raise SystemExit(f"candidate destination already exists: {destination}")
                shutil.copy2(source, destination)
                created.append(destination)
                candidates.append({"candidate_id": f"candidate-{index:02d}",
                                   "path": str(destination), "source": "user_external",
                                   "original_filename": source.name})
            metadata = {"route": "user_external", "provider": "user_selected",
                        "model": "user_supplied_or_unknown",
                        "candidate_count": len(candidates),
                        "reference_paths": [inside(args.project_root, path) for path in refs]}
            metadata["context"] = context_ref
            batch = candidate_batch(args.project_root, args.batch.stem, output_type, scope,
                                    prompt, candidates, metadata, deps, context_ref)
            write(args.batch, batch)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        print(json.dumps({"batch": str(args.batch), "candidates": len(candidates),
                          "route": "user_external"}, ensure_ascii=False))
        return 0

    service = ImageGenerationService()
    candidates, metadata = (service.edit(prompt, refs, args.count, args.output_dir)
                            if refs else service.generate(prompt, args.count, args.output_dir))
    metadata["context"] = context_ref
    batch = candidate_batch(args.project_root, args.batch.stem, output_type, scope,
                            prompt, candidates, metadata, deps, context_ref)
    write(args.batch, batch)
    print(json.dumps({"batch": str(args.batch), "candidates": len(candidates)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
