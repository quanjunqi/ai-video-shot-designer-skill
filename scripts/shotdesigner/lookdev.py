"""Scene-mapped character look states, component approvals, and fusion."""

from __future__ import annotations

from .provenance import (
    BASIS_FIELDS,
    validate_component_basis,
    validate_ownership,
    validate_provenance,
)


COMPONENT_TYPES = {"hair", "makeup", "costume", "shoes", "accessories", "prop", "special_state"}

# These are production assets, while COMPONENT_TYPES above are the semantic
# look-state components declared by the script analysis.
LOOK_ASSET_TYPES = {
    "costume_structure", "fabric_detail", "costume_worn_view",
    "costume_reference_analysis", "hair_batch", "makeup_batch",
    "accessory_batch", "look_component",
}

COMPONENT_ASSET_TYPES = {
    "hair": {"hair_batch", "look_component"},
    "makeup": {"makeup_batch"},
    "costume": {"costume_structure", "fabric_detail", "costume_worn_view",
                 "costume_reference_analysis", "look_component"},
    "shoes": {"look_component"},
    "accessories": {"accessory_batch", "look_component"},
    "prop": set(),
    "special_state": {"look_component"},
}

COMPONENT_SCRIPT_DOMAINS = {
    "hair": "hair", "makeup": "makeup", "costume": "costume", "shoes": "shoes",
    "accessories": "accessories", "prop": "prop",
}

COMPONENT_PRODUCTION_DISPOSITIONS = {"asset_required", "confirmed_absent"}

COSTUME_CONFIRMED_DESIGN_FIELDS = (
    "fit", "color", "material_category", "layering", "graphics_and_trim",
)
COSTUME_UPPER_STRUCTURE_FIELDS = (
    "category", "neckline", "shoulder", "sleeve", "body_and_hem",
    "seams_and_pockets",
)
COSTUME_LOWER_STRUCTURE_FIELDS = (
    "category", "waistband", "rise_and_leg", "pockets", "hem",
    "front_back_structure",
)


def look_state_scope(character_id: str, look_state_id: str) -> str:
    return f"{character_id}:{look_state_id}"


def validate_look_state_plan(value: object, known_script_refs: set[str] | None = None,
                             known_scene_ids: set[str] | None = None,
                             *, allow_legacy: bool = False) -> list[str]:
    if not isinstance(value, dict):
        return ["look state plan must be an object"]
    required = ("character_id", "look_states", "transitions", "unknowns")
    missing = [field for field in required if field not in value]
    if missing:
        return [f"look state plan missing fields: {missing}"]
    if not isinstance(value.get("look_states"), list) or not value["look_states"]:
        return ["look_states must be a non-empty array"]
    errors, ids = [], []
    for state in value["look_states"]:
        fields = ("look_state_id", "label", "scene_ids", "script_refs",
                  "continuity_reason", "components")
        if not isinstance(state, dict) or any(field not in state for field in fields):
            errors.append("each look state must contain id, label, scene/script mapping, reason, and components")
            continue
        ids.append(state["look_state_id"])
        new_provenance = "provenance" in state
        if not new_provenance and not allow_legacy:
            errors.append(f"{state['look_state_id']}: provenance is required for new look-state plans")
        if new_provenance:
            provenance = state["provenance"]
            provenance_errors = validate_provenance(
                provenance, f"{state['look_state_id']}.provenance")
            errors.extend(provenance_errors)
            label_basis = state.get("label_basis")
            if not isinstance(label_basis, dict):
                errors.append(f"{state['look_state_id']}: label_basis is required")
            else:
                label_kind = label_basis.get("basis")
                label_source = label_basis.get("source")
                if label_kind not in {"script_fact", "continuity_constraint", "user_confirmed"}:
                    errors.append(
                        f"{state['look_state_id']}: label_basis must use script_fact, "
                        "continuity_constraint, or user_confirmed")
                elif (not isinstance(provenance, dict)
                      or label_source not in provenance.get(BASIS_FIELDS[label_kind], [])):
                    errors.append(f"{state['look_state_id']}: label_basis source is not in provenance")
                elif (label_kind == "script_fact"
                      and "state_boundary" not in provenance.get(
                          "script_fact_domains", {}).get(label_source, [])):
                    errors.append(
                        f"{state['look_state_id']}: script-fact label must use state_boundary domain")
                if label_source != state.get("label"):
                    errors.append(f"{state['look_state_id']}: label must exactly match label_basis source")
                if label_kind == "user_confirmed" and not label_basis.get("decision_ref"):
                    errors.append(f"{state['look_state_id']}: user-confirmed label requires decision_ref")
        if not isinstance(state["scene_ids"], list) or not state["scene_ids"]:
            errors.append(f"{state['look_state_id']}: scene_ids must be non-empty")
        elif known_scene_ids is not None and set(state["scene_ids"]) - known_scene_ids:
            errors.append(f"{state['look_state_id']}: unknown scene_ids")
        if not isinstance(state["script_refs"], list) or not state["script_refs"]:
            errors.append(f"{state['look_state_id']}: script_refs must be non-empty")
        elif known_script_refs is not None and set(state["script_refs"]) - known_script_refs:
            errors.append(f"{state['look_state_id']}: unknown script_refs")
        if not isinstance(state["components"], list) or not state["components"]:
            errors.append(f"{state['look_state_id']}: components must be non-empty")
            continue
        component_types = []
        for component in state["components"]:
            if not isinstance(component, dict) or component.get("component_type") not in COMPONENT_TYPES:
                errors.append(f"{state['look_state_id']}: invalid component declaration")
                continue
            component_types.append(component["component_type"])
            if not component.get("requirement") or not component.get("rationale"):
                errors.append(f"{state['look_state_id']}: component needs requirement, basis, and rationale")
            if new_provenance:
                component_type = component["component_type"]
                required_domain = COMPONENT_SCRIPT_DOMAINS.get(component_type)
                if component_type == "special_state":
                    required_domain = (
                        "performance" if component.get("ownership") == "performance_state"
                        else "special_state")
                errors.extend(validate_component_basis(
                    component, f"{state['look_state_id']}:{component_type}",
                    provenance, required_script_domain=required_domain))
                errors.extend(validate_ownership(
                    component, f"{state['look_state_id']}:{component['component_type']}"))
            elif allow_legacy and component.get("basis") not in {
                    "script", "director_inference", "user"}:
                errors.append(f"{state['look_state_id']}: legacy component basis is invalid")
        if len(component_types) != len(set(component_types)):
            errors.append(f"{state['look_state_id']}: duplicate component types")
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        errors.append("look_state_id values must be unique and non-empty")
    if not isinstance(value.get("transitions"), list) or not isinstance(value.get("unknowns"), list):
        errors.append("transitions and unknowns must be arrays")
    return errors


def validate_component(component: object, *, for_production: bool = False,
                       allow_legacy: bool = False) -> list[str]:
    if not isinstance(component, dict):
        return ["look component must be an object"]
    required = ("component_id", "character_id", "component_type", "script_refs",
                "look_state_id", "requirements", "forbidden_changes")
    missing = [field for field in required if field not in component]
    if missing:
        return [f"look component missing fields: {missing}"]
    errors = []
    if component.get("component_type") not in COMPONENT_TYPES:
        errors.append("unsupported look component type")
    asset_type = component.get("asset_type")
    if asset_type is not None:
        if asset_type not in LOOK_ASSET_TYPES:
            errors.append("unsupported look asset type")
        elif asset_type not in COMPONENT_ASSET_TYPES.get(component.get("component_type"), set()):
            errors.append("look asset type does not match component type")
    if not isinstance(component.get("script_refs"), list):
        errors.append("script_refs must be an array")
    if not isinstance(component.get("requirements"), list) or not component["requirements"]:
        errors.append("requirements must be a non-empty array")
    if not isinstance(component.get("forbidden_changes"), list):
        errors.append("forbidden_changes must be an array")
    if "basis" in component or not allow_legacy:
        errors.extend(validate_component_basis(component, "look component"))
        errors.extend(validate_ownership(component, "look component"))
    if component.get("component_type") == "prop":
        errors.append("prop must use the scene/shot asset workflow, not look-component production")
    disposition = component.get("production_disposition", "asset_required")
    if disposition not in COMPONENT_PRODUCTION_DISPOSITIONS:
        errors.append("unsupported component production_disposition")
    elif disposition == "confirmed_absent":
        if component.get("basis") != "user_confirmed" or not component.get("decision_ref"):
            errors.append("confirmed_absent component requires a user-confirmed decision")
        if asset_type is not None:
            errors.append("confirmed_absent component cannot declare an asset_type")
        if component.get("downstream_assets") not in (None, []):
            errors.append("confirmed_absent component cannot declare downstream assets")
        if for_production:
            errors.append("confirmed_absent component does not produce an image asset")
    if for_production and component.get("basis") == "unresolved":
        errors.append("unresolved look components cannot enter a production Prompt")
    if for_production and component.get("component_type") == "costume":
        reference_status = component.get("reference_image_status")
        if reference_status not in {"provided", "not_provided"}:
            errors.append(
                "costume production requires a user-confirmed reference_image_status")
        if not component.get("reference_decision_ref"):
            errors.append(
                "costume production requires reference_decision_ref")
        if reference_status == "provided" and not component.get("reference_image"):
            errors.append(
                "costume production with a provided reference requires reference_image")
    return errors


def validate_costume_structure_design(component: object) -> list[str]:
    if not isinstance(component, dict):
        return ["costume structure spec must be an object"]
    design = component.get("structure_design")
    if not isinstance(design, dict):
        return [
            "costume-structure requires structure_design confirmed before Prompt export"
        ]
    errors = []
    if design.get("status") != "user_confirmed":
        errors.append("structure_design.status must be user_confirmed")
    if not isinstance(design.get("decision_ref"), str) or not design["decision_ref"].strip():
        errors.append("structure_design.decision_ref is required")
    if not isinstance(design.get("garment_combination"), str) or not design[
            "garment_combination"].strip():
        errors.append("structure_design.garment_combination is required")
    groups = (
        ("confirmed_design", COSTUME_CONFIRMED_DESIGN_FIELDS),
        ("upper_structure", COSTUME_UPPER_STRUCTURE_FIELDS),
        ("lower_structure", COSTUME_LOWER_STRUCTURE_FIELDS),
    )
    for group_name, fields in groups:
        group = design.get(group_name)
        if not isinstance(group, dict):
            errors.append(f"structure_design.{group_name} must be an object")
            continue
        missing = [field for field in fields
                   if not isinstance(group.get(field), str) or not group[field].strip()]
        if missing:
            errors.append(f"structure_design.{group_name} missing fields: {missing}")
    return errors


def costume_structure_prompt(component: dict) -> str:
    errors = validate_costume_structure_design(component)
    if errors:
        raise ValueError("；".join(errors))
    design = component["structure_design"]
    confirmed = design["confirmed_design"]
    upper = design["upper_structure"]
    lower = design["lower_structure"]
    return f"""任务：
生成一张无人物服装结构三视图，用于锁定服装资产的廓形、裁片关系和正侧背结构。
这不是角色定妆图，也不是穿搭场景图。

服装组合：
{design['garment_combination']}。

已确认设计：
- 版型：{confirmed['fit']}
- 配色：{confirmed['color']}
- 面料类别：{confirmed['material_category']}
- 穿着层次：{confirmed['layering']}
- 图案与装饰：{confirmed['graphics_and_trim']}

本次结构方案：
上装：
- 品类：{upper['category']}
- 领口：{upper['neckline']}
- 肩线：{upper['shoulder']}
- 袖型与袖长：{upper['sleeve']}
- 衣身与下摆：{upper['body_and_hem']}
- 接缝与口袋：{upper['seams_and_pockets']}

下装：
- 品类：{lower['category']}
- 腰头：{lower['waistband']}
- 裤裆与裤腿：{lower['rise_and_leg']}
- 口袋：{lower['pockets']}
- 裤脚：{lower['hem']}
- 正面与背面结构：{lower['front_back_structure']}

展示形式：
使用无人物的隐形人台展示完整上装和下装。
一张图内包含三个等比例视图，从左到右依次为正面、标准90度侧面、背面。
三个视图必须保持完全相同的服装款式、比例、颜色和结构。
服装完整可见，不裁切，不重叠。

视觉表现：
服装技术展示图，工业设计感，结构准确，轮廓和缝线清晰。
纯白背景，均匀平光，无环境光、戏剧光、投影或渐变。
仅表现足以辨认结构的基础面料特征，不表现微距纹理和复杂穿着褶皱。

禁止：
不出现真人、模特、人体、头部、脸、手、脚或皮肤。
不出现房间、家具、电脑、手机及任何剧情场景。
不添加未经确认的外套、叠穿、图案、Logo、配饰或装饰。
不改变三个视图之间的结构、长度、颜色或比例。
画面内不生成标题、尺寸、箭头、汉字、英文字母或其他文字。"""


def validate_four_view_spec(value: object) -> list[str]:
    """Validate the contract for the default character video reference sheet."""
    if not isinstance(value, dict):
        return ["character four-view spec must be an object"]
    required = ("character_id", "look_state_id", "view_order", "requirements", "forbidden")
    missing = [field for field in required if field not in value]
    if missing:
        return [f"character four-view spec missing fields: {missing}"]
    if value.get("view_order") != ["front_full_body", "profile_full_body", "back_full_body", "front_face_closeup"]:
        return ["character four-view view_order must be front, profile, back, face close-up"]
    if not isinstance(value.get("requirements"), list) or not value["requirements"]:
        return ["character four-view requirements must be a non-empty array"]
    if not isinstance(value.get("forbidden"), list):
        return ["character four-view forbidden must be an array"]
    return []


def component_is_declared(component: dict, plan: dict) -> bool:
    for state in plan.get("look_states", []):
        if state.get("look_state_id") != component.get("look_state_id"):
            continue
        for item in state.get("components", []):
            if not isinstance(item, dict):
                continue
            if (item.get("component_type") != component.get("component_type")
                    or item.get("ownership") != component.get("ownership")):
                continue
            if (item.get("basis") == component.get("basis")
                    and item.get("basis_ref") == component.get("basis_ref")):
                return True
            if (item.get("basis") == "unresolved"
                    and component.get("basis") == "user_confirmed"
                    and component.get("resolves_basis_ref") == item.get("basis_ref")
                    and component.get("decision_ref")):
                return True
        return False
    return False


def fusable_component_types(state: dict,
                            component_requirements: dict[str, dict] | None = None
                            ) -> list[str]:
    result = []
    for item in state.get("components", []):
        if (not isinstance(item, dict)
                or item.get("ownership") != "character_asset"
                or item.get("component_type") == "prop"):
            continue
        kind = item.get("component_type")
        requirement = (component_requirements or {}).get(kind, {})
        if requirement.get("production_disposition") == "confirmed_absent":
            continue
        result.append(kind)
    return result


def fusion_prompt(character_id: str, look_state_id: str, component_types: list[str],
                  absent_component_types: list[str] | None = None) -> str:
    components = "、".join(component_types)
    absent = ""
    if absent_component_types:
        absent = ("已确认以下组件不存在，成片中不得自行添加："
                  f"{'、'.join(absent_component_types)}。")
    return (f"以第1张参考图的演员身份为唯一身份基准，为角色 {character_id} 的"
            f"定妆状态 {look_state_id} 融合已确认的{components}。"
            "其余参考图只提供各自获批组件，不继承其中人物身份、姿势或背景。"
            "完整保留演员脸部结构、肤色、年龄视觉、身体比例和永久识别特征；"
            f"只组合明确提供的组件，不新增服装、配饰、文字、道具或伤妆。{absent}"
            "中性站立，纯灰背景，三分之四全身，双手和鞋完整可见，single frame, no collage, no text.")


def validate_fusion_sources(ledger: dict, character_id: str, look_state_id: str,
                            component_types: list[str],
                            component_assets: dict[str, list[str] | str] | None = None
                            ) -> tuple[list[str], list[dict]]:
    errors, sources = [], []
    actor = ledger.get("artifacts", {}).get(f"actor_baseline:{character_id}")
    if not actor or actor.get("status") != "USER_APPROVED":
        errors.append("approved actor_baseline is required")
    else:
        sources.append(actor)
    # The actor baseline is sufficient to preserve identity. The old identity
    # set remains an optional enhancement for legacy projects.
    identity_set = ledger.get("artifacts", {}).get(f"actor_identity_set:{character_id}")
    if identity_set and identity_set.get("status") == "USER_APPROVED":
        sources.append(identity_set)
    for kind in component_types:
        if kind == "prop":
            errors.append("prop is a scene or shot asset and cannot be fused into character look")
            continue
        requirement_key = f"look_component_requirement:{character_id}:{look_state_id}:{kind}"
        requirement = ledger.get("artifacts", {}).get(requirement_key)
        if not requirement or requirement.get("status") != "USER_APPROVED":
            errors.append(f"approved look component requirement is required: {kind}")
        declared = component_assets.get(kind) if component_assets else None
        keys = declared if isinstance(declared, list) else [declared] if isinstance(declared, str) else []
        if not keys:
            keys = [f"look_component:{character_id}:{look_state_id}:{kind}"]
        for key in keys:
            if ":" not in key:
                key = f"{key}:{character_id}:{look_state_id}:{kind}"
            item = ledger.get("artifacts", {}).get(key)
            if not item or item.get("status") != "USER_APPROVED":
                if key == f"look_component:{character_id}:{look_state_id}:{kind}":
                    errors.append(f"approved look component is required: {kind}")
                else:
                    errors.append(f"approved look component is required: {kind} ({key})")
            else:
                sources.append(item)
    return errors, sources
