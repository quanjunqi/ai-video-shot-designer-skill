"""Validate on-screen text assets, lineage, and upload policy."""

from __future__ import annotations

from shotdesigner.findings import Finding


TREATMENTS = {
    "object_intrinsic": "asset_locked",
    "dynamic_state": "same_source_states",
    "editorial": "post_production",
    "non_narrative_unreadable": "abstract_layout",
}


def _add(findings, code, message):
    findings.append(Finding(code=code, severity="ERROR", message=message))


def _as_list(value):
    return value if isinstance(value, list) else []


def text_lock_has_user_proof(text_lock):
    return isinstance(text_lock, dict) \
        and text_lock.get("user_review_status") == "passed" \
        and bool(text_lock.get("user_confirmation_statement")) \
        and bool(text_lock.get("confirmed_file_sha256"))


def validate_text_policy(script, asset_by_id):
    findings = []
    for index, item in enumerate(_as_list(script.get("on_screen_text")), 1):
        if not isinstance(item, dict):
            _add(findings, "screen-text-type", f"on_screen_text[{index}] 必须是对象")
            continue
        label = item.get("text") or item.get("text_id") or f"#{index}"
        category = item.get("category")
        treatment = item.get("treatment")
        if category not in TREATMENTS:
            _add(findings, "screen-text-category-invalid",
                   f"画面文字 {label}: category 必须是 {sorted(TREATMENTS)}")
            continue
        expected = TREATMENTS[category]
        if treatment != expected:
            _add(findings, "screen-text-treatment-drift",
                   f"画面文字 {label}: {category} 必须使用 treatment={expected}")
        if category == "object_intrinsic":
            asset = asset_by_id.get(item.get("asset_id"))
            if asset is None:
                _add(findings, "screen-text-asset-missing",
                       f"画面文字 {label}: object_intrinsic 必须绑定已登记 asset_id")
            else:
                text_lock = asset.get("text_lock")
                if not isinstance(text_lock, dict) or not text_lock.get("expected_text") \
                        or not text_lock_has_user_proof(text_lock):
                    _add(findings, "screen-text-asset-proof-incomplete",
                           f"画面文字 {label}: 必须登记 expected_text 和绑定文件哈希的用户逐字确认")
                elif item.get("text") != text_lock.get("expected_text"):
                    _add(findings, "screen-text-asset-content-drift",
                           f"画面文字 {label}: Script IR 文本与资产 expected_text 不一致")
        if category == "dynamic_state":
            state_ids = item.get("state_asset_ids")
            if not isinstance(state_ids, list) or len(state_ids) < 2 or any(
                    asset_id not in asset_by_id for asset_id in state_ids):
                _add(findings, "screen-text-state-assets-invalid",
                       f"画面文字 {label}: dynamic_state 必须绑定至少两个已登记同源状态资产")
            else:
                roots = {asset_by_id[asset_id].get("lineage_root_asset_id") for asset_id in state_ids}
                if len(roots) != 1:
                    _add(findings, "screen-text-state-lineage-drift",
                           f"画面文字 {label}: 前后态必须共享 lineage_root_asset_id")
                root_id = next(iter(roots)) if len(roots) == 1 else None
                root = asset_by_id.get(root_id)
                if not root_id or root is None or root.get("kind") != "canonical":
                    _add(findings, "screen-text-state-lineage-root-invalid",
                           f"画面文字 {label}: lineage root 必须指向已登记 canonical 资产")
                for asset_id in state_ids:
                    if asset_id == root_id:
                        continue
                    if not asset_derives_from(asset_id, root_id, asset_by_id):
                        _add(findings, "screen-text-state-lineage-unproven",
                               f"画面文字 {label}: {asset_id} 未通过 derived_from 证明来自 {root_id}")
                expected_by_asset = item.get("expected_text_by_asset")
                if not isinstance(expected_by_asset, dict) or set(expected_by_asset) != set(state_ids):
                    _add(findings, "screen-text-state-expectations-missing",
                           f"画面文字 {label}: expected_text_by_asset 必须逐状态资产登记期望文字")
                else:
                    for asset_id in state_ids:
                        text_lock = asset_by_id[asset_id].get("text_lock")
                        if not isinstance(text_lock, dict) \
                                or text_lock.get("expected_text") != expected_by_asset.get(asset_id) \
                                or not text_lock_has_user_proof(text_lock):
                            _add(findings, "screen-text-state-proof-incomplete",
                                   f"画面文字 {label}: {asset_id} 的文字锁/用户逐字确认与期望状态不一致")
    return findings


def asset_derives_from(asset_id, root_id, asset_by_id, seen=None):
    if asset_id == root_id:
        return True
    seen = set() if seen is None else seen
    if asset_id in seen:
        return False
    seen.add(asset_id)
    asset = asset_by_id.get(asset_id)
    if not isinstance(asset, dict):
        return False
    parents = asset.get("derived_from")
    if not isinstance(parents, list):
        return False
    return any(
        parent == root_id or asset_derives_from(parent, root_id, asset_by_id, seen.copy())
        for parent in parents if isinstance(parent, str)
    )


def validate_lineage_uploads(unit_id, bound_asset_by_slot):
    findings = []
    lineage_groups = {}
    for bound_asset in bound_asset_by_slot.values():
        if not isinstance(bound_asset, dict):
            continue
        contract = bound_asset.get("asset_contract")
        if not isinstance(contract, dict):
            continue
        root_id = contract.get("provenance", {}).get("lineage_root_asset_id")
        if root_id:
            lineage_groups.setdefault(root_id, []).append(bound_asset)
    for root_id, grouped_assets in lineage_groups.items():
        if len(grouped_assets) < 2:
            continue
        final_only = [asset for asset in grouped_assets
                      if asset.get("asset_contract", {}).get("upload_policy", {}).get("mode")
                      == "lineage-final-only"]
        justified = all(asset.get("asset_contract", {}).get("upload_policy", {}).get("justification")
                        for asset in grouped_assets)
        if final_only and not justified:
            _add(findings, "input-lineage-duplicate",
                   f"{unit_id}: 同谱系 {root_id} 同时上传 {sorted(a.get('asset_id') for a in grouped_assets)}；"
                   "最终状态图已承担当前状态时不得再上传 canonical/其它状态")
    return findings
