#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_continuity.py — ai-video-shot-designer 的动作三态闭环与跨段状态门禁。

validate_h3_prompt.py 只能校验“单个六字段块内部”的时间码与结构，不携带任何
跨块记忆，因此无法发现“上一段尾帧 vs 下一段首帧”的状态翻转。本脚本补上这块：

  1. 动作三态闭环（段内）：首帧锚点（起点）→ 变化（过程）→ 尾帧锚点（终点）。
     凡首帧与尾帧取值不同的状态槽，必须在“变化”里登记一条 from→to，且首尾值
     必须与之一致；多登、漏登、登错都报 ERROR。
  2. 跨段状态交接（段间）：第 N 段尾帧必须逐项等于第 N+1 段首帧。只有当下一段
     显式声明“时空转换：是”时，场景级状态槽（场景/时间/天气/主光）才允许变化，
     实体状态槽（位置/朝向/持有者等）仍须保持，除非在“跨段重置”里逐项列出。
  3. 向后兼容：生成设置里没有结构化“状态锚点”时，不臆测自由文本语义，只做
     “跨段必须复现尾帧 / 首段不得虚构上一段”的弱检查，并给 WARNING 标明本段
     无法机器校验，绝不把“没写锚点”伪装成通过。

状态锚点写在每个单元的中文“生成设置”围栏内（不进 H3 六字段），格式见
references/production/units.md：

    状态锚点（机器校验）：
    首帧：场景=车间；主光=昏灯顶光；[林丛]位置=画面左；[撬棍]持有者=林丛
    尾帧：场景=车间；主光=昏灯顶光；[林丛]位置=背景闸门；[撬棍]持有者=闸门手轮
    变化：[撬棍]持有者 林丛→闸门手轮；[林丛]位置 画面左→背景闸门
    时空转换：否

用法：
  python3 scripts/check_continuity.py FILE [FILE ...]
  cat draft.md | python3 scripts/check_continuity.py -
  python3 scripts/check_continuity.py --json draft.md

退出码：存在 ERROR 返回 1，否则返回 0（WARNING 不改变退出码）。
"""

import argparse
import json
import re
import sys

# 与 validate_h3_prompt.FENCE_RE 同口径：抓取所有三反引号围栏正文。
FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*\r?\n(?P<body>.*?)```", re.S | re.I)

# 场景级状态槽：跨段仅在显式“时空转换：是”时允许变化。
SCENE_GLOBAL_SLOTS = {"场景", "时间", "天气", "主光"}
# 实体状态槽可识别的属性名（[主体]属性=值）。
ENTITY_ATTRS = {"位置", "朝向", "持有者", "手别", "可见", "服装", "伤势",
                "状态", "发声方", "文字状态", "音频状态"}
GLOBAL_SLOTS = SCENE_GLOBAL_SLOTS | {"机位轴", "画幅", "通信状态", "声音桥"}
# 光影锚点受控槽（见 references/planning/shots.md）。都是场景级槽，
# 跨段默认锁定，仅在“时空转换：是”或列入“跨段重置”时允许变化。
LIGHT_SLOTS = {"主光位", "世界源", "色温", "白平衡锚", "光质", "光比", "轮廓", "主体分离"}
# 其中跨段必须锁定的核心槽（其余为记录性槽，同样比对但这三个是硬要求）。
LIGHT_LOCK_SLOTS = {"主光位", "色温", "光质"}
TRANSITION_TYPES = {"none", "continuous_space", "hard_location_cut", "time_jump",
                    "flashback", "independent_start"}
INDEPENDENT_TRANSITIONS = {"flashback", "independent_start"}

ARROW_RE = re.compile(r"(?:→|->|=>)")
ASSIGN_RE = re.compile(r"^(?:\[([^\]]+)\])?\s*([^=：:]+?)\s*[=：]\s*(.*)$")
SLOTREF_RE = re.compile(r"^(?:\[([^\]]+)\])?\s*(.+?)\s*$")

# 方向类取值的受控词归一：只对“纯方向值”做同义归并，复合位置保持原文。
_LEFT = {"左", "画面左", "画面左侧", "画面左边", "左侧", "左边", "left", "camera left", "camera-left"}
_RIGHT = {"右", "画面右", "画面右侧", "画面右边", "右侧", "右边", "right", "camera right", "camera-right"}


def norm_value(value: str) -> str:
    """归一状态值：去空白、全角转半角空格、纯方向值归并到 左/右。"""
    text = re.sub(r"\s+", "", str(value)).lower()
    if text in _LEFT:
        return "左"
    if text in _RIGHT:
        return "右"
    return text


def norm_light_value(slot: str, value: str) -> str:
    """光影槽归一：色温只取开尔文数字（2800K钨丝/2800k → 2800k），其余走通用归一。"""
    text = norm_value(value)
    if slot == "色温":
        m = re.search(r"(\d{3,5})\s*k?", text)
        if m:
            return f"{int(m.group(1))}k"
    return text


def slot_key(entity, attr):
    attr = re.sub(r"\s+", "", attr)
    if entity:
        entity = re.sub(r"\s+", "", entity)
        return f"[{entity}]{attr}"
    return attr


def parse_slot_assignments(line: str) -> dict:
    """把 '场景=A；[甲]位置=画面左；[棍]持有者=甲' 解析为 {slot_key: value}。"""
    result = {}
    if not line:
        return result
    for item in re.split(r"[;；]", line):
        item = item.strip()
        if not item:
            continue
        match = ASSIGN_RE.match(item)
        if not match:
            continue
        entity, attr, value = match.group(1), match.group(2), match.group(3)
        key = slot_key(entity, attr)
        result[key] = norm_light_value(attr, value) if (not entity and attr.strip() in LIGHT_SLOTS) \
            else norm_value(value)
    return result


_ATTR_ALT = "|".join(
    sorted(set(ENTITY_ATTRS) | set(GLOBAL_SLOTS) | set(LIGHT_SLOTS), key=len, reverse=True))
CHANGE_LEFT_RE = re.compile(r"^(?:\[([^\]]+)\])?\s*(" + _ATTR_ALT + r")\s*(.*)$")


def parse_changes(line: str):
    """解析 '[实体]属性 起点→终点；属性 起点→终点'，返回 [(slot_key, from, to)]。

    属性名取自受控集合（位置/朝向/持有者/场景/主光/机位轴…），属性之后、箭头
    之前的部分是起点值；这样才能把“位置 画面左→背景闸门”正确切成三段。
    """
    changes = []
    if not line:
        return changes
    for item in re.split(r"[;；]", line):
        item = item.strip()
        if not item:
            continue
        parts = ARROW_RE.split(item)
        if len(parts) != 2:
            changes.append((None, item.strip(), None))  # 畸形，留给校验报错
            continue
        left_match = CHANGE_LEFT_RE.match(parts[0].strip())
        if not left_match:
            changes.append((None, item.strip(), None))
            continue
        entity, attr, frm = left_match.group(1), left_match.group(2), left_match.group(3)
        normalize = (lambda v: norm_light_value(attr, v)) if (not entity and attr in LIGHT_SLOTS) \
            else norm_value
        changes.append((slot_key(entity, attr), normalize(frm), normalize(parts[1])))
    return changes


def parse_slot_ref_list(line: str):
    """解析 '跨段重置：场景；主光；[甲]位置' 为 slot_key 集合。"""
    refs = set()
    if not line:
        return refs
    for item in re.split(r"[;；,，、]", line):
        item = item.strip()
        if not item:
            continue
        match = SLOTREF_RE.match(item)
        if match:
            refs.add(slot_key(match.group(1), match.group(2)))
    return refs


def _labeled_line(text: str, label: str):
    match = re.search(r"(?m)^\s*" + re.escape(label) + r"\s*[：:]\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else None


def parse_bool_zh(value: str):
    if value is None:
        return None
    head = re.sub(r"[\s（(].*$", "", value).strip()
    if head in {"是", "有", "yes", "true", "Y", "y"}:
        return True
    if head in {"否", "无", "no", "false", "N", "n"}:
        return False
    return None


def parse_transition_type(value: str):
    if value is None:
        return None
    aliases = {
        "无": "none", "否": "none", "none": "none",
        "连续空间": "continuous_space", "continuous_space": "continuous_space",
        "硬切地点": "hard_location_cut", "hard_location_cut": "hard_location_cut",
        "时间跳跃": "time_jump", "time_jump": "time_jump",
        "闪回": "flashback", "flashback": "flashback",
        "独立起始": "independent_start", "independent_start": "independent_start",
    }
    return aliases.get(value.strip(), value.strip())


def extract_units(text: str):
    """按文档顺序抽取生成单元。返回 [{num, order, settings, h3}]。"""
    units = []
    pending = None
    for fence in FENCE_RE.finditer(text):
        body = fence.group("body")
        is_settings = re.search(r"(?m)^\s*生成单元\s*[：:]", body) is not None
        is_h3 = re.search(r"(?m)^subject_definitions\s*:", body) is not None
        if is_settings:
            num_match = re.search(r"(?m)^\s*生成单元\s*[：:]\s*(\d+)", body)
            num = int(num_match.group(1)) if num_match else None
            pending = {"num": num, "settings": body, "h3": None}
            units.append(pending)
        elif is_h3 and pending is not None and pending["h3"] is None:
            pending["h3"] = body
    return units


def parse_unit_state(settings: str) -> dict:
    """从一段中文生成设置中解析状态锚点与弱检查所需的自由文本字段。"""
    first = _labeled_line(settings, "首帧")
    last = _labeled_line(settings, "尾帧")
    change_line = _labeled_line(settings, "变化") or _labeled_line(settings, "状态变化")
    has_anchor = first is not None and last is not None
    raw_in = _labeled_line(settings, "连续性输入") or ""
    raw_out = _labeled_line(settings, "连续性输出") or ""
    transition = parse_bool_zh(_labeled_line(settings, "时空转换"))
    transition_type = parse_transition_type(_labeled_line(settings, "转换类型"))
    reset = parse_slot_ref_list(_labeled_line(settings, "跨段重置") or "")
    light_line = _labeled_line(settings, "光影锚点（机器校验）")
    light = parse_slot_assignments(light_line) if light_line else {}
    return {
        "has_anchor": has_anchor,
        "first": parse_slot_assignments(first) if first else {},
        "last": parse_slot_assignments(last) if last else {},
        "changes": parse_changes(change_line) if change_line else [],
        "light": light,
        "transition": transition,
        "transition_type": transition_type,
        "reset": reset,
        "raw_in": raw_in,
        "raw_out": raw_out,
    }


def check_within_unit(state: dict, idx, err, warn):
    """动作三态闭环：首帧—变化—尾帧必须自洽。"""
    if not state["has_anchor"]:
        return
    first, last, changes = state["first"], state["last"], state["changes"]
    change_map = {}
    for slot, frm, to in changes:
        if slot is None:
            err("state-change-malformed", f"单元{idx} “变化”条目无法解析（缺少 A→B）：{frm}")
            continue
        change_map[slot] = (frm, to)

    for slot in sorted(set(first) | set(last)):
        a, b = first.get(slot), last.get(slot)
        declared = change_map.pop(slot, None)
        if a is not None and b is not None and a != b:
            if declared is None:
                err("state-change-undeclared",
                    f"单元{idx} 状态槽 {slot} 由「{a}」变为「{b}」，但“变化”未登记该起点→终点")
            elif declared[0] != a or declared[1] != b:
                err("state-change-mismatch",
                    f"单元{idx} 状态槽 {slot} 实际 {a}→{b}，但“变化”登记为 {declared[0]}→{declared[1]}")
        elif a is not None and b is not None and a == b and declared is not None:
            warn("state-change-redundant",
                 f"单元{idx} 状态槽 {slot} 首尾均为「{a}」，无需在“变化”中登记变化")
    # change_map 里剩下的都是锚点中不存在的槽
    for slot, (frm, to) in sorted(change_map.items()):
        err("state-change-orphan", f"单元{idx} “变化”登记了首/尾帧不存在的状态槽 {slot}（{frm}→{to}）")


def _light_view(state: dict, frame: dict) -> dict:
    """单元对外的光影状态：以“光影锚点”为基线，首/尾帧里显式的光影槽优先覆盖。"""
    view = dict(state.get("light") or {})
    for key, value in (frame or {}).items():
        if key in LIGHT_SLOTS:
            view[key] = value
    return view


def check_light_cross(prev, cur, label, err, warn):
    """跨段光影一致性：主光位/色温/光质等锁定槽翻转须有“时空转换/跨段重置”授权。

    即使单元没写完整首/尾帧状态锚点，只要写了一行“光影锚点”就能比对。
    """
    ps, cs = prev["state"], cur["state"]
    out_light = _light_view(ps, ps["last"])
    in_light = _light_view(cs, cs["first"])
    if not out_light and not in_light:
        return  # 两侧都没有机器可读光影，交给弱检查/缺锚点提示
    transition = cs["transition"]
    transition_type = cs.get("transition_type")
    reset = cs["reset"]
    transition_declared = (transition_type in TRANSITION_TYPES - {"none"}) or (
        transition_type is None and transition is True) or bool(re.search(
        r"时空转换[：:]\s*是|memory/flashback|闪回|独立回忆首帧|独立[^\n。；;]{0,8}首帧|不复现",
        cs["raw_in"]))
    for slot in sorted(set(out_light) | set(in_light)):
        a, b = out_light.get(slot), in_light.get(slot)
        if a is None or b is None:
            warn("cross-slot-asymmetric",
                 f"{label}：光影槽 {slot} 只在{'上一段' if a is not None else '下一段'}光影锚点出现，无法核对，建议两侧都登记")
            continue
        if a == b:
            continue
        if transition_declared and (slot in LIGHT_SLOTS or slot in reset):
            continue  # 光影槽都是场景级，显式时空转换即允许变化
        hard = "核心" if slot in LIGHT_LOCK_SLOTS else "记录性"
        reason = "已声明时空转换但未列入“跨段重置”" if transition is True else \
                 ("未声明“时空转换：是”" if transition is False else "未明确声明“时空转换”")
        code = "cross-light-flip" if slot in LIGHT_LOCK_SLOTS else "cross-state-flip"
        (err if slot in LIGHT_LOCK_SLOTS else warn)(
            code, f"{label}：{hard}光影槽 {slot} 由「{a}」变为「{b}」，{reason}，存在跨段光影漂移")


def check_cross_unit(prev, cur, prev_idx, cur_idx, err, warn):
    """跨段交接：prev.尾帧 必须逐项等于 cur.首帧。"""
    ps, cs = prev["state"], cur["state"]
    label = f"单元{prev_idx}尾帧→单元{cur_idx}首帧"

    # 光影跨段一致性：只要任一侧写了光影锚点就能比对（不依赖完整首尾锚点）。
    check_light_cross(prev, cur, label, err, warn)

    # 弱检查（无结构化锚点时的兜底）
    if not ps["has_anchor"] or not cs["has_anchor"]:
        # A flashback mentioned inside a unit does not prove that the unit
        # starts in the memory timeline. Require an explicit independent
        # opening or transition declaration before exempting the real tail.
        transition_exempt = cs.get("transition_type") in INDEPENDENT_TRANSITIONS or bool(re.search(
            r"独立回忆首帧|独立[^\n。；;]{0,8}首帧|不复现(?:上一段|前一段|前段)",
            cs["raw_in"]))
        if transition_exempt:
            warn("cross-tail-exempt-transition",
                 f"{label}：下一段声明时空转换/闪回并以独立首帧开始，豁免尾帧复现（无法逐项机器校验）")
        elif not re.search(r"(复现|尾帧|承接)", cs["raw_in"]):
            err("cross-tail-not-reproduced",
                f"{label}：下一段“连续性输入”未声明复现上一段实际尾帧，且缺少可机器校验的状态锚点")
        else:
            warn("state-anchor-missing",
                 f"{label}：至少一单元缺少结构化状态锚点，跨段一致性无法逐项机器校验")
        return

    transition = cs["transition"]
    transition_type = cs.get("transition_type")
    reset = cs["reset"]
    for slot in sorted(set(ps["last"]) | set(cs["first"])):
        if slot in LIGHT_SLOTS:
            continue  # 光影槽已由 check_light_cross 处理，避免重复报错
        a, b = ps["last"].get(slot), cs["first"].get(slot)
        if a is None or b is None:
            # 一单元登记了、另一单元漏登同一槽：无法证明一致。
            warn("cross-slot-asymmetric",
                 f"{label}：状态槽 {slot} 只在{'上一段尾帧' if a is not None else '下一段首帧'}出现，无法核对，建议两侧都登记")
            continue
        if a == b:
            continue
        is_scene_slot = slot in SCENE_GLOBAL_SLOTS or (("[" not in slot) and slot in SCENE_GLOBAL_SLOTS)
        scene_transition = transition_type in TRANSITION_TYPES - {"none"} or (
            transition_type is None and transition is True)
        if scene_transition and (is_scene_slot or slot in reset):
            continue  # 显式时空转换允许场景槽变化，实体槽须在“跨段重置”逐项授权
        reason = "已声明时空转换但该实体槽未列入“跨段重置”" if transition is True else \
                 ("未声明“时空转换：是”" if transition is False else "未明确声明“时空转换”")
        err("cross-state-flip",
            f"{label}：状态槽 {slot} 由「{a}」翻转为「{b}」，{reason}，属于未授权跨段漂移")


def validate_text(text: str):
    issues = []
    err = lambda code, msg: issues.append(("ERROR", code, msg))
    warn = lambda code, msg: issues.append(("WARNING", code, msg))

    units = extract_units(text)
    parsed = []
    for order, unit in enumerate(units, 1):
        state = parse_unit_state(unit["settings"])
        idx = unit["num"] if unit["num"] is not None else order
        parsed.append({"idx": idx, "state": state, "settings": unit["settings"]})
        if state["transition_type"] is not None and state["transition_type"] not in TRANSITION_TYPES:
            err("transition-type-invalid",
                f"单元{idx} 转换类型 {state['transition_type']!r} 非法；可选 {sorted(TRANSITION_TYPES)}")
        if state["transition_type"] is None and state["transition"] is True:
            warn("transition-type-missing",
                 f"单元{idx} 仍使用未类型化的“时空转换：是”；请补“转换类型”以区分连续空间与独立起始")
        # 首段不得虚构上一段尾帧
        if order == 1 and re.search(r"(复现第|上一段.*尾帧|上段.*尾帧)", state["raw_in"]):
            err("first-unit-fake-tail", "第 1 单元没有上一段，不得在“连续性输入”复现不存在的上一段尾帧")
        if not state["raw_in"]:
            warn("continuity-in-missing", f"单元{idx} 缺少“连续性输入”字段")
        if not state["raw_out"] and order == len(units):
            warn("continuity-out-missing", f"单元{idx} 缺少“连续性输出”字段")
        frame_light = set(state["first"]) | set(state["last"])
        if not state["light"] and not (frame_light & LIGHT_SLOTS):
            warn("light-anchor-missing",
                 f"单元{idx} 缺少受控“光影锚点（机器校验）”，主光位/色温跨段一致性无法机器核对（见 lighting-judgment-rules.md §1）")
        check_within_unit(state, idx, err, warn)

    for prev, cur in zip(parsed, parsed[1:]):
        if prev["idx"] is not None and cur["idx"] is not None and cur["idx"] != prev["idx"] + 1:
            warn("unit-number-gap", f"单元编号由 {prev['idx']} 跳到 {cur['idx']}，确认是否缺单元")
        check_cross_unit(prev, cur, prev["idx"], cur["idx"], err, warn)

    if not units:
        issues.append(("WARNING", "no-unit", "未发现任何含“生成单元”的中文生成设置围栏"))
    return issues, len(units)


def main():
    ap = argparse.ArgumentParser(description="动作三态闭环与跨段状态门禁")
    ap.add_argument("files", nargs="+", help="待校验文件；- 表示标准输入")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report, total_err = {}, 0
    for path in args.files:
        if path == "-":
            text, shown = sys.stdin.read(), "<stdin>"
        else:
            try:
                text = open(path, encoding="utf-8").read()
                shown = path
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
