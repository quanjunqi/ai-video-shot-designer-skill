#!/usr/bin/env python3
"""Submit and retrieve MiniMax H3 videos through the AutoDL Art workflow API."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import time
import urllib.error
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import adapter_config


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = adapter_config.by_contract("autodl-minimax-h3-v1")
if ADAPTER is None:  # pragma: no cover
    raise RuntimeError("missing autodl-minimax-h3-v1 adapter config")
DEFAULT_BASE_URL = ADAPTER["api"]["base_url"]
DEFAULT_WORKFLOW = ADAPTER["api"]["workflow"]
RESOLUTIONS = tuple(ADAPTER["limits"]["resolutions"])
PROMPT_MIN = adapter_config.limit(ADAPTER, "prompt_characters", "min")
PROMPT_MAX = adapter_config.limit(ADAPTER, "prompt_characters", "max")
DURATION_MIN = adapter_config.limit(ADAPTER, "unit_duration_seconds", "min")
DURATION_MAX = adapter_config.limit(ADAPTER, "unit_duration_seconds", "max")
IMAGE_MIN = adapter_config.limit(ADAPTER, "reference_images", "min")
IMAGE_MAX = adapter_config.limit(ADAPTER, "reference_images", "max")
AUDIO_MIN = adapter_config.limit(ADAPTER, "reference_audio", "min")
AUDIO_MAX = adapter_config.limit(ADAPTER, "reference_audio", "max")
SUCCESS_STATES = {"completed", "complete", "success", "succeeded", "done"}
FAILURE_STATES = {"failed", "failure", "error", "cancelled", "canceled"}
MAX_RETRIES = 3
REFERENCE_DEFINITION_RE = re.compile(
    r"(?m)^\s*<(Subject|Picture|Video|Audio)\s+(\d+)>\s+(.+?)\s*$",
    re.I,
)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_token() -> str:
    load_dotenv(ROOT / ".env")
    token = os.getenv("AUTODL_ART_TOKEN", "").strip()
    if not token or token == "replace_with_your_token":
        raise SystemExit("Missing AUTODL_ART_TOKEN in the environment or .env")
    return token


def is_remote_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_reference_urls(values: list[str], kind: str, maximum: int, minimum: int = 0) -> None:
    if len(values) < minimum or len(values) > maximum:
        raise SystemExit(f"{kind} count must be between {minimum} and {maximum}; got {len(values)}")
    invalid = [value for value in values if not is_remote_url(value)]
    if invalid:
        raise SystemExit(f"{kind} must use public HTTP(S) URLs: {invalid[0]}")


def extract_h3_prompt(text: str) -> str:
    blocks = re.findall(r"```(?:text)?\s*\n(.*?)```", text, re.S | re.I)
    candidates = [block.strip() for block in blocks if re.search(r"(?m)^subject_definitions\s*:", block)]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise SystemExit("Prompt file contains multiple H3 blocks; provide a single-unit file")
    return text.strip()


def resolve_prompt(prompt: str | None, prompt_file: Path | None) -> str:
    if prompt is not None:
        value = prompt
    elif prompt_file is not None:
        try:
            value = extract_h3_prompt(prompt_file.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SystemExit(f"Unable to read prompt file {prompt_file}: {exc}") from exc
    else:
        raise SystemExit("Provide --prompt or --prompt-file")
    length = len(value)
    if not PROMPT_MIN <= length <= PROMPT_MAX:
        raise SystemExit(
            "AutoDL minimax_h3_zm_u24 adapter requires prompt to contain "
            f"{PROMPT_MIN}-{PROMPT_MAX} characters; got {length}"
        )
    return value


def build_payload(prompt: str, duration: int, resolution: str, seed: int | None,
                  images: list[str], audios: list[str]) -> dict:
    if not DURATION_MIN <= duration <= DURATION_MAX:
        raise SystemExit(
            f"duration must be between {DURATION_MIN} and {DURATION_MAX} seconds; got {duration}")
    if resolution not in RESOLUTIONS:
        raise SystemExit(f"Unsupported resolution: {resolution}")
    validate_reference_urls(images, "reference image", IMAGE_MAX, minimum=IMAGE_MIN)
    validate_reference_urls(audios, "reference audio", AUDIO_MAX, minimum=AUDIO_MIN)
    payload = {"prompt": prompt, "duration": duration, "resolution": resolution}
    if seed is not None:
        payload["seed"] = seed
    payload.update({f"ref_image_{index}": url for index, url in enumerate(images)})
    payload.update({f"ref_audio_{index}": url for index, url in enumerate(audios)})
    return payload


def validate_prompt_reference_bindings(
        prompt: str, values: list[str], reference_kind: str) -> list[dict]:
    if reference_kind not in {"image", "audio"}:
        raise ValueError(f"unsupported reference kind: {reference_kind}")
    section_match = re.search(
        r"(?ms)^subject_definitions\s*:\s*(.*?)(?=^summary\s*:)",
        prompt,
    )
    if not section_match:
        raise SystemExit("Prompt must contain subject_definitions before summary")
    definitions = [
        (kind.title(), int(number), body)
        for kind, number, body in REFERENCE_DEFINITION_RE.findall(section_match.group(1))
    ]
    bindings = []
    for reference_index, url in enumerate(values):
        api_field = f"ref_{reference_kind}_{reference_index}"
        matches = [
            (kind, number)
            for kind, number, body in definitions
            if re.search(rf"\b{re.escape(api_field)}\b", body, re.I)
        ]
        if len(matches) != 1:
            raise SystemExit(
                f"{api_field} must appear in exactly one H3 tag definition "
                f"inside subject_definitions; found {len(matches)}"
            )
        kind, number = matches[0]
        if reference_kind == "audio" and kind != "Audio":
            raise SystemExit(f"{api_field} must bind to an <Audio N> definition, got <{kind} {number}>")
        if reference_kind == "image" and kind not in {"Subject", "Picture"}:
            raise SystemExit(
                f"{api_field} must bind to a <Subject N> or <Picture N> definition, got <{kind} {number}>")
        bindings.append({"api_field": api_field, "prompt_slot": f"<{kind} {number}>", "url": url})
    referenced_fields = {
        int(number)
        for _, _, body in definitions
        for number in re.findall(rf"\bref_{reference_kind}_(\d+)\b", body, re.I)
    }
    unexpected = sorted(referenced_fields - set(range(len(values))))
    if unexpected:
        raise SystemExit(f"Prompt binds {reference_kind} fields that were not uploaded: {unexpected}")
    return bindings


def validate_prompt_image_bindings(prompt: str, images: list[str]) -> list[dict]:
    return validate_prompt_reference_bindings(prompt, images, "image")


def validate_prompt_audio_bindings(prompt: str, audios: list[str]) -> list[dict]:
    return validate_prompt_reference_bindings(prompt, audios, "audio")


def canonical_hash(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_context_reference(path: Path, artifact_root: Path) -> dict:
    """Load the small upstream context receipt used for request provenance."""
    try:
        path.resolve().relative_to(artifact_root.resolve())
        reference = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"Unable to read context reference {path}: {exc}") from exc
    if not isinstance(reference, dict):
        raise SystemExit("context reference must be a JSON object")
    required = ("context_type", "scope_id", "context_hash", "path", "cache_hit", "artifact_keys")
    missing = [key for key in required if key not in reference]
    if missing:
        raise SystemExit(f"context reference is missing: {', '.join(missing)}")
    for field in ("context_type", "scope_id", "path"):
        if not isinstance(reference[field], str) or not reference[field].strip():
            raise SystemExit(f"context reference {field} must be a non-empty string")
    if not isinstance(reference["cache_hit"], bool):
        raise SystemExit("context reference cache_hit must be boolean")
    if not isinstance(reference["context_hash"], str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", reference["context_hash"]):
        raise SystemExit("context reference context_hash must use sha256:<hex>")
    artifact_keys = reference["artifact_keys"]
    if (not isinstance(artifact_keys, list) or
            not artifact_keys or
            any(not isinstance(key, str) or not key.strip() for key in artifact_keys)):
        raise SystemExit("context reference artifact_keys must be a non-empty list of strings")
    if len(artifact_keys) != len(set(artifact_keys)):
        raise SystemExit("context reference artifact_keys must be unique")
    request_sha256 = reference.get("request_sha256")
    if request_sha256 is not None and (
            not isinstance(request_sha256, str) or
            not re.fullmatch(r"sha256:[0-9a-f]{64}", request_sha256)):
        raise SystemExit("context reference request_sha256 must use sha256:<hex>")
    raw_context_path = Path(reference["path"])
    if raw_context_path.is_absolute():
        raise SystemExit("context reference path must be relative to --artifact-root")
    resolved_context_path = (artifact_root / raw_context_path).resolve()
    try:
        resolved_context_path.relative_to(artifact_root.resolve())
    except ValueError as exc:
        raise SystemExit("context reference path must stay inside --artifact-root") from exc
    if not resolved_context_path.is_file():
        raise SystemExit(f"context reference target is missing: {reference['path']}")
    try:
        packet = json.loads(resolved_context_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"context reference target is not a context packet: {exc}") from exc
    if not isinstance(packet, dict) or packet.get("context_hash") != reference["context_hash"]:
        raise SystemExit("context reference hash does not match its context packet")
    if (packet.get("context_type"), packet.get("scope_id")) != (
            reference["context_type"], reference["scope_id"]):
        raise SystemExit("context reference scope does not match its context packet")
    packet_inputs = packet.get("inputs")
    if not isinstance(packet_inputs, list) or not packet_inputs:
        raise SystemExit("context reference target has no context inputs")
    packet_keys = [record.get("key") for record in packet_inputs if isinstance(record, dict)]
    if (len(packet_keys) != len(packet_inputs) or
            any(not isinstance(key, str) or not key.strip() for key in packet_keys)):
        raise SystemExit("context reference target has invalid context inputs")
    if sorted(artifact_keys) != sorted(packet_keys):
        raise SystemExit("context reference artifact_keys do not match its context packet")
    return {
        "context_type": reference["context_type"],
        "scope_id": reference["scope_id"],
        "context_hash": reference["context_hash"],
        "path": str(raw_context_path),
        "cache_hit": reference["cache_hit"],
        "artifact_keys": artifact_keys,
        **({"request_sha256": request_sha256} if request_sha256 is not None else {}),
    }


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def api_urls() -> tuple[str, str]:
    load_dotenv(ROOT / ".env")
    base = os.getenv("AUTODL_ART_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    workflow = os.getenv("AUTODL_ART_MINIMAX_WORKFLOW", DEFAULT_WORKFLOW).strip("/")
    return f"{base}/{workflow}", f"{base}/result"


def request_json(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        request = Request(
            url,
            data=body,
            headers={"Authorization": token, "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict):
                raise ValueError("API response is not a JSON object")
            return result
        except urllib.error.HTTPError as exc:
            try:
                error_result = json.loads(exc.read().decode("utf-8"))
                message = error_result.get("msg") or error_result.get("message") or exc.reason
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                message = exc.reason
            finally:
                exc.close()
            last_error = f"HTTP {exc.code}: {message}"
            if 400 <= exc.code < 500:
                break
            if attempt < MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))
    raise SystemExit(f"AutoDL Art request failed after {MAX_RETRIES} attempts: {last_error}")


def response_data(result: dict) -> dict:
    data = result.get("data")
    return data if isinstance(data, dict) else {}


def response_state(result: dict) -> str:
    return str(response_data(result).get("status", result.get("status", ""))).strip().lower()


def normalized_attempt_state(result: dict) -> str:
    state = response_state(result)
    if state in SUCCESS_STATES or response_results(result):
        return "completed"
    if state in {"queued", "queue", "pending", "waiting"}:
        return "queued"
    if state in {"running", "processing", "in_progress", "in-progress"}:
        return "running"
    return "submitted"


def response_task_id(result: dict) -> str | None:
    value = response_data(result).get("task_id") or result.get("task_id")
    return str(value) if value else None


def response_results(result: dict) -> list[dict]:
    values = response_data(result).get("results", result.get("results", []))
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def ensure_success_code(result: dict) -> None:
    code = result.get("code")
    if code not in (None, "", "Success", "success", 0, "0"):
        message = result.get("msg") or result.get("message") or "unknown API error"
        raise SystemExit(f"AutoDL Art API rejected the request: code={code}, message={message}")


def submit(payload: dict) -> dict:
    submit_url, _ = api_urls()
    result = request_json("POST", submit_url, require_token(), payload)
    ensure_success_code(result)
    if not response_task_id(result):
        raise SystemExit("Submission response did not include data.task_id")
    return result


def poll(task_id: str, interval: float = 3, timeout: float = 900) -> dict:
    _, result_base = api_urls()
    token = require_token()
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        result = request_json("GET", f"{result_base}/{task_id}", token)
        ensure_success_code(result)
        state = response_state(result)
        if state in SUCCESS_STATES or response_results(result):
            return result
        if state in FAILURE_STATES:
            message = result.get("msg") or response_data(result).get("message") or "unknown task failure"
            raise SystemExit(f"MiniMax H3 task {task_id} failed: {message}")
        time.sleep(interval)
    raise SystemExit(f"MiniMax H3 task {task_id} timed out after {timeout:g}s")


def download_videos(result: dict, output_dir: Path, prefix: str) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, item in enumerate(response_results(result), 1):
        if item.get("type") != "video" or not is_remote_url(str(item.get("url", ""))):
            continue
        suffix = "." + str(item.get("file_type", "mp4")).lstrip(".")
        path = output_dir / f"{prefix}_{index:02d}{suffix}"
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with urlopen(item["url"], timeout=300) as response:
                    path.write_bytes(response.read())
                break
            except (OSError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** (attempt - 1))
        else:
            raise SystemExit(f"Video download failed after {MAX_RETRIES} attempts: {last_error}")
        paths.append({"result_url": item["url"], "local_path": str(path), "sha256": file_hash(path)})
    if not paths:
        raise SystemExit("Completed response did not include a downloadable video result")
    return paths


def save_metadata(result: dict, request_meta: dict, directory: Path, prefix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    saved = dict(result)
    saved["_request"] = request_meta
    path = directory / f"{prefix}_result.json"
    path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def add_generation_arguments(parser: argparse.ArgumentParser) -> None:
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt")
    prompt_group.add_argument("--prompt-file", type=Path)
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--resolution", choices=RESOLUTIONS, default="768p竖")
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--ref-image", action="append", default=[],
        help=f"Public image URL; repeat {IMAGE_MIN}-{IMAGE_MAX} times")
    parser.add_argument(
        "--ref-audio", action="append", default=[],
        help=f"Public audio URL; repeat {AUDIO_MIN}-{AUDIO_MAX} times")
    parser.add_argument("--metadata-dir", type=Path,
                        help="Defaults to <artifact-root>/stage5/metadata/videos")
    parser.add_argument("--prefix", default="minimax-h3")
    parser.add_argument("--unit-id", required=True, help="Stable manifest unit_id for this request")
    parser.add_argument("--context-reference", type=Path,
                        help="JSON receipt emitted by the upstream context compiler")
    parser.add_argument("--asset-id", help="Stable asset_id; only valid when one video is returned")
    parser.add_argument("--artifact-root", type=Path, default=Path.cwd(),
                        help="Current isolated case root; recorded paths must remain below it")
    parser.add_argument("--json", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoDL Art MiniMax H3 workflow client")
    commands = parser.add_subparsers(dest="command", required=True)
    submit_parser = commands.add_parser("submit", help="Submit without waiting")
    add_generation_arguments(submit_parser)
    run_parser = commands.add_parser("run", help="Submit, poll and download")
    add_generation_arguments(run_parser)
    run_parser.add_argument("--output-dir", type=Path,
                            help="Defaults to <artifact-root>/stage5/generated-videos")
    run_parser.add_argument("--poll-interval", type=float, default=3)
    run_parser.add_argument("--poll-timeout", type=float, default=900)
    poll_parser = commands.add_parser("poll", help="Poll an existing task")
    poll_parser.add_argument("task_id")
    poll_parser.add_argument("--output-dir", type=Path,
                             help="Defaults to <artifact-root>/stage5/generated-videos")
    poll_parser.add_argument("--metadata-dir", type=Path,
                             help="Defaults to <artifact-root>/stage5/metadata/videos")
    poll_parser.add_argument("--prefix", default="minimax-h3")
    poll_parser.add_argument("--unit-id", required=True)
    poll_parser.add_argument("--asset-id")
    poll_parser.add_argument("--request-metadata", type=Path, required=True,
                             help="Metadata JSON written by the original submit command")
    poll_parser.add_argument("--artifact-root", type=Path, default=Path.cwd(),
                             help="Current isolated case root; recorded paths must remain below it")
    poll_parser.add_argument("--poll-interval", type=float, default=3)
    poll_parser.add_argument("--poll-timeout", type=float, default=900)
    poll_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    artifact_root = args.artifact_root.resolve()
    if args.metadata_dir is None:
        args.metadata_dir = artifact_root / "stage5" / "metadata" / "videos"
    if hasattr(args, "output_dir") and args.output_dir is None:
        args.output_dir = artifact_root / "stage5" / "generated-videos"
    for field in ("metadata_dir", "output_dir"):
        path = getattr(args, field, None)
        if path is None:
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(artifact_root)
        except ValueError as exc:
            raise SystemExit(f"--{field.replace('_', '-')} must be inside --artifact-root") from exc
    for field in ("prompt_file", "request_metadata", "context_reference"):
        path = getattr(args, field, None)
        if path is None:
            continue
        try:
            path.resolve().relative_to(artifact_root)
        except ValueError as exc:
            raise SystemExit(f"--{field.replace('_', '-')} must be inside --artifact-root") from exc

    request_meta = {}
    if args.command in {"submit", "run"}:
        prompt = resolve_prompt(args.prompt, args.prompt_file)
        payload = build_payload(prompt, args.duration, args.resolution, args.seed, args.ref_image, args.ref_audio)
        input_bindings = validate_prompt_image_bindings(prompt, args.ref_image)
        audio_bindings = validate_prompt_audio_bindings(prompt, args.ref_audio)
        request_meta = {
            "workflow": os.getenv("AUTODL_ART_MINIMAX_WORKFLOW", DEFAULT_WORKFLOW).strip("/"),
            "prompt": prompt,
            "prompt_characters": len(prompt),
            "duration": args.duration,
            "resolution": args.resolution,
            "seed": args.seed,
            "reference_images": args.ref_image,
            "input_bindings": input_bindings,
            "reference_audios": args.ref_audio,
            "audio_bindings": audio_bindings,
            "unit_id": args.unit_id,
        }
        if args.context_reference is not None:
            request_meta["context"] = load_context_reference(
                args.context_reference, artifact_root)
        submitted_at = datetime.now(timezone.utc).isoformat()
        submitted = submit(payload)
        task_id = response_task_id(submitted)
        if args.command == "submit":
            metadata_path = args.metadata_dir / f"{args.prefix}_result.json"
            active_generation = {
                "unit_id": args.unit_id,
                "task_id": task_id,
                "request_metadata_path": str(metadata_path.resolve().relative_to(artifact_root)),
                "request_metadata_hash": canonical_hash(request_meta),
                "submitted_at": submitted_at,
                "status": normalized_attempt_state(submitted),
            }
            saved_submission = dict(submitted)
            saved_submission["active_generation"] = active_generation
            metadata = save_metadata(saved_submission, request_meta, args.metadata_dir, args.prefix)
            print(f"任务已提交：{task_id}")
            print(f"元数据已写入：{metadata}")
            print("manifest.active_generation：" + json.dumps(active_generation, ensure_ascii=False))
            if args.json:
                print(json.dumps({**saved_submission, "_request": request_meta}, ensure_ascii=False, indent=2))
            return 0
        result = submitted if response_results(submitted) else poll(task_id, args.poll_interval, args.poll_timeout)
    else:
        task_id = args.task_id
        try:
            submitted_metadata = json.loads(args.request_metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Unable to read original request metadata: {exc}") from exc
        recorded_task_id = response_task_id(submitted_metadata)
        if recorded_task_id != task_id:
            raise SystemExit(
                f"Original request metadata belongs to task {recorded_task_id}, not {task_id}"
            )
        request_meta = submitted_metadata.get("_request")
        if not isinstance(request_meta, dict) or request_meta.get("unit_id") != args.unit_id:
            raise SystemExit("Original request metadata does not bind the requested unit_id")
        submitted_at = (submitted_metadata.get("active_generation") or {}).get("submitted_at")
        if not submitted_at:
            raise SystemExit("Original request metadata does not include active_generation.submitted_at")
        result = poll(task_id, args.poll_interval, args.poll_timeout)

    downloads = download_videos(result, args.output_dir, args.prefix)
    if args.asset_id and len(downloads) != 1:
        raise SystemExit("--asset-id requires exactly one returned video")
    request_metadata_hash = canonical_hash(request_meta)
    generated_assets = []
    metadata_path = args.metadata_dir / f"{args.prefix}_result.json"
    for index, download in enumerate(downloads, 1):
        generated_assets.append({
            "asset_id": args.asset_id or f"video-{args.unit_id}-{task_id}-{index:02d}",
            "tag": f"generated-video-{args.unit_id}-{index:02d}",
            "kind": "generated-video",
            "unit_id": args.unit_id,
            "task_id": task_id,
            "result_url": download["result_url"],
            "local_path": str(Path(download["local_path"]).resolve().relative_to(artifact_root)),
            "sha256": download["sha256"],
            "request_metadata_hash": request_metadata_hash,
            "request_metadata_path": str(metadata_path.resolve().relative_to(artifact_root)),
        })
    saved = dict(result)
    saved["local_files"] = [item["local_path"] for item in downloads]
    saved["generated_video_assets"] = generated_assets
    saved["request_metadata_hash"] = request_metadata_hash
    saved["active_generation"] = {
        "unit_id": args.unit_id,
        "task_id": task_id,
        "request_metadata_path": str(metadata_path.resolve().relative_to(artifact_root)),
        "request_metadata_hash": request_metadata_hash,
        "submitted_at": submitted_at,
        "status": "completed",
    }
    metadata = save_metadata(saved, request_meta, args.metadata_dir, args.prefix)
    print(f"任务已完成：{task_id}")
    print(f"视频已下载：{len(downloads)} 个")
    for item in downloads:
        print(f"- {item['local_path']} ({item['sha256']})")
    print(f"元数据已写入：{metadata}")
    print("manifest.active_generation：" + json.dumps(saved["active_generation"], ensure_ascii=False))
    if args.json:
        print(json.dumps({**saved, "_request": request_meta}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
