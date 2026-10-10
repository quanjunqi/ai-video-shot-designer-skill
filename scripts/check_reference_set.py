#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_reference_set.py — 分段参考图“最小集合 / 必选可选禁止 / 跨段尾帧”门禁。

reference-selection-rules.md 要求每段自动选出必选、可选、禁止混用三类参考图，
但这份清单原本只是块前自由文本，没有任何程序核对它和 H3 六字段是否一致。本脚本
把同一单元的“中文生成设置”与其后的六字段块配对，做确定性核对：

  - 同一标签既在必选/可选又在禁止混用 → ERROR（自相矛盾）；
  - 禁止混用的标签却在 subject_definitions 定义/使用 → ERROR（冲突参考被绑定）；
  - 必选标签没有在 subject_definitions 定义 → ERROR（要上传的图没注册）；
  - 六字段定义了的标签既没被选也没被禁 → WARNING（最小集合漏记账）；
  - 非首段必选必须含“上一段实际尾帧图”，首段不得引用上一段尾帧 → ERROR；
  - 参考图数量超出 platform-spec §4 默认 0—8 张区间 → WARNING（默认值非平台硬限）。

只解析结构化标签，不猜测自由文本语义；解析不到三类清单时给 WARNING 而非放行。

用法：
  python3 scripts/check_reference_set.py FILE [FILE ...]
  cat draft.md | python3 scripts/check_reference_set.py -
退出码：存在 ERROR 返回 1，否则 0（WARNING 不改变退出码）。
"""

import argparse
import json
import re
import sys

FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*\r?\n(?P<body>.*?)```", re.S | re.I)
DEFINITION_RE = re.compile(r"(?m)^\s*<(Subject|Picture|Video|Audio)\s+(\d+)>")
USED_RE = re.compile(r"<(Subject|Picture|Video|Audio)\s+(\d+)>")
# 参考数量默认区间（platform-spec §4，【默认】值，故只给 WARNING）。
# The minimum set is genuinely minimal: a simple H3-only delivery may need no
# image, and a small scene may need only one to three. Only excess is noisy.
REF_MIN, REF_MAX = 0, 8

KIND_RUN_RE = re.compile(r"(Subject|Picture|Video|Audio)\s*((?:\d+[\s、,，和及~～\-—––]*)+)", re.I)
SINGLE_RE = re.compile(r"<?(Subject|Picture|Video|Audio)\s+(\d+)>?")
# 实际尾帧图的同义表述：尾帧 / 交接帧 / 稳定帧 / tailframe。
TAIL_IMAGE_RE = re.compile(r"(?:上一?[段单元]|前一?[段单元]|第\s*\d+\s*段).{0,12}(?:尾帧|交接帧|稳定帧|tailframe)|实际尾帧|尾帧图")
# 连续性输入里“声明复现某段”的弱信号（不一定带尾帧字样）。
REPRODUCE_RE = re.compile(r"复现.{0,12}(?:上一?[段单元]|前一?[段单元]|第\s*\d+\s*段)")
# 只有“本段首帧独立起始”才豁免上一段尾帧；段内出现“闪回”本身不等于
# 本段从闪回开始，不能因此跳过真实跨段状态输入。
TRANSITION_EXEMPT_RE = re.compile(
    r"独立回忆首帧|独立[^\n。；;]{0,8}首帧|不复现(?:上一段|前一段|前段)"
)
PENDING_TAIL_RE = re.compile(r"待用户上传|待上传|未上传|待提供|缺失|placeholder", re.I)
INDEPENDENT_TRANSITIONS = {"flashback", "independent_start", "闪回", "独立起始"}


def _cap(kind: str) -> str:
    table = {"subject": "Subject", "picture": "Picture", "video": "Video", "audio": "Audio"}
    return table.get(kind.lower(), kind.capitalize())


def _expand_numbers(token: str):
    """把 '1、2、3' 与区间 '1–6, 11–12' 一并展开为去重整数序列。"""
    nums = []
    for match in re.finditer(r"(\d+)\s*[–—~-]\s*(\d+)", token):  # 区间 a–b
        lo, hi = int(match.group(1)), int(match.group(2))
        nums.extend(range(lo, hi + 1))
    cleaned = re.sub(r"\d+\s*[–—~-]\s*\d+", " ", token)
    nums.extend(int(x) for x in re.findall(r"\d+", cleaned))      # 枚举
    return sorted(set(nums))


def expand_tags(text: str):
    """展开 'Subject 1、2、3'、'Subject 1–6'、'Picture 1' 等简写为标签集合。"""
    tags = set()
    if not text:
        return tags
    for match in KIND_RUN_RE.finditer(text):
        kind = _cap(match.group(1))
        for num in _expand_numbers(match.group(2)):
            tags.add(f"{kind} {num}")
    for match in SINGLE_RE.finditer(text):
        tags.add(f"{_cap(match.group(1))} {int(match.group(2))}")
    return tags


def labeled(text: str, label: str):
    match = re.search(r"(?m)^\s*" + re.escape(label) + r"\s*[：:]\s*(.+?)\s*$", text)
    if not match:
        return None
    value = match.group(1)
    return value.strip()


def is_none_value(value: str) -> bool:
    return value is None or re.sub(r"[\s。.，,；;]", "", value) in {"无", "没有", "不适用", "N/A", "NA"}


def tail_is_tagged(required_text: str, optional_text: str) -> bool:
    """判断尾帧说明是否已经附着在一个已计数的 H3 标签上。"""
    combined = f"{required_text or ''} {optional_text or ''}"
    return bool(re.search(
        r"<(?:Subject|Picture|Video|Audio)\s+\d+>[^\n；;]{0,48}"
        r"(?:尾帧|交接帧|稳定帧|tailframe)",
        combined,
        re.I,
    ))


def has_positive_tail_reference(text: str) -> bool:
    """Explicitly negated tail-frame mentions are not selected references."""
    cleaned = re.sub(
        r"(?:无|没有|不存在的?|不适用)[^\n；;]{0,12}(?:上一?[段单元]|前一?[段单元])?"
        r"[^\n；;]{0,8}(?:实际)?(?:尾帧|交接帧|稳定帧|tailframe)(?:图)?",
        "",
        text or "",
        flags=re.I,
    )
    return bool(TAIL_IMAGE_RE.search(cleaned))


def extract_units(text: str):
    units, pending = [], None
    for fence in FENCE_RE.finditer(text):
        body = fence.group("body")
        if re.search(r"(?m)^\s*生成单元\s*[：:]", body):
            num = re.search(r"(?m)^\s*生成单元\s*[：:]\s*(\d+)", body)
            pending = {"num": int(num.group(1)) if num else None, "settings": body, "h3": None}
            units.append(pending)
        elif re.search(r"(?m)^subject_definitions\s*:", body) and pending is not None and pending["h3"] is None:
            pending["h3"] = body
    return units


def h3_tags(h3: str):
    if not h3:
        return set(), set()
    defined = {f"{_cap(k)} {int(n)}" for k, n in DEFINITION_RE.findall(h3)}
    used = {f"{_cap(k)} {int(n)}" for k, n in USED_RE.findall(h3)}
    return defined, used


def check_unit(unit, order, err, warn):
    s = unit["settings"]
    idx = unit["num"] if unit["num"] is not None else order
    req_raw, opt_raw, ban_raw = labeled(s, "必选"), labeled(s, "可选"), labeled(s, "禁止混用")
    materials = labeled(s, "生成素材") or ""
    raw_in = labeled(s, "连续性输入") or ""
    cross_ref = labeled(s, "跨段状态参考") or ""
    transition_value = labeled(s, "时空转换") or ""
    transition_type = labeled(s, "转换类型") or ""

    # 旧格式可能只有“生成素材”而没有必选/可选/禁止三清单：此时只提示一次，
    # 不做逐标签记账（否则会对每个已定义标签刷一条 defined-not-selected 噪声）。
    lists_present = [name for name, raw in
                     (("必选", req_raw), ("可选", opt_raw), ("禁止混用", ban_raw)) if raw is not None]
    accounting = len(lists_present) == 3
    if not lists_present:
        warn("selection-lists-missing",
             f"单元{idx} 缺少“必选/可选/禁止混用”三清单（旧格式），无法核对最小参考集合")
    elif not accounting:
        missing = {"必选", "可选", "禁止混用"} - set(lists_present)
        warn("selection-field-missing", f"单元{idx} 缺少“{'、'.join(sorted(missing))}”清单（无冲突也应写“无”）")

    required = expand_tags(req_raw or "")
    optional = expand_tags(opt_raw or "")
    forbidden = set() if is_none_value(ban_raw) else expand_tags(ban_raw or "")
    defined, used = h3_tags(unit["h3"])

    # 1. 自相矛盾
    for tag in sorted((required | optional) & forbidden):
        err("selection-conflict", f"单元{idx} 标签 {tag} 同时出现在选图清单与“禁止混用”中")
    # 2. 禁止混用却被绑定/使用
    for tag in sorted(forbidden & (defined | used)):
        err("forbidden-reference-bound", f"单元{idx} 被禁止混用的 {tag} 仍在六字段中定义或使用")
    # 3. 必选未注册
    for tag in sorted(required - defined):
        err("required-tag-undefined", f"单元{idx} 必选参考 {tag} 未在 subject_definitions 定义，无法上传追踪")
    if accounting:
        # 4. 可选未注册（弱）
        for tag in sorted(optional - defined):
            warn("optional-tag-undefined", f"单元{idx} 可选参考 {tag} 未在 subject_definitions 定义")
        # 5. 定义了却既没选也没禁（最小集合记账）
        for tag in sorted(defined - (required | optional | forbidden)):
            warn("defined-not-selected", f"单元{idx} 六字段定义了 {tag}，但必选/可选/禁止混用均未提及，确认是否冗余上传")

    # 6. 跨段尾帧（分两级：静默另起=ERROR；仅文字声明复现但没选尾帧图=WARNING）
    selection_text = f"{req_raw or ''} {opt_raw or ''} {materials} {cross_ref}"
    has_tail = has_positive_tail_reference(selection_text)
    tail_in_required = has_positive_tail_reference(req_raw or "")
    tail_pending = bool(PENDING_TAIL_RE.search(selection_text)) if has_tail else False
    typed = transition_type.strip()
    exempt = typed in INDEPENDENT_TRANSITIONS or (
        not typed and bool(TRANSITION_EXEMPT_RE.search(raw_in) or transition_value.strip() == "是"))
    if order == 1:
        if has_tail:
            err("first-unit-fake-tail", f"单元{idx} 是首段，不存在上一段实际尾帧，不得把它列为参考")
    elif tail_pending:
        err("cross-tail-pending", f"单元{idx} 的上一段尾帧仍标记为待上传/缺失，不能当作已就绪的状态输入")
    elif has_tail and not tail_in_required:
        err("cross-tail-not-required", f"单元{idx} 已列出上一段尾帧，但没有放入“必选”参考图清单")
    elif has_tail:
        pass  # 已选实际尾帧图（即使本段内含时空转换，首帧仍承接上一段）
    elif exempt:
        warn("cross-tail-exempt-transition",
             f"单元{idx} 声明时空转换/闪回并以独立首帧开始，豁免上一段尾帧；确认这是剧本明确的时空切换")
    elif REPRODUCE_RE.search(raw_in):
        warn("cross-tail-image-missing",
             f"单元{idx} 文字声明复现上一段，但必选/生成素材未列出实际尾帧图，平台将缺少首帧状态锚点")
    else:
        err("cross-tail-missing",
            f"单元{idx} 为跨段单元，既未选上一段实际稳定尾帧图，也未声明复现或时空转换，存在跨段漂移风险")

    # 7. 数量控制（默认区间，WARNING；三清单齐全时才统计）
    if accounting:
        # An untagged filename such as “第1段实际尾帧图” is one extra image;
        # a tagged annotation such as “<Picture 3>（第1段实际尾帧图）” is
        # already included in the official-tag count.
        tail_count = 1 if has_tail and order > 1 and not tail_is_tagged(req_raw, opt_raw) else 0
        count = len(required | optional) + tail_count
        if count > REF_MAX:
            warn("reference-count", f"单元{idx} 参考图约 {count} 张，超出默认 {REF_MIN}—{REF_MAX} 张区间，按最小集合与平台上限复核")


def validate_text(text: str):
    issues = []
    err = lambda code, msg: issues.append(("ERROR", code, msg))
    warn = lambda code, msg: issues.append(("WARNING", code, msg))
    units = extract_units(text)
    for order, unit in enumerate(units, 1):
        check_unit(unit, order, err, warn)
    if not units:
        issues.append(("WARNING", "no-unit", "未发现任何含“生成单元”的中文生成设置围栏"))
    return issues, len(units)


def main():
    ap = argparse.ArgumentParser(description="分段参考图最小集合与跨段尾帧门禁")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report, total_err = {}, 0
    for path in args.files:
        if path == "-":
            text, shown = sys.stdin.read(), "<stdin>"
        else:
            try:
                text, shown = open(path, encoding="utf-8").read(), path
            except OSError as exc:
                report[path] = {"error": f"无法读取: {exc}"}
                total_err += 1
                continue
        issues, n = validate_text(text)
        report[shown] = {"units": n, "issues": issues}
        total_err += sum(1 for lvl, _, _ in issues if lvl == "ERROR")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for shown, data in report.items():
            if "error" in data:
                print(f"[{shown}] {data['error']}")
                continue
            print(f"[{shown}] 生成单元 {data['units']} 个")
            if not data["issues"]:
                print("  PASS  无 ERROR / WARNING")
            for lvl, code, msg in data["issues"]:
                print(f"  {lvl:<7} {code}: {msg}")
        print("-" * 48)
        print(f"汇总：ERROR={total_err}")
    sys.exit(1 if total_err else 0)


if __name__ == "__main__":
    main()
