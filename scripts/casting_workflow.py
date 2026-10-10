#!/usr/bin/env python3
"""Validate casting briefs, generate neutral actors, and record user selection."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from shotdesigner.casting import (
    actor_candidate_prompt, actor_candidate_prompt_package, actor_style_text, file_sha256,
    finalize_batch, select_candidate, validate_candidate_image, validate_casting_brief,
)
from shotdesigner.context_runtime import prepare_context
from shotdesigner.image_generation import ImageGenerationService
from shotdesigner.ledgers.project import apply_review, register_artifact
from shotdesigner.ledgers.reviews import append_review, create_review


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def known_refs(plan: dict) -> set[str]:
    manifest = plan.get("script_manifest", {})
    return {
        item.get(key) for collection, key in (("events", "event_id"), ("dialogues", "dialogue_id"))
        for item in manifest.get(collection, []) if isinstance(item, dict) and item.get(key)
    }


def require_approved_requirement(ledger: dict, requirement: dict, path: Path) -> None:
    key = f"casting_brief:{requirement.get('character_id')}"
    artifact = ledger.get("artifacts", {}).get(key)
    if not artifact or artifact.get("status") != "USER_APPROVED":
        raise SystemExit(f"casting brief is not user-approved: {key}")
    if artifact.get("sha256") != file_sha256(path):
        raise SystemExit(f"approved casting brief file changed: {key}")


def approved_project_file(ledger: dict, key: str, root: Path) -> tuple[dict, Path]:
    artifact = ledger.get("artifacts", {}).get(key)
    if not artifact or artifact.get("status") != "USER_APPROVED":
        raise SystemExit(f"approved upstream artifact required: {key}")
    path = root / artifact.get("path", "")
    case_relative(root, path)
    if not path.is_file() or file_sha256(path) != artifact.get("sha256"):
        raise SystemExit(f"approved upstream artifact file changed: {key}")
    return artifact, path


def style_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return actor_style_text(value) or json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def case_relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError as exc:
        raise SystemExit(f"path must stay inside project root: {path}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate-casting-brief", aliases=["validate-requirement"])
    validate.add_argument("requirement", type=Path)
    validate.add_argument("script_plan", type=Path)

    generate = sub.add_parser("generate")
    generate.add_argument("requirement", type=Path)
    generate.add_argument("script_plan", type=Path)
    generate.add_argument("project_ledger", type=Path)
    generate.add_argument("batch", type=Path)
    generate.add_argument("output_dir", type=Path)
    generate.add_argument("--project-root", type=Path, required=True)
    generate.add_argument("--style", help="deprecated: must match the approved visual-style file")
    generate.add_argument("--count", type=int, default=4)
    generate.add_argument("--batch-id")

    export_prompt = sub.add_parser("export-prompt")
    export_prompt.add_argument("requirement", type=Path)
    export_prompt.add_argument("script_plan", type=Path)
    export_prompt.add_argument("project_ledger", type=Path)
    export_prompt.add_argument("output", type=Path)
    export_prompt.add_argument("--project-root", type=Path, required=True)
    export_prompt.add_argument("--count", type=int, default=4)

    import_candidates = sub.add_parser("import-candidates")
    import_candidates.add_argument("requirement", type=Path)
    import_candidates.add_argument("script_plan", type=Path)
    import_candidates.add_argument("project_ledger", type=Path)
    import_candidates.add_argument("batch", type=Path)
    import_candidates.add_argument("output_dir", type=Path)
    import_candidates.add_argument("files", nargs="+", type=Path)
    import_candidates.add_argument("--project-root", type=Path, required=True)
    import_candidates.add_argument("--batch-id")

    select = sub.add_parser("select")
    select.add_argument("batch", type=Path)
    select.add_argument("candidate_id")
    select.add_argument("project_ledger", type=Path)
    select.add_argument("review_ledger", type=Path)
    select.add_argument("review_id")
    select.add_argument("user_statement")
    select.add_argument("--project-root", type=Path, required=True)

    args = parser.parse_args()
    if args.command in {"validate-casting-brief", "validate-requirement"}:
        requirement, plan = read(args.requirement), read(args.script_plan)
        errors = validate_casting_brief(requirement, known_refs(plan))
        print(json.dumps({"status": "失败" if errors else "通过", "errors": errors},
                         ensure_ascii=False, indent=2))
        return 1 if errors else 0

    if args.command in {"generate", "export-prompt", "import-candidates"}:
        requirement, plan, ledger = read(args.requirement), read(args.script_plan), read(args.project_ledger)
        errors = validate_casting_brief(requirement, known_refs(plan))
        if errors:
            raise SystemExit("invalid character requirement: " + "；".join(errors))
        case_relative(args.project_root, args.requirement)
        case_relative(args.project_root, args.script_plan)
        case_relative(args.project_root, args.project_ledger)
        require_approved_requirement(ledger, requirement, args.requirement)
        _, style_path = approved_project_file(ledger, "visual_style:PROJECT", args.project_root)
        approved_project_file(ledger, "production_spec:PROJECT", args.project_root)
        approved_style = style_text(style_path)
        if args.command == "generate" and args.style and args.style.strip() != approved_style:
            raise SystemExit("--style differs from the approved visual_style artifact")
        _, ledger, context_ref = prepare_context(
            ledger, "casting", requirement["character_id"], args.project_root,
            artifact_keys=[f"casting_brief:{requirement['character_id']}",
                           "visual_style:PROJECT", "production_spec:PROJECT"],
            request_path=args.requirement,
        )
        write(args.project_ledger, ledger)

    if args.command == "export-prompt":
        case_relative(args.project_root, args.output)
        package = actor_candidate_prompt_package(requirement, approved_style, args.count)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(package, encoding="utf-8")
        print(json.dumps({"character_id": requirement["character_id"],
                          "prompt_path": str(args.output)}, ensure_ascii=False))
        return 0

    if args.command == "import-candidates":
        if not 1 <= len(args.files) <= 8:
            raise SystemExit("candidate file count must be 1-8")
        case_relative(args.project_root, args.batch)
        case_relative(args.project_root, args.output_dir)
        if args.batch.exists():
            raise SystemExit(f"candidate batch already exists: {args.batch}")
        errors = []
        for source in args.files:
            errors.extend(f"{source}: {message}" for message in validate_candidate_image(source))
        if errors:
            raise SystemExit("invalid candidate files: " + "；".join(errors))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        candidates = []
        created = []
        try:
            for index, source in enumerate(args.files, 1):
                destination = args.output_dir / f"candidate-{index:02d}{source.suffix.lower()}"
                if destination.exists():
                    raise SystemExit(f"candidate destination already exists: {destination}")
                shutil.copy2(source, destination)
                created.append(destination)
                candidates.append({"candidate_id": f"candidate-{index:02d}",
                                   "path": case_relative(args.project_root, destination),
                                   "source": "user_external",
                                   "original_filename": source.name})
            prompt = actor_candidate_prompt(requirement, approved_style)
            batch_id = args.batch_id or f"casting-{requirement['character_id']}-v1"
            batch = finalize_batch(
                requirement["character_id"], batch_id, prompt, candidates,
                {"route": "user_external", "provider": "user_selected",
                 "model": "user_supplied_or_unknown", "candidate_count": len(candidates)},
                args.project_root,
                depends_on=[f"casting_brief:{requirement['character_id']}",
                            "visual_style:PROJECT", "production_spec:PROJECT"],
            )
            batch["generation"]["context"] = context_ref
            write(args.batch, batch)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        print(json.dumps({"batch_id": batch_id, "candidate_count": len(candidates),
                          "batch_path": str(args.batch), "route": "user_external"},
                         ensure_ascii=False))
        return 0

    if args.command == "generate":
        case_relative(args.project_root, args.batch)
        case_relative(args.project_root, args.output_dir)
        prompt = actor_candidate_prompt(requirement, approved_style)
        candidates, metadata = ImageGenerationService().generate(prompt, args.count, args.output_dir)
        candidates = [{**item, "path": case_relative(args.project_root, Path(item["path"]))}
                      for item in candidates]
        batch_id = args.batch_id or f"casting-{requirement['character_id']}-v1"
        batch = finalize_batch(
            requirement["character_id"], batch_id, prompt, candidates, metadata,
            args.project_root,
            depends_on=[f"casting_brief:{requirement['character_id']}",
                        "visual_style:PROJECT", "production_spec:PROJECT"],
        )
        batch["generation"]["context"] = context_ref
        write(args.batch, batch)
        print(json.dumps({"batch_id": batch_id, "candidate_count": len(candidates),
                          "batch_path": str(args.batch)}, ensure_ascii=False))
        return 0

    case_relative(args.project_root, args.batch)
    batch, ledger = read(args.batch), read(args.project_ledger)
    selected = select_candidate(batch, args.candidate_id, args.project_root)
    current = ledger.get("artifacts", {}).get(f"actor_baseline:{selected['scope_id']}")
    if current:
        selected["version"] = current["version"] + 1
        selected["artifact_id"] = f"actor-{selected['scope_id']}-v{selected['version']}"
    ledger = register_artifact(ledger, **{key: selected[key] for key in (
        "artifact_id", "artifact_type", "scope_id", "version", "sha256", "path", "depends_on")})
    event = create_review(
        review_id=args.review_id, artifact_id=selected["artifact_id"],
        artifact_type="actor_baseline", scope_id=selected["scope_id"],
        artifact_version=selected["version"], artifact_sha256=selected["sha256"],
        decision="select_candidate", user_statement=args.user_statement)
    ledger = apply_review(ledger, event)
    append_review(args.review_ledger, event)
    batch["selected_candidate_id"] = args.candidate_id
    batch["batch_status"] = "USER_SELECTED"
    for candidate in batch["candidates"]:
        candidate["status"] = "USER_SELECTED" if candidate["candidate_id"] == args.candidate_id else "NOT_SELECTED"
    write(args.batch, batch)
    write(args.project_ledger, ledger)
    print(json.dumps(selected, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
