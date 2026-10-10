"""Shared provenance and ownership contracts for director proposals."""

from __future__ import annotations


PROVENANCE_FIELDS = (
    "script_facts",
    "continuity_constraints",
    "director_recommendations",
    "unresolved",
    "user_decisions",
)

SCRIPT_FACT_DOMAINS = {
    "identity", "hair", "makeup", "costume", "shoes", "accessories", "prop",
    "special_state", "performance", "scene_function", "scene_appearance", "lighting",
    "location", "time", "occupation", "behavior", "emotion", "state_boundary", "media",
}

# The first three are assertions that can inform a proposal.  They are not
# interchangeable: a recommendation still needs user approval before it can
# become a production fact.
PROVENANCE_KINDS = {
    "script_fact",
    "continuity_constraint",
    "director_recommendation",
    "user_confirmed",
    "unresolved",
}

BASIS_FIELDS = {
    "script_fact": "script_facts",
    "continuity_constraint": "continuity_constraints",
    "director_recommendation": "director_recommendations",
    "unresolved": "unresolved",
    "user_confirmed": "user_decisions",
}


def validate_provenance(value: object, label: str = "provenance") -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    missing = [field for field in PROVENANCE_FIELDS if field not in value]
    if missing:
        return [f"{label} missing fields: {missing}"]
    errors = []
    for field in PROVENANCE_FIELDS:
        entries = value.get(field)
        if not isinstance(entries, list) or any(
                not isinstance(entry, str) or not entry.strip() for entry in entries):
            errors.append(f"{label}.{field} must be an array of non-empty strings")
    domains = value.get("script_fact_domains")
    if not isinstance(domains, dict):
        errors.append(f"{label}.script_fact_domains must be an object")
    else:
        script_facts = value.get("script_facts", [])
        missing_domains = [fact for fact in script_facts if fact not in domains]
        unknown_facts = [fact for fact in domains if fact not in script_facts]
        if missing_domains:
            errors.append(f"{label}.script_fact_domains missing facts: {missing_domains}")
        if unknown_facts:
            errors.append(f"{label}.script_fact_domains contains unknown facts: {unknown_facts}")
        for fact, fact_domains in domains.items():
            if (not isinstance(fact_domains, list) or not fact_domains
                    or any(domain not in SCRIPT_FACT_DOMAINS for domain in fact_domains)):
                errors.append(
                    f"{label}.script_fact_domains[{fact!r}] must use known non-empty domains")
    return errors


def validate_component_basis(
    component: dict,
    label: str,
    provenance: dict | None = None,
    required_script_domain: str | None = None,
) -> list[str]:
    basis = component.get("basis")
    if basis not in PROVENANCE_KINDS:
        return [f"{label}: basis must be one of {sorted(PROVENANCE_KINDS)}"]
    errors = []
    basis_ref = component.get("basis_ref")
    if not isinstance(basis_ref, str) or not basis_ref.strip():
        errors.append(f"{label}: basis_ref must identify the exact design-basis entry")
    elif isinstance(provenance, dict):
        field = BASIS_FIELDS[basis]
        if basis_ref not in provenance.get(field, []):
            errors.append(f"{label}: basis_ref is not present in provenance.{field}")
        elif basis == "script_fact" and required_script_domain:
            domains = provenance.get("script_fact_domains", {}).get(basis_ref, [])
            if required_script_domain not in domains:
                errors.append(
                    f"{label}: script fact domain cannot directly define {required_script_domain}")
    if basis == "director_recommendation":
        if component.get("approval_required") is not True:
            errors.append(f"{label}: director recommendations require approval_required=true")
        if not component.get("rationale"):
            errors.append(f"{label}: director recommendations require rationale")
    if basis == "user_confirmed" and not component.get("decision_ref"):
        errors.append(f"{label}: user-confirmed facts require decision_ref")
    if basis == "unresolved":
        requirement = component.get("requirement", component.get("requirements", ""))
        if isinstance(requirement, list):
            requirement = " ".join(str(item) for item in requirement)
        requirement = str(requirement)
        markers = ("待设计", "待确认", "未指定", "未决", "不预设", "unresolved", "to be designed")
        if not any(marker in requirement for marker in markers):
            errors.append(f"{label}: unresolved requirements must explicitly remain open")
    return errors


def validate_ownership(component: dict, label: str) -> list[str]:
    kind = component.get("component_type")
    ownership = component.get("ownership")
    if ownership is None:
        return [f"{label}: ownership is required"]
    allowed = {"character_asset", "scene_asset", "shot_asset", "performance_state"}
    if ownership not in allowed:
        return [f"{label}: unsupported ownership"]
    if kind == "prop" and ownership not in {"scene_asset", "shot_asset"}:
        return [f"{label}: prop must be owned by scene_asset or shot_asset, not character fusion"]
    if kind not in {"prop", "special_state"} and ownership != "character_asset":
        return [f"{label}: look components must use character_asset ownership"]
    if kind != "prop" and ownership == "scene_asset":
        return [f"{label}: only prop may use scene_asset ownership"]
    return []
