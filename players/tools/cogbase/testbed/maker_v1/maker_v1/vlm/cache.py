from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .validation import validate_vlm_frame_response, validate_vlm_request


class VlmCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def key_for(self, request: dict[str, Any], *, image_bytes: bytes = b"") -> str:
        validate_vlm_request(request)
        cache_request = dict(request)
        cache_request["run_id"] = "<ignored-for-cache>"
        digest = hashlib.sha256()
        digest.update(json.dumps(cache_request, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\0")
        digest.update(image_bytes)
        return digest.hexdigest()

    def get(self, request: dict[str, Any], *, image_bytes: bytes = b"") -> dict[str, Any] | None:
        path = self.path_for_key(self.key_for(request, image_bytes=image_bytes))
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return validate_vlm_frame_response(payload, allowed_actions=request.get("allowed_actions", []))

    def set(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
        *,
        image_bytes: bytes = b"",
    ) -> Path:
        validate_vlm_request(request)
        validate_vlm_frame_response(response, allowed_actions=request.get("allowed_actions", []))
        path = self.path_for_key(self.key_for(request, image_bytes=image_bytes))
        path.write_text(json.dumps(response, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def path_for_key(self, key: str) -> Path:
        return self.root / f"{key}.json"
