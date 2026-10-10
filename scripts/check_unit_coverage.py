#!/usr/bin/env python3
"""Validate v3 script coverage and optionally render user shooting manuscripts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shotdesigner.script_coverage import (
    render_unit_manuscript, sha256_text, validate_manuscript_files, validate_source_script,
    validate_unit_coverage,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="JSON containing script_manifest and units")
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args()
    data = json.loads(args.plan.read_text(encoding="utf-8"))
    manifest, units = data.get("script_manifest"), data.get("units")
    errors = validate_unit_coverage(manifest, units)
    if args.artifact_root:
        errors.extend(validate_source_script(data.get("source_script"), args.artifact_root))
    rendered = []
    if not errors and args.render_dir:
        args.render_dir.mkdir(parents=True, exist_ok=True)
        for unit in units:
            text = render_unit_manuscript(manifest, unit)
            path = args.render_dir / f"{unit['unit_id']}-shooting-manuscript.md"
            path.write_text(text, encoding="utf-8")
            rendered.append({"unit_id": unit["unit_id"], "path": str(path), "sha256": sha256_text(text)})
    if not errors and args.artifact_root:
        errors.extend(validate_manuscript_files(manifest, units, args.artifact_root))
    print(json.dumps({"status": "失败" if errors else "通过", "errors": errors,
                      "rendered": rendered}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
