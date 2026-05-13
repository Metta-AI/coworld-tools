from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .action_control import validate_recommended_action
from .vlm import (
    BedrockClaudeAdapter,
    MockVlmAdapter,
    VlmProviderError,
    validate_vlm_frame_response,
    validate_vlm_request,
)


class BootstrapError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    run_id: str
    provider: str
    budget: int
    frames_seen: int
    labels_written: int
    report_file: Path


def run_visual_bootstrap(
    *,
    output_dir: Path,
    frames_dir: Path,
    budget: int,
    provider: str = "mock",
    decode_observations: bool = False,
) -> BootstrapResult:
    output_path = output_dir.expanduser().resolve()
    frame_source = frames_dir.expanduser().resolve()
    if not frame_source.exists() or not frame_source.is_dir():
        raise BootstrapError(f"frames_dir must be an existing directory: {frame_source}")
    if budget < 1:
        raise BootstrapError("vlm budget must be a positive integer")

    manifest = _load_manifest(output_path)
    surface = manifest.get("observation_surface", {})
    if isinstance(surface, dict) and surface.get("category") == "symbolic_primary":
        raise BootstrapError("visual bootstrap is only for visual_primary or mixed_or_alternate outputs")

    adapter = _build_adapter(provider, output_path)
    allowed_actions = _candidate_action_ids(manifest)
    fallback = _fallback_action(allowed_actions)
    run_id = datetime.now(UTC).strftime("bootstrap_%Y%m%dT%H%M%SZ")
    play_card_hash = _file_hash(output_path / "visual_bootstrap" / "play_card.md")
    labels_dir = output_path / "visual_bootstrap" / "labels"
    stored_frames_dir = output_path / "visual_bootstrap" / "frames"
    decoded_frames_dir = output_path / "visual_bootstrap" / "decoded_frames"
    runs_dir = output_path / "visual_bootstrap" / "runs"
    labels_dir.mkdir(parents=True, exist_ok=True)
    stored_frames_dir.mkdir(parents=True, exist_ok=True)
    if decode_observations:
        decoded_frames_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    decoder = _load_generated_decoder(output_path) if decode_observations else None
    for frame_path in _iter_frame_files(frame_source):
        if len(records) >= budget:
            break
        source_payload = frame_path.read_bytes()
        source_hash = hashlib.sha256(source_payload).hexdigest()
        decoder_metadata: dict[str, Any] = {}
        if decoder is not None:
            payload, image_format, decoder_metadata = _decode_to_vlm_image(decoder, source_payload)
            frame_hash = hashlib.sha256(payload).hexdigest()
            stored_frame = decoded_frames_dir / f"{frame_hash}.{image_format}"
        else:
            payload = source_payload
            frame_hash = hashlib.sha256(payload).hexdigest()
            stored_frame = stored_frames_dir / f"{frame_hash}{_suffix_for(frame_path)}"
        stored_frame.write_bytes(payload)
        request = _build_request(
            manifest=manifest,
            run_id=run_id,
            frame_id=frame_hash,
            frame_hash=frame_hash,
            play_card_hash=play_card_hash,
            allowed_actions=allowed_actions,
        )
        validate_vlm_request(request)
        try:
            response = adapter.label_frame(request, image_bytes=payload)
        except VlmProviderError as exc:
            raise BootstrapError(str(exc)) from exc
        validate_vlm_frame_response(response, allowed_actions=allowed_actions)
        action_validation = validate_recommended_action(
            response,
            allowed_actions=allowed_actions,
            fallback_action_id=fallback,
        )
        label_payload = {
            "schema_version": "maker.visual_label.v1",
            "run_id": run_id,
            "source_frame": str(frame_path),
            "source_observation_hash": source_hash,
            "stored_frame": str(stored_frame.relative_to(output_path)),
            "decoder_metadata": decoder_metadata,
            "request": request,
            "response": response,
            "action_validation": action_validation.as_dict(),
        }
        label_file = labels_dir / f"{request['request_id']}.json"
        label_file.write_text(json.dumps(label_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        records.append(
            {
                "source_frame": str(frame_path),
                "source_observation_hash": source_hash,
                "stored_frame": str(stored_frame.relative_to(output_path)),
                "label_file": str(label_file.relative_to(output_path)),
                "recommended_action": action_validation.action_id,
                "valid_action": action_validation.valid,
                "decoded_observation": decoder is not None,
            }
        )

    report = {
        "schema_version": "maker.visual_bootstrap_run.v1",
        "run_id": run_id,
        "provider": provider,
        "budget": budget,
        "decode_observations": decode_observations,
        "frames_seen": len(list(_iter_frame_files(frame_source))),
        "labels_written": len(records),
        "output_dir": str(output_path),
        "frames_dir": str(frame_source),
        "records": records,
    }
    report_file = runs_dir / f"{run_id}.json"
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return BootstrapResult(
        run_id=run_id,
        provider=provider,
        budget=budget,
        frames_seen=report["frames_seen"],
        labels_written=len(records),
        report_file=report_file,
    )


def _load_manifest(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "maker_manifest.json"
    if not path.exists():
        raise BootstrapError(f"maker manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BootstrapError(f"maker manifest must be a JSON object: {path}")
    return payload


def _build_adapter(provider: str, output_path: Path) -> MockVlmAdapter | BedrockClaudeAdapter:
    normalized = provider.strip().lower()
    cache_dir = output_path / "visual_bootstrap" / "cache" / normalized
    if normalized == "mock":
        return MockVlmAdapter(cache_dir)
    if normalized == "bedrock":
        return BedrockClaudeAdapter(
            cache_dir,
            play_card_text=_read_text(output_path / "visual_bootstrap" / "play_card.md"),
        )
    if normalized == "openai":
        raise BootstrapError(
            "OPENAI_API_KEY will be required for --vlm-provider openai, "
            "but that adapter is not implemented yet"
        )
    if normalized == "anthropic":
        raise BootstrapError(
            "ANTHROPIC_API_KEY will be required for --vlm-provider anthropic, "
            "but that adapter is not implemented yet"
        )
    raise BootstrapError(f"unsupported VLM provider: {provider}")


def _candidate_action_ids(manifest: dict[str, Any]) -> list[str]:
    actions = manifest.get("candidate_actions", [])
    if not isinstance(actions, list):
        return []
    action_ids = []
    for action in actions:
        if isinstance(action, dict) and isinstance(action.get("action_id"), str):
            action_ids.append(action["action_id"])
    return action_ids


def _fallback_action(actions: list[str]) -> str:
    for candidate in ("noop", "stay", "wait"):
        if candidate in actions:
            return candidate
    return actions[0] if actions else "unknown"


def _file_hash(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _load_generated_decoder(output_dir: Path) -> Any:
    path = output_dir / "agent" / "perception" / "decoder.py"
    if not path.exists():
        raise BootstrapError(f"generated decoder not found: {path}")
    module_name = f"_maker_generated_decoder_{hashlib.sha256(str(path).encode('utf-8')).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise BootstrapError(f"could not load generated decoder: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _decode_to_vlm_image(decoder: Any, payload: bytes) -> tuple[bytes, str, dict[str, Any]]:
    try:
        image_bytes, image_format, metadata = decoder.decode_to_vlm_image(payload)
    except Exception as exc:
        raise BootstrapError(f"generated decoder failed before VLM labeling: {exc}") from exc
    if not isinstance(image_bytes, bytes):
        raise BootstrapError("generated decoder returned non-bytes image payload")
    if image_format not in {"png", "jpeg", "gif", "webp"}:
        raise BootstrapError(f"generated decoder returned unsupported image format: {image_format!r}")
    if not isinstance(metadata, dict):
        raise BootstrapError("generated decoder returned non-object metadata")
    return image_bytes, image_format, metadata


def _build_request(
    *,
    manifest: dict[str, Any],
    run_id: str,
    frame_id: str,
    frame_hash: str,
    play_card_hash: str,
    allowed_actions: list[str],
) -> dict[str, Any]:
    guide_hash = str(manifest.get("guide_bundle_hash", "unknown"))
    seed = f"{guide_hash}:{play_card_hash}:{frame_id}:classify_current_frame"
    return {
        "schema_version": "maker.vlm_request.v1",
        "request_id": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
        "guide_bundle_hash": guide_hash,
        "play_card_hash": play_card_hash,
        "frame_id": frame_id,
        "frame_hash": frame_hash,
        "run_id": run_id,
        "objective": "classify_current_frame",
        "allowed_views": ["unknown"],
        "allowed_actions": allowed_actions,
        "recent_history": [],
        "parser_summary": {},
        "retrieved_context_ids": [],
    }


def _iter_frame_files(frames_dir: Path) -> list[Path]:
    return sorted(path for path in frames_dir.iterdir() if path.is_file() and not path.name.startswith("."))


def _suffix_for(path: Path) -> str:
    return path.suffix if path.suffix else ".bin"
