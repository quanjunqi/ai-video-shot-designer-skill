"""Provider-neutral image generation service with one configurable adapter."""

from __future__ import annotations

import base64
import json
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]


def http_error_message(exc: HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
        value = json.loads(raw)
        error = value.get("error", value) if isinstance(value, dict) else value
        if isinstance(error, dict):
            message = error.get("message") or error.get("msg") or error.get("detail")
            if message:
                return f"HTTP {exc.code}: {message}"
        if isinstance(error, str) and error.strip():
            return f"HTTP {exc.code}: {error.strip()}"
        if raw.strip():
            return f"HTTP {exc.code}: {raw.strip()[:500]}"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        pass
    return f"HTTP {exc.code}: {exc.reason}"


def load_adapter(path: Path | None = None) -> dict:
    source = path or ROOT / "config" / "adapters" / "image-generation" / "openai-compatible.json"
    value = json.loads(source.read_text(encoding="utf-8"))
    required = ("adapter_id", "base_url_env", "token_env", "model_env", "endpoint")
    missing = [field for field in required if not value.get(field)]
    if missing:
        raise ValueError(f"image adapter config missing: {missing}")
    return value


class ImageGenerationService:
    def __init__(self, adapter: dict | None = None, environ: dict | None = None):
        self.adapter = adapter or load_adapter()
        self.environ = environ if environ is not None else os.environ

    def configuration(self, reference_edit: bool = False) -> tuple[str, str, str]:
        base = self.environ.get(self.adapter["base_url_env"], "").rstrip("/")
        token = self.environ.get(self.adapter["token_env"], "")
        model_env = (self.adapter.get("reference_model_env")
                     if reference_edit else self.adapter["model_env"])
        model = self.environ.get(model_env or self.adapter["model_env"], "")
        missing = [name for name, value in (("base_url", base), ("token", token), ("model", model)) if not value]
        if missing:
            raise ValueError(f"image generation configuration missing: {missing}")
        return base, token, model

    def generate(self, prompt: str, count: int, output_dir: Path,
                 size: str | None = None) -> tuple[list[dict], dict]:
        if not prompt.strip():
            raise ValueError("image prompt is required")
        if not isinstance(count, int) or count < 1 or count > 8:
            raise ValueError("candidate count must be 1-8")
        base, token, model = self.configuration()
        request_limit = self.adapter.get("max_images_per_request", count)
        if not isinstance(request_limit, int) or request_limit < 1:
            raise ValueError("max_images_per_request must be a positive integer")
        image_size = size or self.adapter.get("default_size", "1024x1536")
        output_dir.mkdir(parents=True, exist_ok=True)
        candidates = []
        response_ids = []
        while len(candidates) < count:
            request_count = min(request_limit, count - len(candidates))
            payload = {"model": model, "prompt": prompt, "n": request_count, "size": image_size}
            request = Request(
                base + self.adapter["endpoint"],
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=180) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                message = http_error_message(exc)
                exc.close()
                raise RuntimeError(f"image generation request failed: {message}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"image generation request failed: {exc}") from exc
            items = result.get("data") if isinstance(result, dict) else None
            if not isinstance(items, list) or not items:
                raise RuntimeError("image generation response contains no data items")
            if len(items) > request_count:
                raise RuntimeError("image generation response contains more items than requested")
            response_ids.append(result.get("id") if isinstance(result, dict) else None)
            for item in items:
                index = len(candidates) + 1
                if not isinstance(item, dict):
                    raise RuntimeError(f"image result {index} is not an object")
                path = output_dir / f"candidate-{index:02d}.png"
                if item.get("b64_json"):
                    path.write_bytes(base64.b64decode(item["b64_json"], validate=True))
                    source = "base64"
                elif item.get("url"):
                    try:
                        with urlopen(item["url"], timeout=180) as response:
                            path.write_bytes(response.read())
                    except (HTTPError, URLError, TimeoutError) as exc:
                        raise RuntimeError(f"candidate download failed: {exc}") from exc
                    source = item["url"]
                else:
                    raise RuntimeError(f"image result {index} lacks url or b64_json")
                candidates.append({"candidate_id": f"candidate-{index:02d}", "path": str(path),
                                   "source": source})
        metadata = {"adapter_id": self.adapter["adapter_id"], "model": model,
                    "request": {"model": model, "n": count, "size": image_size,
                                "max_images_per_request": request_limit},
                    "provider_response_id": response_ids[0] if len(response_ids) == 1 else None,
                    "provider_response_ids": response_ids}
        return candidates, metadata

    def edit(self, prompt: str, reference_paths: list[Path], count: int,
             output_dir: Path, size: str | None = None) -> tuple[list[dict], dict]:
        if not reference_paths or any(not path.is_file() for path in reference_paths):
            raise ValueError("reference_edit requires existing reference files")
        if not isinstance(count, int) or count < 1 or count > 8:
            raise ValueError("candidate count must be 1-8")
        base, token, model = self.configuration(reference_edit=True)
        request_limit = self.adapter.get("max_edits_per_request", count)
        if not isinstance(request_limit, int) or request_limit < 1:
            raise ValueError("max_edits_per_request must be a positive integer")
        image_size = size or self.adapter.get("default_size", "1024x1536")
        output_dir.mkdir(parents=True, exist_ok=True)
        candidates = []
        response_ids = []
        while len(candidates) < count:
            request_count = min(request_limit, count - len(candidates))
            boundary = "----shotdesigner-" + uuid.uuid4().hex
            fields = {"model": model, "prompt": prompt, "n": str(request_count),
                      "size": image_size}
            body = bytearray()
            for name, value in fields.items():
                body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
            for reference_path in reference_paths:
                body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{reference_path.name}\"\r\nContent-Type: image/png\r\n\r\n".encode())
                body.extend(reference_path.read_bytes())
                body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode())
            request = Request(
                base + self.adapter["edit_endpoint"], data=bytes(body),
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
            try:
                with urlopen(request, timeout=180) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                message = http_error_message(exc)
                exc.close()
                raise RuntimeError(f"image edit request failed: {message}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"image edit request failed: {exc}") from exc
            items = result.get("data") if isinstance(result, dict) else None
            if not isinstance(items, list) or not items:
                raise RuntimeError("image edit response contains no data items")
            if len(items) > request_count:
                raise RuntimeError("image edit response contains more items than requested")
            response_ids.append(result.get("id") if isinstance(result, dict) else None)
            for item in items:
                index = len(candidates) + 1
                path = output_dir / f"candidate-{index:02d}.png"
                if item.get("b64_json"):
                    path.write_bytes(base64.b64decode(item["b64_json"], validate=True))
                    source = "base64"
                elif item.get("url"):
                    with urlopen(item["url"], timeout=180) as response:
                        path.write_bytes(response.read())
                    source = item["url"]
                else:
                    raise RuntimeError(f"image result {index} lacks url or b64_json")
                candidates.append({"candidate_id": f"candidate-{index:02d}",
                                   "path": str(path), "source": source})
        metadata = {"adapter_id": self.adapter["adapter_id"], "model": model,
                    "operation": "reference_edit", "reference_count": len(reference_paths),
                    "request": {"model": model, "n": count, "size": image_size,
                                "max_edits_per_request": request_limit},
                    "provider_response_id": response_ids[0] if len(response_ids) == 1 else None,
                    "provider_response_ids": response_ids}
        return candidates, metadata
