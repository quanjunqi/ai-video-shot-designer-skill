"""Validate text-first shot-card production contracts."""

from __future__ import annotations

from shotdesigner import catalogs
from shotdesigner.findings import Finding
from shotdesigner.provenance import validate_component_basis, validate_provenance


REQUIRED_FIELDS = (
    "design_mode", "purpose", "visual_task", "staging", "camera", "focus",
    "composition", "movement", "timing", "action_chain", "action_states",
    "prop_states", "camera_plan", "cut_necessity", "next_shot_momentum",
    "continuity", "lighting", "effects", "sound", "constraints",
)
CAMERA_FIELDS = ("position", "axis_side", "viewpoint", "angle", "shot_size", "lens")
LENS_FIELDS = ("mm", "perspective", "narrative_use")
MOVEMENT_FIELDS = ("type", "direction", "amplitude", "speed", "easing", "stability", "stop_position")
TIMING_FIELDS = ("start", "duration", "internal_beats", "cut_motivation", "emotional_velocity")
ACTION_STATES = ("start", "process", "end")
CAMERA_PLAN_FIELDS = ("start", "follow", "change_trigger", "end_momentum")
STAGING_FIELDS = ("actors", "props", "occlusion")
FOCUS_FIELDS = ("subject", "depth_of_field", "rack_focus")
COMPOSITION_FIELDS = ("foreground", "middle_ground", "background", "leading_lines", "negative_space", "occlusion")
CONTINUITY_FIELDS = ("in", "out")
LIGHTING_FIELDS = ("anchor", "subject_side", "shadow", "exposure")
SOUND_FIELDS = ("dialogue", "environment", "music")
CONSTRAINT_FIELDS = ("forbidden_drift", "do_not_reveal")
PERFORMANCE_BEAT_FIELDS = ("trigger", "visible_response", "timing", "basis", "basis_ref", "rationale")
STRATEGY_SELECTION_FIELDS = (
    "strategy_id", "role", "goal", "prerequisites_met", "h3_translation",
    "contraindications_checked",
)
EFFECT_CONTRACT_FIELDS = (
    "effect_id", "beat_ids", "source", "effect_type", "trigger", "timing",
    "intensity", "affected_area", "environment_interaction", "end_state",
    "visibility_limits",
)
DYNAMIC_FIELDS = (
    "motion_objective", "spatial_route", "key_contacts", "primary_motion_change",
    "physical_feedbacks", "residual_motion",
)


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _add(findings, severity, code, message):
    findings.append(Finding(code=code, severity=severity, message=message))


def validate(shot, strategy_required=False):
    findings = []
    shot_id = shot.get("shot_id", "<unknown>")
    card = shot.get("shot_card")
    if not isinstance(card, dict):
        _add(findings, "ERROR", "shot-card-missing",
             f"{shot_id}: 缺少结构化 shot_card；无分镜位图工作流必须由镜头卡承载生产决定")
        return findings

    missing = [field for field in REQUIRED_FIELDS if field not in card or card.get(field) in (None, "")]
    if missing:
        _add(findings, "ERROR", "shot-card-field-missing", f"{shot_id}: shot_card 缺少 {missing}")

    design_mode = card.get("design_mode")
    if design_mode not in {"drama", "dynamic", "mixed"}:
        _add(findings, "ERROR", "shot-card-design-mode-invalid",
             f"{shot_id}: design_mode 必须是 drama、dynamic 或 mixed")

    strategies = card.get("strategy_selection")
    if strategy_required and not isinstance(strategies, list):
        _add(findings, "ERROR", "shot-card-strategy-selection-missing",
             f"{shot_id}: v2.1 shot_card 必须包含 strategy_selection 数组，无需策略时写 []")
    if strategies is not None:
        if not isinstance(strategies, list):
            _add(findings, "ERROR", "shot-card-strategy-selection-type",
                 f"{shot_id}: strategy_selection 必须是数组")
        else:
            if len(strategies) > 2:
                _add(findings, "ERROR", "shot-card-strategy-selection-overload",
                     f"{shot_id}: 每镜最多一个 primary 和一个 secondary 策略")
            roles, categories, ids = [], [], []
            known_strategies = catalogs.shot_strategies()
            for index, strategy in enumerate(strategies, 1):
                if not isinstance(strategy, dict):
                    _add(findings, "ERROR", "shot-card-strategy-type",
                         f"{shot_id}: strategy_selection[{index}] 必须是对象")
                    continue
                missing_strategy = [field for field in STRATEGY_SELECTION_FIELDS
                                    if field not in strategy or strategy.get(field) in (None, "")]
                if missing_strategy:
                    _add(findings, "ERROR", "shot-card-strategy-incomplete",
                         f"{shot_id}: strategy_selection[{index}] 缺少 {missing_strategy}")
                strategy_id = strategy.get("strategy_id")
                if strategy_id:
                    ids.append(strategy_id)
                catalog_entry = known_strategies.get(strategy_id)
                if not catalog_entry:
                    _add(findings, "ERROR", "shot-card-strategy-unknown",
                         f"{shot_id}: 未知 strategy_id={strategy_id}")
                else:
                    categories.append(catalog_entry.get("category"))
                role = strategy.get("role")
                roles.append(role)
                if role not in {"primary", "secondary"}:
                    _add(findings, "ERROR", "shot-card-strategy-role-invalid",
                         f"{shot_id}: strategy role 必须是 primary 或 secondary")
                for field in ("prerequisites_met", "contraindications_checked"):
                    value = strategy.get(field)
                    if not isinstance(value, list) or not value or not all(
                            isinstance(item, str) and item.strip() for item in value):
                        _add(findings, "ERROR", "shot-card-strategy-evidence-invalid",
                             f"{shot_id}: strategy_selection[{index}].{field} 必须是非空字符串数组")
            if strategies and roles.count("primary") != 1:
                _add(findings, "ERROR", "shot-card-strategy-primary-count",
                     f"{shot_id}: 非空 strategy_selection 必须恰好包含一个 primary")
            if roles.count("secondary") > 1:
                _add(findings, "ERROR", "shot-card-strategy-secondary-count",
                     f"{shot_id}: 最多只能包含一个 secondary")
            if len(ids) != len(set(ids)):
                _add(findings, "ERROR", "shot-card-strategy-duplicate",
                     f"{shot_id}: 同一策略不得重复选择")
            if len(categories) != len(set(categories)):
                _add(findings, "ERROR", "shot-card-strategy-category-overlap",
                     f"{shot_id}: primary 与 secondary 应解决不同类别的问题")

    action_chain = card.get("action_chain")
    if not isinstance(action_chain, list) or not action_chain or not all(
            isinstance(item, str) and item.strip() for item in action_chain):
        _add(findings, "ERROR", "shot-card-action-chain-invalid",
             f"{shot_id}: action_chain 必须是非空的可观察动作数组")

    if design_mode in {"drama", "mixed"} and _as_list(shot.get("characters")):
        performance_provenance = card.get("performance_provenance")
        for error in validate_provenance(performance_provenance, "performance_provenance"):
            _add(findings, "ERROR", "shot-card-performance-provenance-invalid",
                 f"{shot_id}: {error}")
        performance_beats = card.get("performance_beats")
        if not isinstance(performance_beats, list) or not 1 <= len(performance_beats) <= 4:
            _add(findings, "ERROR", "shot-card-performance-beats-invalid",
                 f"{shot_id}: {design_mode} 人物镜头必须有 1 至 4 个 performance_beats")
        else:
            for index, beat in enumerate(performance_beats, 1):
                if not isinstance(beat, dict):
                    _add(findings, "ERROR", "shot-card-performance-beat-type",
                         f"{shot_id}: performance_beats[{index}] 必须是对象")
                    continue
                missing_performance = [field for field in PERFORMANCE_BEAT_FIELDS
                                       if field not in beat or beat.get(field) in (None, "")]
                if missing_performance:
                    _add(findings, "ERROR", "shot-card-performance-beat-incomplete",
                         f"{shot_id}: performance_beats[{index}] 缺少 {missing_performance}")
                    continue
                for error in validate_component_basis(
                        beat, f"performance_beats[{index}]", performance_provenance,
                        required_script_domain="performance"):
                    _add(findings, "ERROR", "shot-card-performance-basis-invalid",
                         f"{shot_id}: {error}")
                if beat.get("basis") == "unresolved":
                    _add(findings, "ERROR", "shot-card-performance-unresolved",
                         f"{shot_id}: performance_beats[{index}] 未决表演不能进入镜头卡")
                if (beat.get("basis") == "script_fact"
                        and beat.get("visible_response") != beat.get("basis_ref")):
                    _add(findings, "ERROR", "shot-card-performance-script-expansion",
                         f"{shot_id}: 剧本事实表演必须逐字使用可见动作；额外表现应登记为导演建议")

    effects = card.get("effects", [])
    if not isinstance(effects, list):
        _add(findings, "ERROR", "shot-card-effects-type", f"{shot_id}: effects 必须是数组，无额外效果时写 []")
    else:
        effect_ids = []
        for index, effect in enumerate(effects, 1):
            if not isinstance(effect, dict):
                _add(findings, "ERROR", "shot-card-effect-type", f"{shot_id}: effects[{index}] 必须是对象")
                continue
            missing_effect = [field for field in EFFECT_CONTRACT_FIELDS
                              if field not in effect or effect.get(field) in (None, "")]
            if missing_effect:
                _add(findings, "ERROR", "shot-card-effect-incomplete",
                     f"{shot_id}: effects[{index}] 缺少 {missing_effect}")
            if effect.get("effect_id"):
                effect_ids.append(effect["effect_id"])
            if not isinstance(effect.get("beat_ids"), list) or not effect.get("beat_ids"):
                _add(findings, "ERROR", "shot-card-effect-beats-invalid",
                     f"{shot_id}: effects[{index}].beat_ids 必须是非空数组")
            if not isinstance(effect.get("visibility_limits"), list) or not effect.get("visibility_limits"):
                _add(findings, "ERROR", "shot-card-effect-visibility-invalid",
                     f"{shot_id}: effects[{index}].visibility_limits 必须是非空数组")
        if len(effect_ids) != len(set(effect_ids)):
            _add(findings, "ERROR", "shot-card-effect-id-duplicate", f"{shot_id}: effects 存在重复 effect_id")

    visual_sections = (
        ("staging", STAGING_FIELDS, False, "记录人物/道具相对锚点与画面位置"),
        ("focus", FOCUS_FIELDS, True, "记录焦点主体、景深和拉焦"),
        ("composition", COMPOSITION_FIELDS, False, "记录前中后景、锚点和遮挡"),
    )
    continuity_sections = (
        ("continuity", CONTINUITY_FIELDS, True, "包含本镜首尾状态"),
        ("lighting", LIGHTING_FIELDS, True, "记录受光面、阴影和曝光重点"),
        ("sound", SOUND_FIELDS, False, "记录对白、环境声和配乐关系"),
        ("constraints", CONSTRAINT_FIELDS, False, "记录禁止漂移和不可揭示信息"),
    )

    def validate_object_sections(sections):
        for name, fields, require_value, description in sections:
            value = card.get(name)
            if not isinstance(value, dict):
                _add(findings, "ERROR", f"shot-card-{name}-type",
                     f"{shot_id}: shot_card.{name} 必须是对象，{description}")
                continue
            missing_fields = [field for field in fields
                              if field not in value or (require_value and value.get(field) in (None, ""))]
            if missing_fields:
                _add(findings, "ERROR", f"shot-card-{name}-field-missing",
                     f"{shot_id}: shot_card.{name} 缺少 {missing_fields}")

    validate_object_sections(visual_sections)
    if not isinstance(card.get("prop_states"), dict):
        _add(findings, "ERROR", "shot-card-prop-states-type",
             f"{shot_id}: shot_card.prop_states 必须是对象，即使本镜无道具也要写 {{}}")
    validate_object_sections(continuity_sections)

    nested_sections = (
        ("camera", CAMERA_FIELDS), ("movement", MOVEMENT_FIELDS), ("timing", TIMING_FIELDS),
        ("action_states", ACTION_STATES), ("camera_plan", CAMERA_PLAN_FIELDS),
    )
    for name, fields in nested_sections:
        value = card.get(name)
        if not isinstance(value, dict):
            suffix = "，包含 start/process/end" if name == "action_states" else ""
            _add(findings, "ERROR", f"shot-card-{name.replace('_', '-')}-type",
                 f"{shot_id}: shot_card.{name} 必须是对象{suffix}")
            continue
        missing_fields = [field for field in fields if field not in value or value.get(field) in (None, "")]
        if missing_fields:
            code_suffix = "action-state" if name == "action_states" else name.replace("_", "-") + "-field"
            _add(findings, "ERROR", f"shot-card-{code_suffix}-missing",
                 f"{shot_id}: shot_card.{name} 缺少 {missing_fields}")
        if name == "camera":
            lens = value.get("lens")
            if not isinstance(lens, dict):
                _add(findings, "ERROR", "shot-card-lens-type",
                     f"{shot_id}: shot_card.camera.lens 必须是对象，包含 mm、透视和叙事用途")
            else:
                missing_lens = [field for field in LENS_FIELDS if field not in lens or lens.get(field) in (None, "")]
                if missing_lens:
                    _add(findings, "ERROR", "shot-card-lens-field-missing",
                         f"{shot_id}: shot_card.camera.lens 缺少 {missing_lens}")
        if name == "timing":
            internal_beats = value.get("internal_beats")
            if not isinstance(internal_beats, list) or not internal_beats:
                _add(findings, "ERROR", "shot-card-internal-beats-invalid",
                     f"{shot_id}: shot_card.timing.internal_beats 必须是非空数组")

    if design_mode in {"dynamic", "mixed"}:
        missing_dynamic = [field for field in DYNAMIC_FIELDS if field not in card or card.get(field) in (None, "")]
        if missing_dynamic:
            _add(findings, "ERROR", "shot-card-dynamic-field-missing",
                 f"{shot_id}: {design_mode} 镜头缺少动态设计字段 {missing_dynamic}")
        for field in ("spatial_route", "key_contacts", "physical_feedbacks"):
            value = card.get(field)
            if not isinstance(value, list) or not value:
                _add(findings, "ERROR", "shot-card-dynamic-list-invalid", f"{shot_id}: {field} 必须是非空数组")
        feedbacks = card.get("physical_feedbacks")
        if isinstance(feedbacks, list) and not 2 <= len(feedbacks) <= 3:
            _add(findings, "ERROR", "shot-card-physical-feedback-count",
                 f"{shot_id}: physical_feedbacks 必须包含 2 至 3 个可观察反馈")
    return findings


def validate_all(shots, strict, strategy_required=False):
    findings = []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        if strict:
            findings.extend(validate(shot, strategy_required=strategy_required))
        elif "shot_card" not in shot:
            _add(findings, "WARNING", "shot-card-missing-legacy",
                 f"{shot.get('shot_id', '<unknown>')}: 旧分镜板清单未携带结构化 shot_card；"
                 "新工作流不能依赖总版图替代镜头卡")
    return findings
