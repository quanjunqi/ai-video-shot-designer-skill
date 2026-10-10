#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the professional per-shot camera-language cards.

The cards live in the Chinese generation settings before each H3 block. They
make photography decisions explicit without adding fields to the H3 contract.
The default mode keeps older drafts usable by reporting missing cards as
warnings; --strict is the release gate for newly generated work.
"""

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS = (
    "功能", "景别", "视角", "角度", "机位", "焦距", "对焦", "构图",
    "运镜", "节奏", "光影", "效果", "衔接",
)
SHOT_HEADER_RE = re.compile(r"(?m)^\s*镜头\s+(\d+)\s*[：:]\s*$")
CARD_MARKER_RE = re.compile(r"(?m)^\s*镜头语言卡（机器校验）\s*[：:]\s*$")
FENCE_RE = re.compile(
    r"(?P<ignore><!--\s*h3-validator\s*:\s*ignore\s*-->\s*)?"
    r"```[A-Za-z0-9_-]*\r?\n(?P<body>.*?)```", re.S | re.I
)
H3_REQUIRED_RE = re.compile(r"(?m)^\s*subject_definitions\s*:\s*$")
FIELD_RE = re.compile(
    r"(?ms)(?:^|[；;\n])\s*(功能|景别|视角|角度|机位|焦距|对焦|构图|运镜|节奏|光影|效果|衔接)\s*=\s*(.*?)(?=(?:[；;\n])\s*(?:功能|景别|视角|角度|机位|焦距|对焦|构图|运镜|节奏|光影|效果|衔接)\s*=|\Z)"
)
FOCAL_RE = re.compile(r"\b(?:等效\s*)?\d+(?:\.\d+)?\s*mm\b", re.I)
SHOT_RE = re.compile(r"\[Shot\s+(\d+)\]")
EXTERNAL_TIME_RE = re.compile(r"\bAt\s+\d{2}:\d{2}\.\d{3}\b")
EXTERNAL_SHOT_SIZE_RE = re.compile(
    r"\b(?:extreme\s+wide|wide|long|full|medium\s+long|medium|medium\s+close[- ]up|"
    r"close[- ]up|extreme\s+close[- ]up|insert)\s+shot\b", re.I
)
EXTERNAL_CAMERA_RE = re.compile(
    r"\b(?:camera|dolly|pan|tilt|track(?:ing)?|handheld|steadicam|static|crane|"
    r"orbit|zoom|push[- ]in|pull[- ]back|follows?|rack focus)\b", re.I
)
EXTERNAL_FOCUS_RE = re.compile(
    r"\b(?:focus(?:ed|es|ing)?|rack focus|shallow depth of field|deep focus|depth of field)\b",
    re.I,
)
EXTERNAL_LIGHT_RE = re.compile(
    r"\b(?:light(?:s|ing)?|shadow(?:s|ed)?|exposure|backlit|backlight|practical|"
    r"fluorescent|daylight|moonlight|warm|cool|dim|lit)\b", re.I
)
H3_DETAIL_RE = re.compile(
    r"(?ms)^\s*detailed_description\s*:\s*(.*?)(?=^\s*(?:overall_soundscape|non_diegetic_music)\s*:\s*|\Z)"
)

SHOT_SIZES = ("大远景", "远景", "全景", "中全景", "中景", "中近景", "近景", "特写", "大特写")
VIEWPOINTS = ("客观", "主观", "POV", "限制视角", "过肩", "OTS", "双人观察", "俯视空间", "插入特写")
ANGLES = ("平视", "高角度", "低角度", "鸟瞰", "虫视", "荷兰角", "俯拍", "仰拍")
MOVEMENT_TYPES = ("固定", "推", "拉", "横移", "摇", "俯仰", "升降", "环绕", "跟拍", "手持", "稳定器", "轨道", "摇臂", "变焦")
NO_EFFECT_RE = re.compile(r"^(?:无|无额外效果|无特殊效果|不适用)(?:[。；;，,、 ]*)$", re.I)


def issue(issues, level, code, message):
    issues.append((level, f"{code}: {message}"))


def parse_card_sections(text):
    sections = []
    markers = list(CARD_MARKER_RE.finditer(text))
    fence_positions = [m.start() for m in re.finditer(r"```", text)]
    for index, marker in enumerate(markers):
        end_candidates = [m.start() for m in markers[index + 1:]]
        end_candidates += [pos for pos in fence_positions if pos > marker.end()]
        end = min(end_candidates) if end_candidates else len(text)
        body = text[marker.end():end]
        shots = []
        shot_headers = list(SHOT_HEADER_RE.finditer(body))
        for shot_index, header in enumerate(shot_headers):
            shot_end = shot_headers[shot_index + 1].start() if shot_index + 1 < len(shot_headers) else len(body)
            shots.append((int(header.group(1)), body[header.end():shot_end]))
        sections.append((marker.start(), shots))
    return sections


def parse_fields(body):
    fields = {}
    for key, value in FIELD_RE.findall(body.replace("；", "\n")):
        fields[key] = value.strip(" \t\r\n；;")
    return fields


def validate_cards(text, strict=False):
    issues = []
    sections = parse_card_sections(text)
    if not sections:
        issue(issues, "ERROR" if strict else "WARNING", "card-missing", "未找到镜头语言卡（机器校验）")
        return issues, sections

    for section_index, (_position, shots) in enumerate(sections, 1):
        if not shots:
            issue(issues, "ERROR", "card-empty", f"第 {section_index} 个镜头语言卡没有镜头条目")
            continue
        numbers = [number for number, _body in shots]
        if len(numbers) != len(set(numbers)):
            issue(issues, "ERROR", "card-shot-duplicate", f"第 {section_index} 个镜头语言卡的镜头编号重复")
        for number, body in shots:
            fields = parse_fields(body)
            missing = [field for field in REQUIRED_FIELDS if not fields.get(field)]
            if missing:
                issue(issues, "ERROR", "card-field-missing", f"镜头 {number} 缺少: {', '.join(missing)}")
                continue
            size = fields["景别"]
            if not any(item in size for item in SHOT_SIZES):
                issue(issues, "ERROR", "card-shot-size", f"镜头 {number} 的景别不在受控景别链中: {size}")
            viewpoint = fields["视角"]
            if not any(item.lower() in viewpoint.lower() for item in VIEWPOINTS):
                issue(issues, "ERROR", "card-viewpoint", f"镜头 {number} 未声明受控视角: {viewpoint}")
            angle = fields["角度"]
            if not any(item in angle for item in ANGLES):
                issue(issues, "ERROR", "card-angle", f"镜头 {number} 未声明受控角度: {angle}")
            focal = fields["焦距"]
            if not FOCAL_RE.search(focal):
                issue(issues, "ERROR", "card-focal-length", f"镜头 {number} 的焦距必须包含 mm 数值: {focal}")
            if "透视" not in focal:
                issue(issues, "ERROR", "card-focal-perspective", f"镜头 {number} 的焦距缺少透视效果说明")
            if not any(word in focal for word in ("用途", "用于", "叙事", "交代", "强调", "压迫", "窥视")):
                issue(issues, "ERROR", "card-focal-purpose", f"镜头 {number} 的焦距缺少叙事用途说明")
            if not any(item in fields["运镜"] for item in MOVEMENT_TYPES):
                issue(issues, "ERROR", "card-movement-type", f"镜头 {number} 的运镜缺少受控运动类型")
            for required_word in ("方向", "幅度", "速度", "加减速", "稳定", "停止"):
                if required_word not in fields["运镜"]:
                    issue(issues, "ERROR", "card-movement-detail", f"镜头 {number} 的运镜缺少{required_word}")
            rhythm = fields["节奏"]
            if not re.search(r"\d+(?:\.\d+)?\s*秒|时长", rhythm):
                issue(issues, "ERROR", "card-rhythm-duration", f"镜头 {number} 的节奏缺少真实时长")
            if not any(word in rhythm for word in ("节拍", "起点", "前", "中", "末", "落点", "停顿")):
                issue(issues, "ERROR", "card-rhythm-beat", f"镜头 {number} 的节奏缺少内部节拍")
            if not any(word in rhythm for word in ("切", "剪")):
                issue(issues, "ERROR", "card-rhythm-cut", f"镜头 {number} 的节奏缺少剪切动机或切点")
            if not any(word in rhythm for word in ("情绪", "克制", "紧迫", "舒缓", "速度", "升级", "爆发")):
                issue(issues, "ERROR", "card-rhythm-emotion", f"镜头 {number} 的节奏缺少情绪速度")
            effect = fields["效果"]
            if not NO_EFFECT_RE.fullmatch(effect):
                if "强度" not in effect:
                    issue(issues, "ERROR", "card-effect-intensity", f"镜头 {number} 的效果缺少强度")
                has_start_end = "起止" in effect or ("开始" in effect and "结束" in effect)
                if not has_start_end and not re.search(r"起点.*终点|从.*到", effect):
                    issue(issues, "ERROR", "card-effect-timing", f"镜头 {number} 的效果缺少起止时刻")
                if not any(word in effect for word in ("限制", "不遮", "不影响", "可见")):
                    issue(issues, "ERROR", "card-effect-visibility", f"镜头 {number} 的效果缺少可见性边界")
    return issues, sections


def validate_h3_alignment(text, sections, strict=False):
    issues = []
    valid_blocks = []
    for match in FENCE_RE.finditer(text):
        if match.group("ignore") or not H3_REQUIRED_RE.search(match.group("body")):
            continue
        body = match.group("body")
        detail = H3_DETAIL_RE.search(body)
        if not detail:
            continue
        shot_numbers = [int(number) for number in SHOT_RE.findall(detail.group(1))]
        if shot_numbers:
            valid_blocks.append((match.start(), shot_numbers))

    for block_position, h3_numbers in valid_blocks:
        preceding = [item for item in sections if item[0] < block_position]
        if not preceding:
            continue
        _card_position, card_shots = preceding[-1]
        card_numbers = [number for number, _body in card_shots]
        if len(card_numbers) != len(h3_numbers):
            issue(issues, "ERROR", "card-h3-count", f"镜头语言卡有 {len(card_numbers)} 镜，H3 有 {len(h3_numbers)} 镜，数量不一致")
        elif card_numbers != h3_numbers:
            issue(issues, "ERROR", "card-h3-order", f"镜头语言卡镜号 {card_numbers} 与 H3 镜号 {h3_numbers} 不一致")
    return issues


def validate_external_h3(text):
    """Require a usable minimum of shot language when only H3 is delivered."""
    issues = []
    blocks = []
    for match in FENCE_RE.finditer(text):
        body = match.group("body")
        detail = H3_DETAIL_RE.search(body)
        if H3_REQUIRED_RE.search(body) and detail:
            blocks.append(detail.group(1))
    if not blocks:
        return issues

    for block_index, detail in enumerate(blocks, 1):
        shots = list(re.finditer(
            r"(?m)^\s*\[Shot\s+\d+\].*?(?=^\s*\[Shot\s+\d+\]|\Z)",
            detail,
            re.S,
        ))
        if not shots:
            issue(issues, "ERROR", "external-h3-shot-missing", f"第 {block_index} 个 H3 没有可识别的 [Shot N] 镜头")
            continue
        for shot in shots:
            shot_text = shot.group(0)
            label = re.search(r"\[Shot\s+(\d+)\]", shot_text)
            number = label.group(1) if label else "?"
            if not EXTERNAL_TIME_RE.search(shot_text):
                issue(issues, "ERROR", "external-h3-timecode", f"H3 镜头 {number} 缺少 At MM:SS.mmm 局部时间码")
            if not EXTERNAL_SHOT_SIZE_RE.search(shot_text):
                issue(issues, "ERROR", "external-h3-shot-size", f"H3 镜头 {number} 缺少英文景别（如 medium shot / close-up）")
            if not EXTERNAL_CAMERA_RE.search(shot_text):
                issue(issues, "ERROR", "external-h3-camera", f"H3 镜头 {number} 缺少机位或镜头运动语句")
        if not EXTERNAL_FOCUS_RE.search(detail):
            issue(issues, "ERROR", "external-h3-focus", f"第 {block_index} 个 H3 缺少对焦或景深信息")
        if not EXTERNAL_LIGHT_RE.search(detail):
            issue(issues, "ERROR", "external-h3-light", f"第 {block_index} 个 H3 缺少光影或曝光信息")
    return issues


def validate_text(text, strict=False, scope="internal"):
    card_strict = strict and scope == "internal"
    issues, sections = validate_cards(text, card_strict)
    issues.extend(validate_h3_alignment(text, sections, strict))
    if scope == "external-h3" and strict:
        issues.extend(validate_external_h3(text))
    return issues, len(sections)


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验专业级逐镜镜头语言卡")
    parser.add_argument("files", nargs="+", help="Markdown 文件，使用 - 从标准输入读取")
    parser.add_argument("--strict", action="store_true", help="缺少镜头语言卡也报 ERROR")
    parser.add_argument(
        "--scope",
        choices=("internal", "external-h3"),
        default="internal",
        help="internal 验收完整规划稿；external-h3 只验收用户可见的 H3 交付稿，不因隐藏镜头卡缺失失败",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    results = []
    for name in args.files:
        text = sys.stdin.read() if name == "-" else Path(name).read_text(encoding="utf-8")
        issues, cards = validate_text(text, args.strict, args.scope)
        results.append({"file": name, "cards": cards, "issues": [{"level": level, "message": msg} for level, msg in issues]})

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"{result['file']}: cards={result['cards']}")
            for item in result["issues"]:
                print(f"{item['level']}: {item['message']}")
    return 1 if any(item["level"] == "ERROR" for result in results for item in result["issues"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
