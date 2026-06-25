from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .documents import all_documents
from .framework import AgentFrameworkRef
from .sidecar import merge_sidecars


GUIDE_CONTRACT_FILENAME = "guide_contract.json"
GUIDE_CONTRACT_SCHEMA_VERSION = "guide.contract.v1"

CORE_CONTRACT_DOCUMENTS: tuple[str, ...] = (
    "GAME_OVERVIEW.md",
    "INTERFACE_CONTRACT.md",
    "OBSERVATION_DECODING.md",
    "ACTION_SEMANTICS_AND_CONTROL.md",
    "STATE_AND_VIEW_MODEL.md",
    "CONNECTION_AND_EPISODE_LIFECYCLE.md",
    "MINIMUM_VIABLE_AGENT.md",
)


def write_guide_contract(
    output_dir: Path,
    *,
    game_source: Path | None = None,
    agent_framework: AgentFrameworkRef | None = None,
) -> Path:
    output_path = output_dir.expanduser().resolve()
    contract = build_guide_contract(
        output_path,
        game_source=game_source,
        agent_framework=agent_framework,
    )
    contract_file = output_path / GUIDE_CONTRACT_FILENAME
    contract_file.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return contract_file


def build_guide_contract(
    output_dir: Path,
    *,
    game_source: Path | None = None,
    agent_framework: AgentFrameworkRef | None = None,
) -> dict[str, Any]:
    output_path = output_dir.expanduser().resolve()
    documents = _load_documents(output_path)
    evidence = _EvidenceCollector(documents)
    observation = _build_observation_contract(evidence)
    actions = _build_action_contract(evidence)
    runtime = _build_runtime_contract(evidence)

    prose_contract = {
        "schema_version": GUIDE_CONTRACT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "game_slug": _slug_from_output_dir(output_path),
        "guide_dir": str(output_path),
        "game_source": None if game_source is None else str(game_source.expanduser().resolve()),
        "agent_framework": None if agent_framework is None else agent_framework.as_contract(),
        "document_hash": _hash_documents(documents),
        "documents_present": sorted(documents),
        "documents_missing": [filename for filename in CORE_CONTRACT_DOCUMENTS if filename not in documents],
        "all_guide_documents_missing": [
            document.filename for document in all_documents() if document.filename not in documents
        ],
        "observation": observation,
        "actions": actions,
        "runtime": runtime,
    }
    return merge_sidecars(prose_contract, output_path)


def _load_documents(output_dir: Path) -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(output_dir.glob("*.md"))
        if path.is_file()
    }


def _build_observation_contract(evidence: _EvidenceCollector) -> dict[str, Any]:
    visual_evidence = [
        item
        for item in evidence.find(
            ("INTERFACE_CONTRACT.md", "OBSERVATION_DECODING.md", "MINIMUM_VIABLE_AGENT.md"),
            (
                r"\bframe ?buffer\b",
                r"\bpixels?\b",
                r"\bimage\b",
                r"\bpacked\b",
                r"\bscreenshot\b",
                r"\bpalette\b",
                r"\bsprite\b",
                r"\b\d{2,5}\s*[xX×]\s*\d{2,5}\b",
                r"\b\d[\d,]*\s+bytes?\b",
            ),
            include_context=True,
        )
        if not _is_negated_visual_claim(str(item["text"]))
        and not _is_negated_visual_claim(str(item.get("context", "")))
    ]
    visual_evidence = [_without_context(item) for item in visual_evidence]
    symbolic_evidence = evidence.find(
        ("INTERFACE_CONTRACT.md", "OBSERVATION_DECODING.md", "MINIMUM_VIABLE_AGENT.md"),
        (
            r"\bjson\b",
            r"\bstructured\b",
            r"\bfields?\b",
            r"\btoken\b",
            r"\barray\b",
            r"\bsymbolic\b",
        ),
    )
    alternate_evidence = evidence.find(
        ("INTERFACE_CONTRACT.md", "OBSERVATION_DECODING.md"),
        (r"\balternate\b", r"\balternative\b", r"\bside channel\b", r"\bsprite_player\b"),
    )
    visual_score = _score_observation_evidence(visual_evidence)
    symbolic_score = _score_observation_evidence(symbolic_evidence)

    if visual_score >= 2 and symbolic_score >= 2:
        surface = "mixed_or_alternate"
        confidence = 0.8 if alternate_evidence else 0.7
    elif visual_score >= 2:
        surface = "visual_primary"
        confidence = min(0.9, 0.55 + visual_score / 20)
    elif symbolic_score >= 2:
        surface = "symbolic_primary"
        confidence = min(0.9, 0.55 + symbolic_score / 20)
    else:
        surface = "unknown"
        confidence = 0.2

    combined = _dedupe_evidence([*visual_evidence, *symbolic_evidence, *alternate_evidence])
    hints = _extract_observation_hints(combined)
    primary = {
        "channel": _first_endpoint(combined, default="/player"),
        "transport": _transport_from_evidence(combined),
        "input_kind": _input_kind_from_surface_and_hints(surface, hints),
        "encoding": _encoding_from_hints(hints),
        "width": hints["width"],
        "height": hints["height"],
        "byte_length": hints["byte_length"],
        "bit_depth": hints["bit_depth"],
        "evidence": combined[:20],
    }
    alternates = [
        {
            "channel": "/sprite_player",
            "description": "alternate playable sprite protocol",
            "evidence": alternate_evidence[:5],
        }
    ] if any("/sprite_player" in item["text"] for item in alternate_evidence) else []

    return {
        "surface_category": surface,
        "confidence": round(confidence, 2),
        "visual_score": round(visual_score, 2),
        "symbolic_score": round(symbolic_score, 2),
        "primary": primary,
        "alternates": alternates,
    }


def _build_action_contract(evidence: _EvidenceCollector) -> dict[str, Any]:
    action_evidence = evidence.find(
        ("INTERFACE_CONTRACT.md", "ACTION_SEMANTICS_AND_CONTROL.md", "MINIMUM_VIABLE_AGENT.md"),
        (
            r"\baction\b",
            r"\bactions\b",
            r"\bbutton\b",
            r"\bbutton[a-z]+\b",
            r"\binput\b",
            r"\bmask\b",
            r"\bmove\b",
            r"\bvalid values\b",
            r"\baction_names\b",
        ),
        include_continuations=True,
    )
    action_ids = _extract_action_ids(action_evidence)
    style = "unknown"
    requires_message_type = False
    payload_prefix: list[int] = []
    payloads: dict[str, int] = {}
    default_action = _select_default_action(tuple(action_ids))

    if _has_any(action_evidence, (r"\[0x00,\s*mask\]", r"2-byte binary", r"input bitmask", r"button mask")):
        payloads = _extract_button_payloads(action_evidence, tuple(action_ids))
        if payloads:
            style = "binary_button_mask"
            requires_message_type = True
            payload_prefix = [0]
            default_action = "noop"
    elif _has_any(action_evidence, (r'"move"', r"`move`", r"\bmove\b.*valid values")):
        style = "move_json"
    elif _has_any(action_evidence, (r'"action_name"', r"\baction_name\b")):
        style = "action_name_json"
        requires_message_type = True
    elif _has_any(action_evidence, (r'"action_index"', r"\baction_index\b")):
        style = "action_index_json"
        requires_message_type = True

    candidates = [
        {
            "action_id": action_id,
            "source": "guide_contract",
            "evidence": _evidence_for_action(action_id, action_evidence)[:5],
        }
        for action_id in action_ids
    ]

    return {
        "style": style,
        "default_action": default_action,
        "requires_message_type": requires_message_type,
        "payload_prefix": payload_prefix,
        "payloads": payloads,
        "candidates": candidates,
        "evidence": action_evidence[:30],
    }


def _build_runtime_contract(evidence: _EvidenceCollector) -> dict[str, Any]:
    runtime_evidence = evidence.find(
        ("CONNECTION_AND_EPISODE_LIFECYCLE.md", "INTERFACE_CONTRACT.md", "TRAINING_AND_EVALUATION.md"),
        (
            r"\bwebsocket\b",
            r"\bendpoint\b",
            r"\bconnect\b",
            r"\blobby\b",
            r"\bepisode\b",
            r"\btick\b",
            r"\bfps\b",
            r"\breset\b",
            r"\bdisconnect\b",
        ),
    )
    endpoints = [
        {
            "path": path,
            "transport": _transport_for_endpoint(path, runtime_evidence),
            "evidence": [item for item in runtime_evidence if path in item["text"]][:5],
        }
        for path in _extract_endpoint_paths(runtime_evidence)
    ]
    return {
        "endpoints": endpoints,
        "tick_rate_hz": _extract_tick_rate(runtime_evidence),
        "notes": runtime_evidence[:20],
    }


def _score_observation_evidence(items: list[dict[str, Any]]) -> float:
    score = 0.0
    for item in items:
        text = str(item["text"]).lower()
        if re.search(r"\bframe ?buffer\b|\bpacked\b|\bpixels?\b", text):
            score += 2.0
        elif re.search(r"\bjson\b|\bstructured\b|\bfields?\b|\btoken\b", text):
            score += 1.5
        else:
            score += 1.0
    return score


def _is_negated_visual_claim(line: str) -> bool:
    lowered = line.lower()
    visual_terms = r"(binary|frame ?buffer|framebuffer|pixel|pixels|screenshot|image|canvas|packed|raw)"
    if re.search(rf"\b(no|without)\b[^.]*\b{visual_terms}\b", lowered):
        return True
    if re.search(rf"\bthere is no\b[^.]*\b{visual_terms}\b", lowered):
        return True
    if re.search(rf"\bnot\b[^.]*\b{visual_terms}\b[^.]*\b(player|observation|payload|message|contract)\b", lowered):
        return True
    if "no binary" in lowered or "no frame buffer" in lowered or "no framebuffer" in lowered:
        return True
    if "not included" in lowered and any(term in lowered for term in ("pixel", "frame", "image", "canvas")):
        return True
    return False


def _extract_observation_hints(items: list[dict[str, Any]]) -> dict[str, int | None]:
    text = "\n".join(str(item["text"]) for item in items)
    dimensions = re.search(r"\b(\d{2,5})\s*[xX×]\s*(\d{2,5})\b", text)
    byte_length = re.search(r"\b(\d[\d,]*)\s+bytes?\b", text, flags=re.I)
    bit_depth = re.search(r"\b(\d+)\s*[- ]?bit\b", text, flags=re.I)
    return {
        "width": int(dimensions.group(1)) if dimensions else None,
        "height": int(dimensions.group(2)) if dimensions else None,
        "byte_length": int(byte_length.group(1).replace(",", "")) if byte_length else None,
        "bit_depth": int(bit_depth.group(1)) if bit_depth else None,
    }


def _transport_from_evidence(items: list[dict[str, Any]]) -> str:
    text = "\n".join(str(item["text"]).lower() for item in items)
    if "websocket" in text and "binary" in text:
        return "websocket_binary"
    if "websocket" in text and "json" in text:
        return "websocket_json"
    if "websocket" in text:
        return "websocket"
    if "json" in text:
        return "json"
    return "unknown"


def _input_kind_from_surface_and_hints(surface: str, hints: dict[str, int | None]) -> str:
    if surface == "symbolic_primary":
        return "structured_symbolic"
    if hints["byte_length"] is not None or hints["width"] is not None or hints["bit_depth"] is not None:
        return "raw_visual_observation"
    if surface in {"visual_primary", "mixed_or_alternate"}:
        return "visual_unknown_encoding"
    return "unknown"


def _encoding_from_hints(hints: dict[str, int | None]) -> str:
    if hints["bit_depth"] == 4 and hints["byte_length"] is not None:
        return "packed_4bit_framebuffer"
    if hints["byte_length"] is not None:
        return "raw_binary"
    return "unknown"


def _first_endpoint(items: list[dict[str, Any]], *, default: str) -> str:
    paths = _extract_endpoint_paths(items)
    return paths[0] if paths else default


def _extract_endpoint_paths(items: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for item in items:
        for path in re.findall(r"`(/[-_a-zA-Z0-9]+)`|(?<!\w)(/[-_a-zA-Z0-9]+)(?!\w)", str(item["text"])):
            value = path[0] or path[1]
            if value not in paths:
                paths.append(value)
    return paths


def _transport_for_endpoint(path: str, items: list[dict[str, Any]]) -> str:
    path_segments = [
        segment
        for item in items
        for segment in re.split(r"(?<=[.!?])\s+", str(item["text"]))
        if path in segment
    ]
    path_items = [{"text": segment} for segment in path_segments]
    path_text = "\n".join(segment.lower() for segment in path_segments)
    websocket_negated = re.search(r"\bnot\b[^.]*\bwebsocket\b", path_text) is not None
    if re.search(r"\bhttp\b|\bget\b|\bpost\b|\bput\b|\bdelete\b|\bresponse\b|\bjson response\b", path_text):
        return "http"
    if not websocket_negated and re.search(r"\bwebsocket\b|\bws://|\bwss://|\bwebsocketroute\b", path_text):
        return "websocket"
    if path == "/player" and _has_any(path_items, (r"\bconnect\b", r"\bslot\b", r"\btoken\b")):
        return "websocket"
    return "unknown"


def _extract_tick_rate(items: list[dict[str, Any]]) -> int | None:
    text = "\n".join(str(item["text"]) for item in items)
    match = re.search(r"\b(\d{1,3})\s*(?:fps|hz|ticks? per second)\b", text, flags=re.I)
    return int(match.group(1)) if match else None


def _extract_action_ids(items: list[dict[str, Any]]) -> list[str]:
    candidates: dict[str, None] = {}
    for item in items:
        text = str(item["text"])
        for token in re.findall(r"`([^`]+)`|\"([A-Za-z][A-Za-z0-9_-]{0,48})\"", text):
            for raw in token:
                action = _normalize_action_token(raw)
                if action is not None:
                    candidates[action] = None
        for known in _KNOWN_ACTION_TERMS:
            if re.search(rf"\b{re.escape(known)}\b", text, flags=re.I):
                candidates[known] = None
        parsed = _parse_button_mask_table_row(text)
        if parsed is not None:
            candidates[parsed[0]] = None
    return sorted(candidates)


def _extract_button_payloads(items: list[dict[str, Any]], action_ids: tuple[str, ...]) -> dict[str, int]:
    action_set = set(action_ids)
    masks: dict[str, int] = {}
    for item in items:
        parsed = _parse_button_mask_table_row(str(item["text"]))
        if parsed is None:
            continue
        action_id, mask = parsed
        if action_id in action_set:
            masks[action_id] = mask

    if not masks:
        return {}

    masks["noop"] = 0
    if "attack" in masks:
        for alias in ("report", "vote", "a"):
            if alias in action_set:
                masks[alias] = masks["attack"]
    if "b" in masks and "vent" in action_set:
        masks["vent"] = masks["b"]

    ordered = ("noop", *action_ids)
    return {action_id: masks[action_id] for action_id in ordered if action_id in masks}


def _parse_button_mask_table_row(line: str) -> tuple[str, int] | None:
    if "|" not in line:
        return None
    cells = [cell.strip().strip("`").strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) < 4:
        return None

    mask: int | None = None
    mask_index = -1
    for index, cell in enumerate(cells):
        hex_match = re.fullmatch(r"0x([0-9a-fA-F]{1,2})", cell)
        if hex_match is not None:
            mask = int(hex_match.group(1), 16)
            mask_index = index
            break
        if re.fullmatch(r"\d+", cell):
            bit = int(cell)
            if 0 <= bit <= 6:
                mask = 1 << bit
                mask_index = index
                break
    if mask is None or mask == 0xFF:
        return None

    preferred_cells = cells[mask_index + 2 :] if len(cells) > mask_index + 2 else cells[mask_index + 1 :]
    for cell in preferred_cells:
        button_action = _normalize_button_action_cell(cell)
        if button_action is not None:
            return button_action, mask
        token = _normalize_action_token(cell)
        if token is not None:
            return token, mask
    return None


def _normalize_button_action_cell(cell: str) -> str | None:
    normalized = re.sub(r"\s+", " ", cell.strip("`").strip().lower()).replace("_", "")
    return {
        "buttonup": "up",
        "buttondown": "down",
        "buttonleft": "left",
        "buttonright": "right",
        "buttonselect": "select",
        "buttona": "attack",
        "buttonb": "b",
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
        "select": "select",
        "a": "attack",
        "a (attack)": "attack",
    }.get(normalized)


def _evidence_for_action(action_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        if re.search(rf"\b{re.escape(action_id)}\b", str(item["text"]), flags=re.I):
            result.append(item)
    return result or items[:1]


def _has_any(items: list[dict[str, Any]], patterns: tuple[str, ...]) -> bool:
    text = "\n".join(str(item["text"]) for item in items)
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


def _normalize_action_token(token: str) -> str | None:
    normalized = token.strip().lower().replace("-", "_")
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    if normalized in _ACTION_STOPWORDS:
        return None
    if normalized in {"a", "buttona"}:
        return "attack"
    if normalized == "buttonb":
        return "b"
    if normalized.startswith("button"):
        normalized = normalized.removeprefix("button")
    if normalized in _BUTTON_DIRECTIONS:
        return normalized
    if len(normalized) < 2 and normalized not in _KNOWN_ACTION_TERMS:
        return None
    if normalized in _KNOWN_ACTION_TERMS:
        return normalized
    return None


def _select_default_action(action_ids: tuple[str, ...]) -> str:
    for action_id in ("noop", "stay", "wait", "up", "move_north"):
        if action_id in action_ids:
            return action_id
    return action_ids[0] if action_ids else "noop"


def _clean_line(line: str) -> str:
    return " ".join(line.strip().strip("|").split())


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = (str(item["document"]), int(item["line"]), str(item["text"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _without_context(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "context"}


def _slug_from_output_dir(path: Path) -> str:
    raw = path.name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return slug or "unknown_game"


def _hash_documents(documents: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for filename in sorted(documents):
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(documents[filename].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


class _EvidenceCollector:
    def __init__(self, documents: dict[str, str]) -> None:
        self._documents = documents

    def find(
        self,
        filenames: tuple[str, ...],
        patterns: tuple[str, ...],
        *,
        include_context: bool = False,
        include_continuations: bool = False,
    ) -> list[dict[str, Any]]:
        compiled = tuple(re.compile(pattern, re.I) for pattern in patterns)
        evidence: list[dict[str, Any]] = []
        for filename in filenames:
            content = self._documents.get(filename)
            if content is None:
                continue
            previous_cleaned = ""
            previous_matched = False
            for line_no, line in enumerate(content.splitlines(), start=1):
                if _is_low_signal_line(line):
                    continue
                cleaned = _clean_line(line)
                matched = any(pattern.search(cleaned) for pattern in compiled)
                continuation = (
                    include_continuations
                    and previous_matched
                    and bool(re.search(r"`[^`]+`|\"[A-Za-z][A-Za-z0-9_-]{0,48}\"", cleaned))
                )
                if matched or continuation:
                    item = {"document": filename, "line": line_no, "text": cleaned}
                    if include_context:
                        item["context"] = f"{previous_cleaned} {cleaned}".strip()
                    evidence.append(item)
                previous_cleaned = cleaned
                previous_matched = matched
        return _dedupe_evidence(evidence)


def _is_low_signal_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("```") or stripped.startswith("#"):
        return True
    if set(stripped) <= {"|", "-", ":", " "}:
        return True
    return False


_KNOWN_ACTION_TERMS = (
    "noop",
    "stay",
    "up",
    "down",
    "left",
    "right",
    "north",
    "south",
    "west",
    "east",
    "move_north",
    "move_south",
    "move_west",
    "move_east",
    "interact",
    "select",
    "attack",
    "report",
    "vote",
    "chat",
    "vent",
)

_BUTTON_DIRECTIONS = {"up", "down", "left", "right", "select"}

_ACTION_STOPWORDS = {
    "action",
    "actions",
    "agent",
    "binary",
    "button",
    "buttons",
    "byte",
    "client",
    "constant",
    "cursor",
    "field",
    "fields",
    "input",
    "json",
    "mask",
    "message",
    "packet",
    "phase",
    "player",
    "playing",
    "server",
    "type",
    "unused",
    "value",
    "voting",
}
