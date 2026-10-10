#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_h3_prompt.py — ai-video-shot-designer 的 MiniMax H3 分段 Prompt 机械校验器。

把 Skill“交付前静默检查”里可机械化的部分固化为可重复运行的规则：
  - 六字段是否齐全、顺序是否正确、是否重复；
  - 是否只使用项目允许的 H3 标签 <Subject/Picture/Video/Audio N>，且使用前已定义；
  - summary 是否以适配任务前缀开头；retention_analysis 是否使用项目约定枚举；
  - detailed_description 的 At MM:SS.mmm 是否单调递增、是否超过单段时长上限；
  - 台词是否包在 <d>[Language] ... </d>；是否混入 Visual:/Action:/Camera: 等自定义字段；
  - 六字段块内是否误塞 continuity_in/generation_inputs 等内部字段；
  - 是否存在未知字段、空字段、重复标签或未定义标签；
  - 文档中显式标记为历史基线的代码块可跳过，避免回归样例污染结果。
  - 中文生成设置里“本段时间线”的时长是否超限；声音字段句数是否在建议范围。

数值口径读取目标 Adapter 配置；单段硬上限默认 15s，可用 --max-duration 覆盖。

用法：
  python3 scripts/validate_h3_prompt.py FILE [FILE ...]
  python3 scripts/validate_h3_prompt.py --json path/to/h3-prompt.md
  cat draft.txt | python3 scripts/validate_h3_prompt.py -

退出码：存在 ERROR 返回 1，否则返回 0（WARNING 不改变退出码）。
"""

import argparse
import json
import re
import sys

import adapter_config

ADAPTER = adapter_config.by_contract("minimax-h3-direct-v1")
if ADAPTER is None:  # pragma: no cover
    raise RuntimeError("missing minimax-h3-direct-v1 adapter config")
FIELDS = list(ADAPTER["prompt"]["fields"])
KNOWN_PREFIXES = tuple(ADAPTER["prompt"]["known_prefixes"])
DEFAULT_MAX_DURATION = adapter_config.limit(ADAPTER, "unit_duration_seconds", "max")
LEGAL_TAG_KINDS = ("Subject", "Picture", "Video", "Audio")
VIS_ENUMS = {"fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference"}
AUD_ENUMS = {"fully_copy", "partially_copy", "reference", "weak_reference"}
ALL_ENUMS = VIS_ENUMS | AUD_ENUMS

# A baseline/example block can be preceded by this marker. Capture the marker
# with the fence so validate_text can omit it without changing normal drafts.
FENCE_RE = re.compile(
    r"(?P<ignore><!--\s*h3-validator\s*:\s*ignore\s*-->\s*)?"
    r"```[A-Za-z0-9_-]*\r?\n(?P<body>.*?)```",
    re.S | re.I,
)
TAG_RE = re.compile(r"<(Subject|Picture|Video|Audio)\s+(\d+)>")
MALFORMED_TAG_RE = re.compile(r"</?(Subject|Picture|Video|Audio)(\d+)>")
# Definitions are line-oriented; references to a tag inside its description
# must not be mistaken for a second definition. H3 examples in the wild use
# both "<Subject 1> is ..." and the concise "<Subject 1> ..." form, so both
# are accepted as long as a non-empty description follows the tag.
DEFINITION_RE = re.compile(
    r"(?m)^\s*<(Subject|Picture|Video|Audio)\s+(\d+)>\s*"
    r"(?:(?:is|=)\s*)?(.+\S)\s*$"
)
ILLEGAL_TAG_RE = re.compile(r"</?\s*([A-Za-z]+)\s*\d*\s*>")
TIME_RE = re.compile(r"At\s+(\d{1,2}):(\d{2}\.\d{3})")
SHOT_RE = re.compile(r"\[Shot\s+\d+\]")
D_RE = re.compile(r"<d>(.*?)</d>", re.S)
D_RAW_RE = re.compile(r"<d>")
D_CLOSE_RE = re.compile(r"</d>")
TIMELINE_RE = re.compile(r"本段时间线：\s*(\d{1,2}):(\d{2}(?:\.\d+)?)\s*[—\-–]\s*(\d{1,2}):(\d{2}(?:\.\d+)?)")
FORBIDDEN_CUSTOM_RE = re.compile(r"(?im)^\s*(visual|action|camera|motion|lighting|sound)\s*:")
FORBIDDEN_INTERNAL_RE = re.compile(
    r"(?m)^\s*(continuity_in|continuity_out|generation_inputs|state_diff|handoff_frame|"
    r"continuity_mode|generation_duration|overlap_duration|usable_duration|audio_handoff|"
    r"shot_handoff_in|shot_handoff_out|shot_transition)\s*:"
)


def to_sec(m, s):
    return int(m) * 60 + float(s)


def field_spans(block):
    """返回 {field: (header_start, content_start, content_end)}，按出现位置。"""
    spans = {}
    hits = []
    for f in FIELDS:
        m = re.search(r"(?m)^" + re.escape(f) + r"\s*:\s*", block)
        if m:
            hits.append((m.start(), m.end(), f))
    hits.sort()
    for i, (hs, ce, f) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(block)
        spans[f] = (hs, ce, end)
    return spans


def count_sentences(text):
    parts = [p for p in re.split(r"[.!?]+", text) if p.strip()]
    return len(parts)


def shot_numbers(text):
    """Return the ordered [Shot N] numbers found in a detailed description."""
    return [int(n) for n in re.findall(r"\[Shot\s+(\d+)\]", text)]


def validate_shot_structure(dd, err, warn):
    """Validate lightweight shot/timecode alignment without over-constraining prose."""
    numbers = shot_numbers(dd)
    if numbers:
        # Some production ledgers number shots globally across the film while
        # others restart at 1 for each unit. Both are valid; reject only
        # duplicate or backwards numbering, which is unambiguously broken.
        if any(b <= a for a, b in zip(numbers, numbers[1:])):
            err("shot-order", f"[Shot N] 必须严格递增，当前为: {', '.join(map(str, numbers))}")

        # Every explicit shot section should have at least one local timecode.
        sections = re.split(r"(?=\[Shot\s+\d+\])", dd)
        missing_time = []
        for section in sections:
            match = re.match(r"\[Shot\s+(\d+)\]", section.strip())
            if match and not TIME_RE.search(section):
                missing_time.append(match.group(1))
        if missing_time:
            warn("shot-time-missing", f"[Shot {', '.join(missing_time)}] 未找到 At MM:SS.mmm 局部时间码")


def validate_block(block, idx, max_duration):
    """校验一个含 subject_definitions 的六字段块。"""
    issues = []
    err = lambda code, msg: issues.append(("ERROR", f"block#{idx} {code}: {msg}"))
    warn = lambda code, msg: issues.append(("WARNING", f"block#{idx} {code}: {msg}"))

    # 1. 字段齐全性 + 顺序 + 重复 + 未知字段
    all_headers = re.findall(r"(?m)^\s*([a-z][a-z0-9_]*)\s*:\s*", block)
    unknown_headers = sorted(set(all_headers) - set(FIELDS))
    if unknown_headers:
        err("unknown-field", f"出现未知字段: {', '.join(unknown_headers)}；六字段块只能包含官方字段")

    present_order = []
    for f in FIELDS:
        occ = [m.start() for m in re.finditer(r"(?m)^" + re.escape(f) + r"\s*:", block)]
        if len(occ) > 1:
            err("duplicate-field", f"字段 {f} 出现 {len(occ)} 次，只能出现一次")
        if occ:
            present_order.append((f, occ[0]))
    missing = [f for f in FIELDS if f not in dict(present_order)]
    if missing:
        err("missing-field", f"缺少六字段: {', '.join(missing)}")
    ordered = [f for f, _ in sorted(present_order, key=lambda x: x[1])]
    expected = [f for f in FIELDS if f in dict(present_order)]
    if ordered and ordered != expected:
        err("field-order", f"字段顺序错误: {' -> '.join(ordered)}；应为 {' -> '.join(expected)}")

    spans = field_spans(block)

    def content(f):
        return block[spans[f][1]:spans[f][2]].strip() if f in spans else ""

    empty = [f for f in FIELDS if f in spans and not content(f)]
    if empty:
        err("empty-field", f"字段不能为空: {', '.join(empty)}")

    # 2. 标签合法性 + 先定义后使用
    defined, used = {}, {}
    subj_text = content("subject_definitions")
    definitions = DEFINITION_RE.findall(subj_text)
    if not definitions:
        err("subject-definitions-empty", "subject_definitions 至少要定义一个 H3 标签")
    for kind, num, _description in definitions:
        key = (kind, int(num))
        if key in defined:
            err("duplicate-tag-definition", f"{kind} {num} 在 subject_definitions 中重复定义")
        defined[(kind, int(num))] = True
    body_after_def = block[spans["summary"][1]:] if "summary" in spans else block
    for kind, num in TAG_RE.findall(body_after_def):
        used[(kind, int(num))] = True
    for m in ILLEGAL_TAG_RE.finditer(block):
        kind = m.group(1)
        if kind not in LEGAL_TAG_KINDS and kind not in ("d", "scenetrans", "cutoff"):
            err("illegal-tag", f"出现未允许标签 <{kind}>；只允许 Subject/Picture/Video/Audio 与 d/scenetrans/cutoff")
    malformed = sorted({f"<{kind}{num}>" for kind, num in MALFORMED_TAG_RE.findall(block)})
    if malformed:
            err("malformed-tag", f"H3 标签必须在类别与编号之间保留空格: {', '.join(malformed)}")
    for tag in sorted(used):
        if tag not in defined:
            err("tag-undefined", f"<{tag[0]} {tag[1]}> 在 subject_definitions 之后被使用，但未在其中定义")
    for tag in sorted(defined):
        if tag not in used:
            warn("tag-unused", f"<{tag[0]} {tag[1]}> 已定义但后文未使用，确认是否冗余")

    # 3. summary 前缀
    summary = content("summary")
    if summary:
        head = summary.lstrip()
        m = re.match(r"^\[([^\]]+)\]", head)
        if not m:
            err("summary-prefix", "summary 必须以项目适配任务前缀开头，如 [reference generation]")
        elif head[: len(KNOWN_PREFIXES[0])] and not any(head.startswith(p) for p in KNOWN_PREFIXES):
            warn("summary-prefix-unknown", f"前缀 [{m.group(1)}] 不在已知列表，确认是否为当前官方写法")

    # 4. retention_analysis 枚举
    retention = content("retention_analysis")
    if retention:
        found = set(re.findall(r"[a-z_]+_(?:preserved|copy|transfer|reference)|weak_reference|attribute_transfer|reference", retention))
        found = {x for x in found if "_" in x or x == "reference"}
        if not found:
            warn("retention-enum", "retention_analysis 未出现任何合法保留度枚举（fully_preserved / partially_copy 等）")
        else:
            bad = {x for x in found if x not in ALL_ENUMS}
            if bad:
                warn("retention-enum", f"存在疑似非法保留度取值: {', '.join(sorted(bad))}")

    # 5. detailed_description
    dd = content("detailed_description")
    if dd:
        if not SHOT_RE.search(dd):
            warn("shot-missing", "detailed_description 中没有 [Shot N] 分段")
        else:
            validate_shot_structure(dd, err, warn)
        if FORBIDDEN_CUSTOM_RE.search(dd):
            err("custom-field", "detailed_description 不允许 Visual:/Action:/Camera: 等自定义字段，请改为自然段落")
        secs = [to_sec(mn, ss) for mn, ss in TIME_RE.findall(dd)]
        if secs and secs[0] > 1e-6:
            warn("time-start", f"第一个显式镜头时间码为 {secs[0]:.3f}s；若前文未明确描述首帧，建议补充 At 00:00.000")
        if any(b < a for a, b in zip(secs, secs[1:])):
            err("time-order", "At MM:SS.mmm 时间码不是单调递增")
        if secs and max(secs) > max_duration + 1e-6:
            err("time-overflow", f"镜头时间码最大 {max(secs):.3f}s 超过单段上限 {max_duration}s")
        # 台词标签
        for dm in D_RE.finditer(dd):
            inner = dm.group(1)
            if not inner.lstrip().startswith("["):
                err("dialogue-language", "<d> 后必须以 [Language] 标注语言，如 <d>[Chinese]... </d>")
        # 检测写了 <d> 但没闭合
        if len(D_RAW_RE.findall(dd)) != len(D_RE.findall(dd)) or len(D_CLOSE_RE.findall(dd)) != len(D_RE.findall(dd)):
            err("dialogue-unbalanced", "<d> 与 </d> 数量不匹配，台词标签未正确闭合")

    # 6. 六字段块内不得出现内部字段
    bad_internal = sorted(set(m.group(1) for m in FORBIDDEN_INTERNAL_RE.finditer(block)))
    if bad_internal:
        err("internal-in-block", f"内部字段不得写进六字段块，应放在块前中文生成设置: {', '.join(bad_internal)}")

    # 7. 声音句数（建议项）
    osc = content("overall_soundscape")
    if osc and osc.strip() != "N/A":
        n = count_sentences(osc)
        if n > 4:
            warn("soundscape-length", f"overall_soundscape 建议 1—4 句，当前约 {n} 句")
    nm = content("non_diegetic_music")
    if nm and nm.strip() != "N/A":
        n = count_sentences(nm)
        if n > 3:
            warn("music-length", f"non_diegetic_music 建议 1—3 句，当前约 {n} 句")

    return issues


def validate_text(text, max_duration):
    issues = []
    blocks = []
    for match in FENCE_RE.finditer(text):
        if match.group("ignore"):
            continue
        body = match.group("body")
        if re.search(r"(?m)^subject_definitions\s*:", body):
            blocks.append(body)
    if not blocks:
        issues.append(("WARNING", "未发现任何含 subject_definitions 的六字段块"))
    for i, b in enumerate(blocks, 1):
        issues.extend(validate_block(b, i, max_duration))

    # 中文生成设置：本段时间线时长
    for m in TIMELINE_RE.finditer(text):
        dur = to_sec(m.group(3), m.group(4)) - to_sec(m.group(1), m.group(2))
        if dur > max_duration + 1e-6:
            issues.append(("ERROR", f"本段时间线时长 {dur:.1f}s 超过单段上限 {max_duration}s"))
        if dur <= 0:
            issues.append(("ERROR", "本段时间线结束时间早于或等于开始时间"))
    return issues, len(blocks)


def main():
    ap = argparse.ArgumentParser(description="MiniMax H3 分段 Prompt 机械校验器")
    ap.add_argument("files", nargs="+", help="待校验文件；- 表示标准输入")
    ap.add_argument("--max-duration", type=float, default=DEFAULT_MAX_DURATION,
                    help=f"单段项目契约上限秒数，默认 {DEFAULT_MAX_DURATION:g}（来自 Adapter 配置）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args()

    report = {}
    total_err = 0
    for path in args.files:
        if path == "-":
            text, shown = sys.stdin.read(), "<stdin>"
        else:
            try:
                with open(path, encoding="utf-8") as fh:
                    text, shown = fh.read(), path
            except OSError as e:
                report[path] = {"error": f"无法读取: {e}"}
                total_err += 1
                continue
        issues, nblocks = validate_text(text, args.max_duration)
        report[shown] = {"blocks": nblocks, "issues": issues}
        total_err += sum(1 for lvl, _ in issues if lvl == "ERROR")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for shown, data in report.items():
            if "error" in data:
                print(f"[{shown}] {data['error']}")
                continue
            print(f"[{shown}] 六字段块 {data['blocks']} 个")
            if not data["issues"]:
                print("  PASS  无 ERROR / WARNING")
            for lvl, msg in data["issues"]:
                print(f"  {lvl:<7} {msg}")
        print("-" * 48)
        print(f"汇总：ERROR={total_err}")

    sys.exit(1 if total_err else 0)


if __name__ == "__main__":
    main()
