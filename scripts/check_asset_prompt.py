#!/usr/bin/env python3
"""Check that an asset Prompt applies project texture style at the right layer."""

import argparse
import json
from pathlib import Path


PRESERVE_MARKERS = ("preserve", "inherit", "keep the exact", "保持", "保留", "继承")
BOUNDED_EDIT_MARKERS = ("change only", "modify only", "only inside", "仅修改", "只修改", "只改变")


def inspect(prompt: str, contract: dict, project_style_lock: str = "") -> list[str]:
    errors = []
    operation = contract.get("prompt_operation")
    application = contract.get("style_application")
    prompt_folded = prompt.casefold()
    style_lock = project_style_lock.strip()

    if operation == "canonical_create":
        if application != "project-texture-lock":
            errors.append("canonical_create 必须声明 style_application=project-texture-lock")
        if style_lock and style_lock.casefold() not in prompt_folded:
            errors.append("canonical_create Prompt 未包含项目质感锁")
    elif operation == "reference_edit":
        if application != "inherit-source":
            errors.append("reference_edit 必须声明 style_application=inherit-source")
        if not (contract.get("provenance", {}).get("derived_from") or []):
            errors.append("reference_edit 缺少 derived_from 源资产")
        if not (contract.get("variable_regions") or []):
            errors.append("reference_edit 缺少 variable_regions")
        if style_lock and style_lock.casefold() in prompt_folded:
            errors.append("reference_edit Prompt 不得重复完整项目质感锁")
        if not any(marker in prompt_folded for marker in PRESERVE_MARKERS):
            errors.append("reference_edit Prompt 缺少源图保持/继承指令")
        if not any(marker in prompt_folded for marker in BOUNDED_EDIT_MARKERS):
            errors.append("reference_edit Prompt 缺少仅修改变量区的边界指令")
    elif operation == "composition_create":
        if application not in {"project-texture-lock", "inherit-source"}:
            errors.append("composition_create 必须明确重新应用质感锁或继承源图")
    else:
        errors.append(f"未知 prompt_operation: {operation!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--project-style-lock", default="")
    parser.add_argument("--project-style-lock-file", type=Path)
    args = parser.parse_args()

    style_lock = args.project_style_lock
    if args.project_style_lock_file:
        style_lock = args.project_style_lock_file.read_text(encoding="utf-8").strip()
    prompt = args.prompt.read_text(encoding="utf-8")
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    errors = inspect(prompt, contract, style_lock)
    for error in errors:
        print(f"ERROR {error}")
    if errors:
        return 1
    print("asset-prompt-check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
