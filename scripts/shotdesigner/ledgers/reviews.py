"""Create and persist immutable user review events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import review_policy
from .project import utc_now


AMBIGUOUS_APPROVAL_MARKERS = (
    "不清楚", "不知道", "不确定", "先进行下一步", "先继续", "暂定", "稍后确认",
    "没选好", "还没选", "尚未选", "未选定", "没有选",
    "defer", "provisional", "not sure", "don't know", "do not know",
)
EXPLICIT_APPROVAL_MARKERS = (
    "通过", "确认", "同意", "批准", "接受", "选择", "挑选", "选好", "选定",
    "采用", "锁定", "就用这", "用这张",
    "approve", "approved", "confirm", "confirmed", "accept", "accepted", "select",
)


def is_explicit_approval_statement(statement: str) -> bool:
    normalized = " ".join(statement.strip().lower().split())
    if not normalized or any(marker in normalized for marker in AMBIGUOUS_APPROVAL_MARKERS):
        return False
    return any(marker in normalized for marker in EXPLICIT_APPROVAL_MARKERS)


def create_review(
    *, review_id: str, artifact_id: str, artifact_type: str, scope_id: str,
    artifact_version: int, artifact_sha256: str, decision: str,
    user_statement: str, decided_at: str | None = None,
    requested_changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    policy = review_policy()
    if decision not in policy["decisions"]:
        raise ValueError(f"unsupported review decision: {decision}")
    if not user_statement.strip():
        raise ValueError("user_statement is required; AI cannot invent user approval")
    if not artifact_sha256.startswith("sha256:"):
        raise ValueError("artifact_sha256 must use the sha256:<hex> form")
    if decision in policy["approval_decisions"] and not is_explicit_approval_statement(user_statement):
        raise ValueError("approval requires an explicit, unambiguous user statement")
    if decision in policy["approval_decisions"]:
        status = "USER_APPROVED"
    elif decision in {"reject", "request_changes", "regenerate"}:
        status = "USER_REJECTED"
    else:
        status = "AWAITING_USER"
    return {
        "review_id": review_id,
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "scope_id": scope_id,
        "artifact_version": artifact_version,
        "artifact_sha256": artifact_sha256,
        "decision": decision,
        "resulting_status": status,
        "user_statement": user_statement,
        "requested_changes": requested_changes or [],
        "decided_by": "user",
        "decided_at": decided_at or utc_now(),
    }


def append_review(path: str | Path, review: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(review, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_reviews(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    reviews = []
    for number, raw in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid review ledger line {number}: {exc}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"review ledger line {number} must be an object")
        reviews.append(item)
    return reviews
