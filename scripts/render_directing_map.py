#!/usr/bin/env python3
"""Render the combined actor-blocking and camera-movement review map."""
import argparse, json
from pathlib import Path
from shotdesigner.directing_map import render, validate_routes

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene_map", type=Path); parser.add_argument("output", type=Path)
    args = parser.parse_args(); value = json.loads(args.scene_map.read_text(encoding="utf-8"))
    errors = validate_routes(value)
    if errors:
        print(json.dumps({"status":"失败","errors":errors}, ensure_ascii=False)); return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(value), encoding="utf-8")
    print(f"rendered: {args.output}"); return 0

if __name__ == "__main__": raise SystemExit(main())
