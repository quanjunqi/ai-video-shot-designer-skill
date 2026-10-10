#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the provenance contract for generated image metadata.

无 --ledger 时只做“模型名 / 用途 / 来源非空”的格式门禁；传入 --ledger
（asset_ledger.py 维护的 asset-ledger.json）后，会把每个派生来源解析到台账
资产，校验其真实存在、kind 为 canonical/tailframe、风格锁一致且未处于失败态，
从而堵住“随手填一个不存在的 URL 也算有来源”的漏洞。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BLOCKED_STATES = {"失败", "历史失败", "历史失败，禁止复用"}
SOURCE_KINDS = {"canonical", "tailframe"}
DEFAULT_TEXT_MODEL = "gpt-image-2"
DEFAULT_REFERENCE_MODEL = "nano-banana-2-2k"
ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def expected_models(ledger: dict | None) -> tuple[str, str]:
    load_dotenv(ROOT / ".env")
    policy = (ledger or {}).get("model_policy", {})
    return (
        policy.get("text_model") or os.getenv("PEARAPI_TEXT_MODEL") or DEFAULT_TEXT_MODEL,
        policy.get("reference_model") or os.getenv("PEARAPI_REFERENCE_MODEL") or DEFAULT_REFERENCE_MODEL,
    )


def build_source_index(ledger: dict) -> dict:
    """ref(URL/本地路径/asset_id) -> asset 记录。"""
    index = {}
    for asset in (ledger or {}).get("assets", {}).values():
        for ref in [asset.get("asset_id"), *asset.get("source_urls", []), *asset.get("local_files", [])]:
            if ref:
                index[ref] = asset
    return index


def check_sources_against_ledger(sources, ledger: dict, errors: list):
    if not ledger:
        return
    index = build_source_index(ledger)
    for ref in sources:
        asset = index.get(ref)
        if asset is None:
            errors.append(f"派生来源未在项目台账登记（无法证明其为真实 canonical/尾帧资产）：{ref}")
            continue
        if asset.get("kind") not in SOURCE_KINDS:
            errors.append(f"派生来源 {asset.get('asset_id')} kind={asset.get('kind')}，只允许 canonical/tailframe")
        if asset.get("visual_state") in BLOCKED_STATES:
            errors.append(f"派生来源 {asset.get('asset_id')} 处于 {asset.get('visual_state')}，禁止作为来源")


def inspect(path: Path, kind: str, ledger: dict = None) -> dict:
    report = {"file": str(path), "kind": kind, "status": "通过", "errors": [], "checks": {}}
    if not path.exists():
        report["errors"].append("元数据文件不存在")
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            request = data.get("_request", {}) if isinstance(data, dict) else {}
            model = request.get("model")
            purpose = request.get("purpose")
            style = request.get("style")
            sources = request.get("source_images") or request.get("derived_from") or []
            report["checks"].update({
                "model": model,
                "purpose": purpose,
                "style": style,
                "source_count": len(sources) if isinstance(sources, list) else 0,
            })
            if ledger is not None:
                expected_style = ledger.get("style_lock")
                if not style:
                    report["errors"].append("生产元数据必须记录项目风格锁 style")
                elif expected_style and style != expected_style:
                    report["errors"].append(f"元数据风格锁 {style} 与项目台账 {expected_style} 不一致")
            text_model, reference_model = expected_models(ledger)
            report["checks"].update({"expected_text_model": text_model, "expected_reference_model": reference_model})
            if kind == "canonical":
                if model != text_model:
                    report["errors"].append(f"canonical 资产必须使用项目 text_model={text_model}")
                if purpose != "canonical-text":
                    report["errors"].append("canonical 资产用途必须是 canonical-text")
                if sources:
                    report["errors"].append("canonical 文生图不应携带派生来源图片")
            else:
                if model != reference_model:
                    report["errors"].append(f"派生图必须使用项目 reference_model={reference_model}")
                if purpose != "reference-derived":
                    report["errors"].append("派生图用途必须是 reference-derived")
                if not isinstance(sources, list) or not sources or any(not isinstance(item, str) or not item.strip() for item in sources):
                    report["errors"].append("派生图必须记录至少一个实际来源图片引用")
                elif isinstance(sources, list):
                    check_sources_against_ledger(sources, ledger, report["errors"])
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            report["errors"].append(f"元数据无法解析：{exc}")
    if report["errors"]:
        report["status"] = "失败"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="生成图片来源链门禁")
    parser.add_argument("metadata", nargs="+", type=Path)
    parser.add_argument("--kind", choices=("canonical", "derived"), required=True)
    parser.add_argument("--ledger", type=Path, help="图片资产台账 asset-ledger.json；传入后核验来源真实性")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    ledger = None
    if args.ledger:
        if not args.ledger.exists():
            print(f"台账不存在：{args.ledger}", file=sys.stderr)
            return 1
        ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    reports = [inspect(path, args.kind, ledger=ledger) for path in args.metadata]
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(f"{report['status']}：{report['file']}")
            for error in report["errors"]:
                print(f"  错误：{error}")
    return 1 if any(item["status"] == "失败" for item in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
