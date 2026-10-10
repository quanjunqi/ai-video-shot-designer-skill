#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run deterministic file-level checks before a human visual review.

This is deliberately a gate, not an image-quality model.  A generated image
can pass the file checks and still be rejected by the director during visual
review.  The report therefore distinguishes ``程序通过`` from
``待视觉确认``.
"""

import argparse
import json
import sys
from pathlib import Path


MIN_SIDE = 256
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp"}
KINDS = {"asset", "composition"}


def _load_image(path: Path):
    try:
        from PIL import Image, ImageStat
    except ImportError as exc:
        raise RuntimeError("需要 Pillow：python3 -m pip install Pillow") from exc
    image = Image.open(path)
    image.load()
    return image, ImageStat.Stat(image.convert("RGB"))


def inspect(path: Path, kind: str) -> dict:
    result = {
        "file": str(path),
        "kind": kind,
        "status": "待视觉确认",
        "errors": [],
        "warnings": [],
        "checks": {},
    }
    if not path.exists():
        result["errors"].append("文件不存在")
        result["status"] = "失败"
        return result
    if not path.is_file():
        result["errors"].append("目标不是普通文件")
        result["status"] = "失败"
        return result
    result["checks"]["extension"] = path.suffix.lower()
    if path.suffix.lower() not in SUPPORTED:
        result["errors"].append("文件扩展名不在 PNG/JPG/JPEG/WEBP 范围内")
    if path.stat().st_size == 0:
        result["errors"].append("文件为空")
    try:
        image, stats = _load_image(path)
        width, height = image.size
        result["checks"].update({
            "format": image.format,
            "mode": image.mode,
            "width": width,
            "height": height,
            "aspect_ratio": round(width / height, 4) if height else None,
            "mean_rgb": [round(value, 2) for value in stats.mean],
            "stddev_rgb": [round(value, 2) for value in stats.stddev],
        })
        if min(width, height) < MIN_SIDE:
            result["errors"].append(f"最短边 {min(width, height)}px 小于 {MIN_SIDE}px")
        if not image.getbbox():
            result["errors"].append("图像没有可见像素")
        if max(stats.stddev) < 3.0:
            result["warnings"].append("画面近似纯色或缺少有效内容，请人工确认")
    except Exception as exc:  # Pillow decode errors vary by format/plugin.
        result["errors"].append(f"图像无法读取：{exc}")
    if result["errors"]:
        result["status"] = "失败"
    elif result["warnings"]:
        result["status"] = "程序通过，待视觉确认"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="图片文件质量门禁与视觉复核清单生成器")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--kind", choices=sorted(KINDS), default="asset")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    reports = [inspect(path, args.kind) for path in args.files]
    failed = any(report["status"] == "失败" for report in reports)
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(f"{report['status']}：{report['file']}")
            for message in report["errors"]:
                print(f"  错误：{message}")
            for message in report["warnings"]:
                print(f"  警告：{message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
