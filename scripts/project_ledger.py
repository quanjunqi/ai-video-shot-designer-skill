#!/usr/bin/env python3
"""Manage the compact v3 co-direct project and immutable review ledgers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from shotdesigner.ledgers.dependencies import mark_stale
from shotdesigner.context_runtime import prepare_context
from shotdesigner.ledgers.project import apply_review, new_project, register_artifact, utc_now
from shotdesigner.ledgers.reviews import append_review, create_review, load_reviews
from shotdesigner.ledgers.stages import validate_advance
from shotdesigner.validators.project_ledger import validate_project_ledger


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--path", type=Path, default=Path("project-ledger.json"))
    result.add_argument("--reviews", type=Path, default=Path("reviews/review-ledger.jsonl"))
    sub = result.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("project_id")
    init.add_argument("title")

    add = sub.add_parser("register")
    add.add_argument("artifact_id")
    add.add_argument("artifact_type")
    add.add_argument("scope_id")
    add.add_argument("version", type=int)
    add.add_argument("sha256")
    add.add_argument("artifact_path")
    add.add_argument("--depends-on", action="append", default=[])
    add.add_argument("--status", default="AWAITING_USER")

    review = sub.add_parser("review")
    review.add_argument("review_id")
    review.add_argument("artifact_type")
    review.add_argument("scope_id")
    review.add_argument("decision")
    review.add_argument("user_statement")

    stale = sub.add_parser("invalidate")
    stale.add_argument("artifact_type")
    stale.add_argument("scope_id")

    scopes = sub.add_parser("set-scopes")
    scopes.add_argument("kind", choices=("characters", "look_states", "scenes", "units"))
    scopes.add_argument("ids", nargs="+")

    advance = sub.add_parser("advance")
    advance.add_argument("target")

    sub.add_parser("show")

    context = sub.add_parser("context", help="compile or inspect an internal context packet")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    context_build = context_sub.add_parser("build")
    context_build.add_argument("context_type")
    context_build.add_argument("scope_id")
    context_build.add_argument("--project-root", type=Path, default=Path("."))
    context_build.add_argument("--artifact-key", action="append", default=[],
                               help="Explicit approved artifact key; repeat for dynamic inputs")
    context_build.add_argument("--request", type=Path,
                               help="Node request spec whose file hash participates in caching")
    context_build.add_argument("--output", type=Path)
    context_build.add_argument("--reference-output", type=Path,
                               help="Write the validated context receipt to this project-relative JSON path")
    context_build.add_argument("--variable", action="append", default=[], metavar="NAME=VALUE")
    context_build.add_argument("--allow-missing-files", action="store_true")
    context_inspect = context_sub.add_parser("inspect")
    context_inspect.add_argument("context_type")
    context_inspect.add_argument("scope_id")
    context_inspect.add_argument("--project-root", type=Path, default=Path("."))
    context_inspect.add_argument("--artifact-key", action="append", default=[],
                                 help="Explicit approved artifact key; repeat for dynamic inputs")
    context_inspect.add_argument("--request", type=Path,
                                 help="Node request spec whose file hash participates in caching")
    context_inspect.add_argument("--variable", action="append", default=[], metavar="NAME=VALUE")
    context_inspect.add_argument("--allow-missing-files", action="store_true")
    return result


def context_variables(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"invalid --variable, expected NAME=VALUE: {value}")
        name, raw = value.split("=", 1)
        if not name:
            raise SystemExit(f"invalid --variable name: {value}")
        result[name] = raw
    return result


def context_output_path(project_root: Path, output: Path) -> Path:
    if output.is_absolute():
        raise SystemExit("context output must be relative to --project-root")
    root = project_root.resolve()
    resolved = (root / output).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SystemExit("context output must remain inside --project-root") from exc
    return resolved


def main() -> int:
    args = parser().parse_args()
    if args.command == "init":
        if args.path.exists():
            raise SystemExit(f"ledger already exists: {args.path}")
        value = new_project(args.project_id, args.title)
        save(args.path, value)
    else:
        if not args.path.is_file():
            raise SystemExit(f"ledger not found: {args.path}")
        value = load(args.path)
        if args.command == "context":
            output = None
            if args.output is not None:
                output = context_output_path(args.project_root, args.output)
                output = output.relative_to(args.project_root.resolve())
            reference_output = None
            if getattr(args, "reference_output", None) is not None:
                reference_output = context_output_path(args.project_root, args.reference_output)
            packet, updated, reference = prepare_context(
                value, args.context_type, args.scope_id, args.project_root,
                artifact_keys=args.artifact_key or None,
                request_path=args.request,
                variables=context_variables(args.variable),
                verify_files=not args.allow_missing_files,
                output_path=output,
                inspect_only=args.context_command == "inspect",
            )
            if args.context_command == "inspect":
                entry = value.get("derived_cache", {}).get(
                    f"context:{args.context_type}:{args.scope_id}")
                print(json.dumps({"context_hash": packet["context_hash"],
                                  "cache_hit": reference["cache_hit"],
                                  "artifact_keys": reference["artifact_keys"],
                                  "output": reference["path"],
                                  "cache_entry": entry}, ensure_ascii=False, indent=2))
                return 0
            save(args.path, updated)
            if reference_output is not None:
                save(reference_output, reference)
            print(json.dumps({"context_hash": packet["context_hash"],
                              "cache_hit": reference["cache_hit"],
                              "artifact_keys": reference["artifact_keys"],
                              "output": reference["path"],
                              **({"reference_output": str(reference_output.relative_to(args.project_root.resolve()))}
                                 if reference_output is not None else {})},
                       ensure_ascii=False, indent=2))
            return 0
        if args.command == "register":
            value = register_artifact(
                value, artifact_id=args.artifact_id, artifact_type=args.artifact_type,
                scope_id=args.scope_id, version=args.version, sha256=args.sha256,
                path=args.artifact_path, depends_on=args.depends_on, status=args.status)
            save(args.path, value)
        elif args.command == "review":
            key = f"{args.artifact_type}:{args.scope_id}"
            artifact = value.get("artifacts", {}).get(key)
            if artifact is None:
                raise SystemExit(f"unknown current artifact: {key}")
            event = create_review(
                review_id=args.review_id, artifact_id=artifact["artifact_id"],
                artifact_type=args.artifact_type, scope_id=args.scope_id,
                artifact_version=artifact["version"], artifact_sha256=artifact["sha256"],
                decision=args.decision, user_statement=args.user_statement)
            value = apply_review(value, event)
            append_review(args.reviews, event)
            save(args.path, value)
        elif args.command == "invalidate":
            value, affected = mark_stale(value, args.artifact_type, args.scope_id)
            save(args.path, value)
            print(json.dumps({"affected": affected}, ensure_ascii=False))
            return 0
        elif args.command == "set-scopes":
            value.setdefault("scope_registry", {})[args.kind] = list(dict.fromkeys(args.ids))
            value["updated_at"] = utc_now()
            save(args.path, value)
        elif args.command == "advance":
            errors = validate_project_ledger(value, load_reviews(args.reviews))
            errors.extend(validate_advance(value, args.target))
            if errors:
                raise SystemExit("cannot advance: " + "；".join(errors))
            value["current_stage"] = args.target
            value["updated_at"] = utc_now()
            save(args.path, value)
        elif args.command != "show":
            raise AssertionError(args.command)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
