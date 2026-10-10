"""Validate generated-video files and active generation attempts."""

from __future__ import annotations

import hashlib
import json
import re

from shotdesigner.findings import Finding


VIDEO_ASSET_KINDS = {"video", "generated-video", "video-output"}
VIDEO_ASSET_FIELDS = (
    "asset_id", "kind", "unit_id", "task_id", "result_url", "local_path",
    "sha256", "request_metadata_hash", "request_metadata_path",
)
GENERATION_ATTEMPT_FIELDS = (
    "unit_id", "task_id", "request_metadata_path", "request_metadata_hash",
    "submitted_at", "status",
)
GENERATION_ATTEMPT_STATES = {"submitted", "queued", "running", "completed"}


def _add(findings, code, message):
    findings.append(Finding(code=code, severity="ERROR", message=message))


def validate_video_assets(asset_list, unit_by_id, artifact_root, resolve_artifact, sha256):
    findings = []
    for asset in asset_list:
        if not isinstance(asset, dict) or asset.get("kind") not in VIDEO_ASSET_KINDS:
            continue
        asset_id = asset.get("asset_id", "<unknown>")
        missing = [field for field in VIDEO_ASSET_FIELDS
                   if field not in asset or asset.get(field) in (None, "")]
        if missing:
            _add(findings, "generated-video-asset-incomplete",
                   f"{asset_id}: 生成视频资产缺少 {missing}")
            continue
        if asset.get("unit_id") not in unit_by_id:
            _add(findings, "generated-video-unit-unknown",
                   f"{asset_id}: unit_id={asset.get('unit_id')} 不存在")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(asset.get("sha256"))):
            _add(findings, "generated-video-hash-invalid",
                   f"{asset_id}: sha256 格式非法")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(asset.get("request_metadata_hash"))):
            _add(findings, "generated-video-request-hash-invalid",
                   f"{asset_id}: request_metadata_hash 格式非法")
        if not re.match(r"^https?://", str(asset.get("result_url"))):
            _add(findings, "generated-video-url-invalid",
                   f"{asset_id}: result_url 必须是 HTTP(S) URL")
        if artifact_root is not None and asset.get("local_path"):
            try:
                path = resolve_artifact(artifact_root, asset["local_path"])
            except (TypeError, ValueError) as exc:
                _add(findings, "generated-video-path-invalid",
                     f"{asset_id}: 本地视频路径非法: {exc}")
                continue
            if not path.is_file():
                _add(findings, "generated-video-file-missing",
                       f"{asset_id}: 本地视频不存在 {path}")
            elif sha256(path) != asset.get("sha256"):
                _add(findings, "generated-video-file-hash-drift",
                       f"{asset_id}: 本地视频内容与登记 sha256 不一致")
        if artifact_root is not None and asset.get("request_metadata_path"):
            try:
                metadata_path = resolve_artifact(artifact_root, asset["request_metadata_path"])
            except (TypeError, ValueError) as exc:
                _add(findings, "generated-video-metadata-path-invalid",
                     f"{asset_id}: 请求元数据路径非法: {exc}")
                continue
            if not metadata_path.is_file():
                _add(findings, "generated-video-metadata-missing",
                       f"{asset_id}: 请求元数据不存在 {metadata_path}")
            else:
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    request_meta = metadata.get("_request", {})
                    canonical = json.dumps(request_meta, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")
                    request_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
                    if request_hash != asset.get("request_metadata_hash"):
                        _add(findings, "generated-video-request-hash-drift",
                               f"{asset_id}: 请求元数据与登记 hash 不一致")
                    response_data = metadata.get("data", {}) or {}
                    response_task_id = response_data.get("task_id")
                    if not response_task_id:
                        _add(findings, "generated-video-task-proof-missing",
                               f"{asset_id}: 请求元数据缺少 data.task_id")
                    elif str(response_task_id) != str(asset.get("task_id")):
                        _add(findings, "generated-video-task-drift",
                               f"{asset_id}: task_id 与请求元数据不一致")
                    response_status = str(response_data.get("status", "")).strip().lower()
                    if response_status not in {"completed", "complete", "success", "succeeded", "done"}:
                        _add(findings, "generated-video-result-not-successful",
                               f"{asset_id}: 请求元数据没有成功完成状态，当前={response_status or '<missing>'}")
                    result_urls = {item.get("url") for item in response_data.get("results", [])
                                   if isinstance(item, dict) and item.get("type") == "video"}
                    if asset.get("result_url") not in result_urls:
                        _add(findings, "generated-video-result-url-drift",
                               f"{asset_id}: result_url 不属于该任务结果")
                except (OSError, json.JSONDecodeError, AttributeError) as exc:
                    _add(findings, "generated-video-metadata-invalid",
                           f"{asset_id}: 请求元数据无法解析: {exc}")
    return findings


def validate_active_generation(workflow, unit_by_id, asset_by_id, artifact_root, resolve_artifact):
    findings = []
    state = workflow.get("workflow_state")
    attempt = workflow.get("active_generation")
    if state == "IN_PRODUCTION" and not isinstance(attempt, dict):
        _add(findings, "active-generation-missing",
               "IN_PRODUCTION 必须登记 active_generation 及真实任务提交证据")
        return findings
    if attempt is None:
        return findings
    if not isinstance(attempt, dict):
        _add(findings, "active-generation-type", "active_generation 必须是对象")
        return findings
    missing = [field for field in GENERATION_ATTEMPT_FIELDS
               if field not in attempt or attempt.get(field) in (None, "")]
    if missing:
        _add(findings, "active-generation-incomplete",
               f"active_generation 缺少 {missing}")
        return findings
    active_unit_id = workflow.get("active_unit_id")
    if attempt.get("unit_id") != active_unit_id or active_unit_id not in unit_by_id:
        _add(findings, "active-generation-unit-drift",
               "active_generation.unit_id 必须等于存在的 active_unit_id")
    if attempt.get("status") not in GENERATION_ATTEMPT_STATES:
        _add(findings, "active-generation-status-invalid",
               f"active_generation.status 必须是 {sorted(GENERATION_ATTEMPT_STATES)}")
    elif state == "IN_PRODUCTION" and attempt.get("status") == "completed":
        _add(findings, "active-generation-state-stale",
               "任务已 completed 时 workflow_state 必须推进到 USER_REVIEW_PENDING")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(attempt.get("request_metadata_hash"))):
        _add(findings, "active-generation-request-hash-invalid",
               "active_generation.request_metadata_hash 格式非法")
    if artifact_root is not None:
        try:
            metadata_path = resolve_artifact(artifact_root, attempt["request_metadata_path"])
        except (TypeError, ValueError) as exc:
            _add(findings, "active-generation-metadata-path-invalid",
                 f"active_generation 请求元数据路径非法: {exc}")
            metadata_path = None
        if metadata_path is not None:
            if not metadata_path.is_file():
                _add(findings, "active-generation-metadata-missing",
                       f"active_generation 请求元数据不存在: {metadata_path}")
            else:
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    request_meta = metadata.get("_request")
                    if not isinstance(request_meta, dict):
                        raise ValueError("缺少 _request 对象")
                    canonical = json.dumps(request_meta, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")
                    request_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
                    if request_hash != attempt.get("request_metadata_hash"):
                        _add(findings, "active-generation-request-hash-drift",
                               "active_generation 请求元数据与登记 hash 不一致")
                    if request_meta.get("unit_id") != attempt.get("unit_id"):
                        _add(findings, "active-generation-request-unit-drift",
                               "active_generation 请求元数据未绑定同一 unit_id")
                    response_task_id = (metadata.get("data", {}) or {}).get("task_id")
                    if not response_task_id or str(response_task_id) != str(attempt.get("task_id")):
                        _add(findings, "active-generation-task-drift",
                               "active_generation.task_id 与提交元数据不一致或缺失")
                except (OSError, json.JSONDecodeError, AttributeError, ValueError) as exc:
                    _add(findings, "active-generation-metadata-invalid",
                           f"active_generation 请求元数据无法解析: {exc}")
    video_asset_id = unit_by_id.get(attempt.get("unit_id"), {}).get("video_asset_id")
    video_asset = asset_by_id.get(video_asset_id) if video_asset_id else None
    if video_asset and str(video_asset.get("task_id")) != str(attempt.get("task_id")):
        _add(findings, "active-generation-video-task-drift",
               "活动单元的视频资产与 active_generation 不是同一任务")
    return findings
