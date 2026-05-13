from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .cache import VlmCache
from .validation import build_mock_vlm_frame_response, validate_vlm_frame_response, validate_vlm_request


DEFAULT_BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"


class VlmProviderError(RuntimeError):
    pass


class MockVlmAdapter:
    """Deterministic adapter for testing the VLM contract without model calls."""

    provider_id = "mock"
    model_id = "mock-vlm"

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache = VlmCache(cache_dir) if cache_dir is not None else None

    def label_frame(self, request: dict[str, Any], *, image_bytes: bytes = b"") -> dict[str, Any]:
        validate_vlm_request(request)
        if self.cache is not None:
            cached = self.cache.get(request, image_bytes=image_bytes)
            if cached is not None:
                return cached

        response = build_mock_vlm_frame_response(request)
        validate_vlm_frame_response(response, allowed_actions=request.get("allowed_actions", []))
        if self.cache is not None:
            self.cache.set(request, response, image_bytes=image_bytes)
        return response


class BedrockClaudeAdapter:
    """AWS Bedrock Claude adapter for schema-bound frame labeling."""

    provider_id = "bedrock"

    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        client: Any | None = None,
        model_id: str | None = None,
        region_name: str | None = None,
        play_card_text: str = "",
        max_tokens: int = 1800,
        temperature: float = 0.0,
    ) -> None:
        self.cache = VlmCache(cache_dir) if cache_dir is not None else None
        self.model_id = model_id or os.environ.get("MAKER_V1_BEDROCK_MODEL_ID") or DEFAULT_BEDROCK_MODEL_ID
        self.region_name = (
            region_name
            or os.environ.get("MAKER_V1_BEDROCK_REGION")
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
        )
        self.play_card_text = _clip_text(play_card_text, max_chars=8000)
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.client = client if client is not None else self._build_client()

    def label_frame(self, request: dict[str, Any], *, image_bytes: bytes = b"") -> dict[str, Any]:
        validate_vlm_request(request)
        image_format = _detect_image_format(image_bytes)
        if image_format is None:
            raise VlmProviderError(
                "Bedrock VLM labeling requires image bytes in PNG, JPEG, GIF, or WebP format. "
                "Raw observations must be decoded into image fixtures before using --vlm-provider bedrock. "
                "Use the generated agent/perception/decoder_spec.json and "
                "agent/perception/DECODER_GENERATION_TASK.md to build the game-specific decoder."
            )

        if self.cache is not None:
            cached = self.cache.get(request, image_bytes=image_bytes)
            if cached is not None:
                return cached

        response_text = self._call_bedrock(request, image_bytes=image_bytes, image_format=image_format)
        payload = _parse_json_object(response_text)
        validate_vlm_frame_response(payload, allowed_actions=request.get("allowed_actions", []))
        if self.cache is not None:
            self.cache.set(request, payload, image_bytes=image_bytes)
        return payload

    def _build_client(self) -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise VlmProviderError(
                "boto3 is required for --vlm-provider bedrock. Install project dependencies with uv first."
            ) from exc

        session = boto3.Session()
        kwargs: dict[str, str] = {}
        if self.region_name:
            kwargs["region_name"] = self.region_name
        return session.client("bedrock-runtime", **kwargs)

    def _call_bedrock(
        self,
        request: dict[str, Any],
        *,
        image_bytes: bytes,
        image_format: str,
    ) -> str:
        try:
            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": _SYSTEM_PROMPT}],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"text": _build_user_prompt(request, self.play_card_text)},
                            {"image": {"format": image_format, "source": {"bytes": image_bytes}}},
                        ],
                    }
                ],
                inferenceConfig={
                    "maxTokens": self.max_tokens,
                    "temperature": self.temperature,
                },
            )
        except Exception as exc:
            raise VlmProviderError(f"Bedrock Converse call failed for model {self.model_id!r}: {exc}") from exc
        return _extract_converse_text(response)


_SYSTEM_PROMPT = """You are a schema-bound visual labeler for game-agent development.
Return exactly one JSON object. Do not include markdown, commentary, or fields outside the requested schema."""


def _build_user_prompt(request: dict[str, Any], play_card_text: str) -> str:
    context = play_card_text if play_card_text else "No play card text was provided."
    request_context = {
        "request_id": request["request_id"],
        "frame_id": request["frame_id"],
        "objective": request["objective"],
        "allowed_views": request["allowed_views"],
        "allowed_actions": request["allowed_actions"],
        "recent_history": request["recent_history"],
        "parser_summary": request["parser_summary"],
        "retrieved_context_ids": request["retrieved_context_ids"],
    }
    fallback = _fallback_action(request["allowed_actions"])
    return (
        "Label the attached game frame for an agent-building pipeline.\n\n"
        "Guide context:\n"
        f"{context}\n\n"
        "Request context:\n"
        f"{json.dumps(request_context, indent=2, sort_keys=True)}\n\n"
        "Return JSON with exactly this top-level schema:\n"
        "{\n"
        '  "schema_version": "maker.vlm_frame.v1",\n'
        '  "request_id": string,\n'
        '  "frame_id": string,\n'
        '  "view": {"id": string, "confidence": number, "evidence": [string]},\n'
        '  "phase": {"id": string, "confidence": number, "evidence": [string]},\n'
        '  "visible_text": [{"text": string, "region": {"x": int, "y": int, "w": int, "h": int}, "confidence": number}],\n'
        '  "ui_elements": [{"kind": "button|menu|cursor|timer|score|chat|label|unknown", "label": string, "region": {"x": int, "y": int, "w": int, "h": int}, "state": "active|inactive|selected|disabled|unknown", "confidence": number}],\n'
        '  "entities": [{"kind": "self|player|opponent|item|body|hazard|objective|unknown", "label": string, "region": {"x": int, "y": int, "w": int, "h": int}, "attributes": object, "confidence": number}],\n'
        '  "state_observations": [{"key": string, "value": string|number|boolean|null, "status": "observed|inferred|guide_prior", "confidence": number, "evidence": [string]}],\n'
        '  "available_actions": [{"action_id": string, "confidence": number, "evidence": [string]}],\n'
        '  "recommended_action": {"action_id": string, "parameters": object, "confidence": number, "rationale": string, "fallback_action_id": string},\n'
        '  "novelty": {"status": "known|variant|new|uncertain", "save_frame": boolean, "reason": string},\n'
        '  "parser_targets": [{"target": string, "why": string, "suggested_test": string}],\n'
        '  "memory_updates": [{"key": string, "value": string|number|boolean|null, "status": "candidate", "confidence": number, "evidence": [string]}],\n'
        '  "uncertainty": [{"field": string, "reason": string, "needed_next": string}]\n'
        "}\n\n"
        f'Use request_id "{request["request_id"]}" and frame_id "{request["frame_id"]}". '
        "Use only allowed action ids for available_actions and recommended_action.action_id. "
        f'If unsure, set recommended_action.action_id and fallback_action_id to "{fallback}". '
        "Use integer zero regions when no precise region is visible. "
        "Use confidence values between 0.0 and 1.0."
    )


def _extract_converse_text(response: dict[str, Any]) -> str:
    content = response.get("output", {}).get("message", {}).get("content", [])
    texts = [block["text"] for block in content if isinstance(block, dict) and isinstance(block.get("text"), str)]
    if not texts:
        raise VlmProviderError("Bedrock Converse response did not contain text output")
    return "\n".join(texts)


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise VlmProviderError("Bedrock response did not contain a JSON object")
    candidate = stripped[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        preview = candidate[:500].replace("\n", " ")
        raise VlmProviderError(f"Bedrock response was not valid JSON: {preview}") from exc
    if not isinstance(payload, dict):
        raise VlmProviderError("Bedrock response JSON must be an object")
    return payload


def _detect_image_format(image_bytes: bytes) -> str | None:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "webp"
    return None


def _clip_text(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n[truncated]"


def _fallback_action(actions: list[str]) -> str:
    for candidate in ("noop", "stay", "wait"):
        if candidate in actions:
            return candidate
    return actions[0] if actions else "unknown"
