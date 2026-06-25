from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GUIDE_DOCUMENT_FILENAMES: tuple[str, ...] = (
    "README.md",
    "GAME_OVERVIEW.md",
    "RULES_AND_MECHANICS.md",
    "INTERFACE_CONTRACT.md",
    "STATE_AND_VIEW_MODEL.md",
    "CONNECTION_AND_EPISODE_LIFECYCLE.md",
    "TRAINING_AND_EVALUATION.md",
    "OBSERVATION_DECODING.md",
    "ACTION_SEMANTICS_AND_CONTROL.md",
    "MEMORY_AND_HIDDEN_INFORMATION.md",
    "REWARDS_AND_PROGRESS_SIGNALS.md",
    "MINIMUM_VIABLE_AGENT.md",
    "ERROR_RECOVERY_AND_ROBUSTNESS.md",
    "STRATEGY_AND_POLICY_GUIDE.md",
    "IMPLEMENTATION_NOTES.md",
)

CORE_DOCUMENT_FILENAMES: tuple[str, ...] = (
    "GAME_OVERVIEW.md",
    "INTERFACE_CONTRACT.md",
    "OBSERVATION_DECODING.md",
    "ACTION_SEMANTICS_AND_CONTROL.md",
    "STATE_AND_VIEW_MODEL.md",
    "CONNECTION_AND_EPISODE_LIFECYCLE.md",
    "MINIMUM_VIABLE_AGENT.md",
)

GUIDE_CONTRACT_SCHEMA_VERSION = "guide.contract.v1"


@dataclass(frozen=True, slots=True)
class Evidence:
    document: str
    line: int
    text: str

    def as_dict(self) -> dict[str, object]:
        return {
            "document": self.document,
            "line": self.line,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class GuideDocument:
    filename: str
    path: Path
    content: str

    @property
    def name(self) -> str:
        return self.filename.removesuffix(".md")


@dataclass(frozen=True, slots=True)
class GuideBundle:
    guide_dir: Path
    game_slug: str
    documents: dict[str, GuideDocument]
    missing_documents: tuple[str, ...]
    bundle_hash: str
    contract: dict[str, Any] | None
    contract_hash: str | None

    def get(self, filename: str) -> GuideDocument | None:
        return self.documents.get(filename)

    def content(self, filename: str) -> str:
        document = self.get(filename)
        return "" if document is None else document.content


@dataclass(frozen=True, slots=True)
class ObservationSurface:
    category: str
    confidence: float
    visual_score: float
    symbolic_score: float
    evidence: tuple[Evidence, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "visual_score": self.visual_score,
            "symbolic_score": self.symbolic_score,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    action_id: str
    source: str
    evidence: tuple[Evidence, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "source": self.source,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class ActionWireContract:
    style: str
    default_action: str
    requires_message_type: bool
    action_payloads: dict[str, int]
    evidence: tuple[Evidence, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "style": self.style,
            "default_action": self.default_action,
            "requires_message_type": self.requires_message_type,
            "action_payloads": dict(self.action_payloads),
            "evidence": [item.as_dict() for item in self.evidence],
        }


def load_guide_bundle(guide_dir: Path) -> GuideBundle:
    resolved = guide_dir.expanduser().resolve()
    documents: dict[str, GuideDocument] = {}

    for path in sorted(resolved.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        documents[path.name] = GuideDocument(path.name, path, content)

    contract, contract_hash = _load_guide_contract(resolved)
    missing = tuple(filename for filename in CORE_DOCUMENT_FILENAMES if filename not in documents)
    return GuideBundle(
        guide_dir=resolved,
        game_slug=_slug_from_guide_dir(resolved),
        documents=documents,
        missing_documents=missing,
        bundle_hash=_hash_documents(documents),
        contract=contract,
        contract_hash=contract_hash,
    )


def classify_observation_surface(bundle: GuideBundle) -> ObservationSurface:
    contract_surface = _observation_surface_from_contract(bundle)
    if contract_surface is not None:
        return contract_surface

    target_docs = (
        "INTERFACE_CONTRACT.md",
        "OBSERVATION_DECODING.md",
        "CONNECTION_AND_EPISODE_LIFECYCLE.md",
        "MINIMUM_VIABLE_AGENT.md",
    )
    visual_hits = _scan_patterns(bundle, target_docs, _VISUAL_PATTERNS)
    symbolic_hits = _scan_patterns(bundle, target_docs, _SYMBOLIC_PATTERNS)
    alternate_hits = _scan_patterns(bundle, target_docs, _ALTERNATE_PATTERNS)

    visual_score = _score_hits(visual_hits)
    symbolic_score = _score_hits(symbolic_hits)
    evidence = _dedupe_evidence([*visual_hits, *symbolic_hits, *alternate_hits])[:10]

    if symbolic_score >= 2.0 and symbolic_score >= visual_score * 3:
        category = "symbolic_primary"
        confidence = min(0.9, 0.6 + symbolic_score / 100.0)
    elif visual_score >= 2.0 and visual_score >= symbolic_score * 3:
        category = "visual_primary"
        confidence = min(0.9, 0.6 + visual_score / 100.0)
    elif visual_score >= 2.0 and symbolic_score >= 2.0:
        category = "mixed_or_alternate"
        confidence = 0.8 if alternate_hits else 0.7
    elif visual_score >= 2.0:
        category = "visual_primary"
        confidence = min(0.9, 0.55 + visual_score / 10.0)
    elif symbolic_score >= 2.0:
        category = "symbolic_primary"
        confidence = min(0.9, 0.55 + symbolic_score / 10.0)
    else:
        category = "unknown"
        confidence = 0.2

    return ObservationSurface(
        category=category,
        confidence=round(confidence, 2),
        visual_score=round(visual_score, 2),
        symbolic_score=round(symbolic_score, 2),
        evidence=tuple(evidence),
    )


def extract_action_candidates(bundle: GuideBundle) -> tuple[ActionCandidate, ...]:
    contract_actions = _action_candidates_from_contract(bundle)
    if contract_actions:
        return contract_actions

    explicit_actions = _extract_action_name_arrays(bundle)
    if len(explicit_actions) >= 2:
        return explicit_actions

    action_docs = (
        "INTERFACE_CONTRACT.md",
        "ACTION_SEMANTICS_AND_CONTROL.md",
        "MINIMUM_VIABLE_AGENT.md",
    )
    candidates: dict[str, list[Evidence]] = {}

    for filename in action_docs:
        document = bundle.get(filename)
        if document is None:
            continue
        for line_no, line in enumerate(document.content.splitlines(), start=1):
            lowered = line.lower()
            if not any(keyword in lowered for keyword in _ACTION_LINE_KEYWORDS):
                continue
            if _is_negative_action_claim(line):
                continue
            for raw_token in _extract_quoted_tokens(line):
                token = _normalize_action_token(raw_token)
                if token is None:
                    continue
                candidates.setdefault(token, []).append(Evidence(filename, line_no, _clean_line(line)))
            for known in _KNOWN_ACTION_TERMS:
                if re.search(rf"\b{re.escape(known)}\b", lowered):
                    candidates.setdefault(known, []).append(Evidence(filename, line_no, _clean_line(line)))

    return tuple(
        ActionCandidate(action_id=action_id, source="guide_text_heuristic", evidence=tuple(evidence[:3]))
        for action_id, evidence in sorted(candidates.items())
    )


def infer_action_wire_contract(
    bundle: GuideBundle,
    actions: tuple[ActionCandidate, ...],
) -> ActionWireContract:
    contract_wire = _action_wire_from_contract(bundle, actions)
    if contract_wire is not None:
        return contract_wire

    documents = (
        "INTERFACE_CONTRACT.md",
        "ACTION_SEMANTICS_AND_CONTROL.md",
        "MINIMUM_VIABLE_AGENT.md",
    )
    action_ids = tuple(action.action_id for action in actions)
    default_action = _select_default_action(action_ids)
    evidence: list[Evidence] = []

    if _find_contract_evidence(bundle, documents, (r'"action_name"', r"\baction_name\b"), evidence):
        return ActionWireContract(
            style="action_name_json",
            default_action=default_action,
            requires_message_type=True,
            action_payloads={},
            evidence=tuple(evidence[:5]),
        )

    evidence.clear()
    if _find_contract_evidence(bundle, documents, (r'"action_index"', r"\baction_index\b"), evidence):
        return ActionWireContract(
            style="action_index_json",
            default_action=default_action,
            requires_message_type=True,
            action_payloads={},
            evidence=tuple(evidence[:5]),
        )

    evidence.clear()
    if _find_contract_evidence(
        bundle,
        documents,
        (
            r'"move"',
            r"`move`\s*\|\s*string",
            r"message\[\s*\"move\"\s*\]",
            r"\bmove\b.*valid values",
        ),
        evidence,
    ):
        return ActionWireContract(
            style="move_json",
            default_action=default_action if default_action in action_ids else "stay",
            requires_message_type=False,
            action_payloads={},
            evidence=tuple(evidence[:5]),
        )

    evidence.clear()
    button_masks = _extract_button_mask_payloads(bundle, action_ids, evidence)
    if button_masks:
        return ActionWireContract(
            style="binary_button_mask",
            default_action="noop" if "noop" in button_masks else default_action,
            requires_message_type=True,
            action_payloads=button_masks,
            evidence=tuple(evidence[:8]),
        )

    return ActionWireContract(
        style="unknown_json",
        default_action=default_action,
        requires_message_type=False,
        action_payloads={},
        evidence=(),
    )


def _extract_action_name_arrays(bundle: GuideBundle) -> tuple[ActionCandidate, ...]:
    candidates: dict[str, list[Evidence]] = {}
    for filename in ("INTERFACE_CONTRACT.md", "ACTION_SEMANTICS_AND_CONTROL.md", "MINIMUM_VIABLE_AGENT.md"):
        document = bundle.get(filename)
        if document is None:
            continue
        for line_no, line in enumerate(document.content.splitlines(), start=1):
            if re.search(r"(?<!vibe_)action_names", line) is None or "[" not in line:
                continue
            for token in _extract_quoted_tokens(line):
                normalized = _normalize_action_token(token)
                if normalized is None:
                    continue
                candidates.setdefault(normalized, []).append(Evidence(filename, line_no, _clean_line(line)))

    return tuple(
        ActionCandidate(action_id=action_id, source="guide_action_names", evidence=tuple(evidence[:3]))
        for action_id, evidence in candidates.items()
    )


def extract_runtime_notes(bundle: GuideBundle, *, limit: int = 12) -> tuple[Evidence, ...]:
    contract_notes = _runtime_notes_from_contract(bundle, limit=limit)
    if contract_notes:
        return contract_notes

    runtime_docs = (
        "CONNECTION_AND_EPISODE_LIFECYCLE.md",
        "INTERFACE_CONTRACT.md",
        "TRAINING_AND_EVALUATION.md",
    )
    notes: list[Evidence] = []
    for filename in runtime_docs:
        document = bundle.get(filename)
        if document is None:
            continue
        for line_no, line in enumerate(document.content.splitlines(), start=1):
            if _is_low_signal_line(line):
                continue
            lowered = line.lower()
            if any(keyword in lowered for keyword in _RUNTIME_KEYWORDS):
                notes.append(Evidence(filename, line_no, _clean_line(line)))
                if len(notes) >= limit:
                    return tuple(notes)
    return tuple(notes)


def build_play_card(
    bundle: GuideBundle,
    surface: ObservationSurface,
    actions: tuple[ActionCandidate, ...],
    runtime_notes: tuple[Evidence, ...],
) -> str:
    title = _extract_game_title(bundle) or bundle.game_slug
    action_text = ", ".join(action.action_id for action in actions[:20]) or "unknown"
    hidden_rules = _extract_hidden_information_rules(bundle)
    observation_evidence = "\n".join(
        f"- {item.document}:{item.line}: {item.text}" for item in surface.evidence[:5]
    ) or "- No strong observation-surface evidence found."
    runtime_text = "\n".join(
        f"- {item.document}:{item.line}: {item.text}" for item in runtime_notes[:6]
    ) or "- No runtime notes extracted."
    hidden_text = "\n".join(f"- {item.text}" for item in hidden_rules) or "- Treat non-visible state as unknown unless the guide marks it as player-observable."

    return f"""# {title} maker_v1 Play Card

Generated from guide bundle: `{bundle.game_slug}`

## Observation Contract

- Surface: `{surface.category}`
- Confidence: `{surface.confidence}`
- Guide bundle hash: `{bundle.bundle_hash}`

Evidence:
{observation_evidence}

## Action Registry Candidates

{action_text}

## Runtime Notes

{runtime_text}

## Hidden Information Rules

{hidden_text}

## VLM Use

Use a VLM only for visual states that deterministic parsing cannot classify,
for novel frame labels, or for constrained action recommendations from the
candidate action list above. The VLM must not assert hidden state as fact, write
memory directly, invent actions, or bypass action validation.
"""


def _slug_from_guide_dir(path: Path) -> str:
    raw = path.name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return slug or "unknown_game"


def _hash_documents(documents: dict[str, GuideDocument]) -> str:
    digest = hashlib.sha256()
    for filename in sorted(documents):
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(documents[filename].content.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _load_guide_contract(guide_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    contract_file = guide_dir / "guide_contract.json"
    if not contract_file.exists():
        return None, None
    content = contract_file.read_text(encoding="utf-8")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid guide contract JSON: {contract_file}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"guide contract must be a JSON object: {contract_file}")
    schema_version = parsed.get("schema_version")
    if schema_version != GUIDE_CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported guide contract schema {schema_version!r}: {contract_file}"
        )
    return parsed, hashlib.sha256(content.encode("utf-8")).hexdigest()


def _observation_surface_from_contract(bundle: GuideBundle) -> ObservationSurface | None:
    observation = _contract_section(bundle, "observation")
    if observation is None:
        return None
    category = observation.get("surface_category")
    if category not in {"symbolic_primary", "visual_primary", "mixed_or_alternate", "unknown"}:
        return None
    return ObservationSurface(
        category=str(category),
        confidence=_float_contract_value(observation.get("confidence"), default=0.2),
        visual_score=_float_contract_value(observation.get("visual_score"), default=0.0),
        symbolic_score=_float_contract_value(observation.get("symbolic_score"), default=0.0),
        evidence=tuple(
            _contract_evidence(
                [
                    *(_contract_evidence_items(observation.get("primary"))),
                    *(_contract_evidence_items(observation)),
                ]
            )[:10]
        ),
    )


def _action_candidates_from_contract(bundle: GuideBundle) -> tuple[ActionCandidate, ...]:
    actions = _contract_section(bundle, "actions")
    if actions is None:
        return ()
    candidates = actions.get("candidates")
    if not isinstance(candidates, list):
        payloads = actions.get("payloads")
        if not isinstance(payloads, dict):
            return ()
        candidates = [{"action_id": key, "source": "guide_contract", "evidence": actions.get("evidence", [])} for key in payloads]

    result: list[ActionCandidate] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        action_id = _normalize_action_token(str(item.get("action_id", "")))
        if action_id is None or action_id in seen:
            continue
        seen.add(action_id)
        evidence = tuple(_contract_evidence(_contract_evidence_items(item))[:3])
        result.append(ActionCandidate(action_id=action_id, source="guide_contract", evidence=evidence))
    return tuple(sorted(result, key=lambda item: item.action_id))


def _action_wire_from_contract(
    bundle: GuideBundle,
    actions: tuple[ActionCandidate, ...],
) -> ActionWireContract | None:
    contract_actions = _contract_section(bundle, "actions")
    if contract_actions is None:
        return None
    style = contract_actions.get("style")
    if style not in {"binary_button_mask", "move_json", "action_name_json", "action_index_json"}:
        return None

    action_ids = tuple(action.action_id for action in actions)
    default_action = str(contract_actions.get("default_action") or _select_default_action(action_ids))
    payloads = _int_payloads(contract_actions.get("payloads"))
    if style == "binary_button_mask":
        if not payloads:
            return None
        payloads.setdefault("noop", 0)
        default_action = "noop" if "noop" in payloads else default_action

    return ActionWireContract(
        style=str(style),
        default_action=default_action,
        requires_message_type=bool(contract_actions.get("requires_message_type")),
        action_payloads=payloads,
        evidence=tuple(_contract_evidence(_contract_evidence_items(contract_actions))[:8]),
    )


def _runtime_notes_from_contract(bundle: GuideBundle, *, limit: int) -> tuple[Evidence, ...]:
    runtime = _contract_section(bundle, "runtime")
    if runtime is None:
        return ()
    return tuple(_contract_evidence(_contract_evidence_items(runtime))[:limit])


def _contract_section(bundle: GuideBundle, key: str) -> dict[str, Any] | None:
    if bundle.contract is None:
        return None
    value = bundle.contract.get(key)
    return value if isinstance(value, dict) else None


def _contract_evidence_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    evidence = value.get("evidence")
    if isinstance(evidence, list):
        return [item for item in evidence if isinstance(item, dict)]
    notes = value.get("notes")
    if isinstance(notes, list):
        return [item for item in notes if isinstance(item, dict)]
    return []


def _contract_evidence(items: list[dict[str, Any]]) -> list[Evidence]:
    result: list[Evidence] = []
    for item in items:
        document = item.get("document")
        line = item.get("line")
        text = item.get("text")
        if not isinstance(document, str) or not isinstance(text, str):
            continue
        try:
            line_no = int(line)
        except (TypeError, ValueError):
            continue
        result.append(Evidence(document, line_no, text))
    return result


def _float_contract_value(value: Any, *, default: float) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def _int_payloads(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    payloads: dict[str, int] = {}
    for key, raw in value.items():
        action_id = _normalize_action_token(str(key))
        if action_id is None:
            continue
        try:
            payloads[action_id] = int(raw)
        except (TypeError, ValueError):
            continue
    return payloads


def _scan_patterns(
    bundle: GuideBundle,
    filenames: tuple[str, ...],
    patterns: tuple[tuple[str, re.Pattern[str], float], ...],
) -> list[Evidence]:
    hits: list[Evidence] = []
    for filename in filenames:
        document = bundle.get(filename)
        if document is None:
            continue
        for line_no, line in enumerate(document.content.splitlines(), start=1):
            cleaned = _clean_line(line)
            if not cleaned or _is_low_signal_line(cleaned):
                continue
            if patterns is _VISUAL_PATTERNS and _is_negated_observation_claim(cleaned):
                continue
            for _name, pattern, _weight in patterns:
                if pattern.search(cleaned):
                    hits.append(Evidence(filename, line_no, cleaned))
                    break
    return hits


def _score_hits(hits: list[Evidence]) -> float:
    score = 0.0
    for hit in hits:
        lowered = hit.text.lower()
        for _name, pattern, weight in (*_VISUAL_PATTERNS, *_SYMBOLIC_PATTERNS):
            if pattern.search(lowered):
                score += weight
                break
    return score


def _dedupe_evidence(items: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, int, str]] = set()
    deduped: list[Evidence] = []
    for item in items:
        key = (item.document, item.line, item.text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _clean_line(line: str) -> str:
    return " ".join(line.strip().strip("|").split())


def _is_negated_observation_claim(line: str) -> bool:
    lowered = line.lower()
    if re.search(r"\b(no|without)\b.*\b(binary|frame ?buffer|framebuffer|pixel|pixels|screenshot|image)\b", lowered):
        return True
    if re.search(r"\bthere is no\b.*\b(payload|binary|frame ?buffer|framebuffer|pixel|pixels)\b", lowered):
        return True
    if "no binary" in lowered or "no frame buffer" in lowered or "no framebuffer" in lowered:
        return True
    if "no replay or frame buffer" in lowered:
        return True
    if "not included" in lowered and any(term in lowered for term in ("pixel", "frame", "image")):
        return True
    return False


def _is_low_signal_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("```"):
        return True
    if stripped.startswith("#"):
        return True
    if set(stripped) <= {"|", "-", ":", " "}:
        return True
    if stripped.lower() in {"---", "source", "source anchors"}:
        return True
    return False


def _find_contract_evidence(
    bundle: GuideBundle,
    filenames: tuple[str, ...],
    patterns: tuple[str, ...],
    evidence: list[Evidence],
) -> bool:
    compiled = tuple(re.compile(pattern, re.I) for pattern in patterns)
    for filename in filenames:
        document = bundle.get(filename)
        if document is None:
            continue
        for line_no, line in enumerate(document.content.splitlines(), start=1):
            if _is_low_signal_line(line):
                continue
            cleaned = _clean_line(line)
            if any(pattern.search(cleaned) for pattern in compiled):
                evidence.append(Evidence(filename, line_no, cleaned))
    return bool(evidence)


def _extract_button_mask_payloads(
    bundle: GuideBundle,
    action_ids: tuple[str, ...],
    evidence: list[Evidence],
) -> dict[str, int]:
    docs = (
        "INTERFACE_CONTRACT.md",
        "ACTION_SEMANTICS_AND_CONTROL.md",
        "MINIMUM_VIABLE_AGENT.md",
    )
    found_contract = False
    masks: dict[str, int] = {}
    action_set = set(action_ids)

    for filename in docs:
        document = bundle.get(filename)
        if document is None:
            continue
        for line_no, line in enumerate(document.content.splitlines(), start=1):
            cleaned = _clean_line(line)
            lowered = cleaned.lower()
            if (
                "[0x00, mask]" in cleaned
                or "button mask" in lowered
                or "2-byte binary" in lowered
                or "2-byte input" in lowered
            ):
                found_contract = True
                evidence.append(Evidence(filename, line_no, cleaned))

            parsed = _parse_button_mask_table_row(line)
            if parsed is None:
                continue
            action_id, mask = parsed
            if action_id in action_set:
                masks[action_id] = mask
                evidence.append(Evidence(filename, line_no, cleaned))

    if not found_contract or not masks:
        return {}

    masks["noop"] = 0
    if "attack" in masks:
        for alias in ("report", "vote", "a"):
            if alias in action_set:
                masks[alias] = masks["attack"]
    if "b" in masks and "vent" in action_set:
        masks["vent"] = masks["b"]

    ordered_action_ids = ("noop", *action_ids)
    return {action_id: masks[action_id] for action_id in ordered_action_ids if action_id in masks}


def _parse_button_mask_table_row(line: str) -> tuple[str, int] | None:
    if "|" not in line:
        return None
    cells = [cell.strip().strip("`").strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) < 4:
        return None
    mask: int | None = None
    mask_index = -1
    for index, cell in enumerate(cells):
        match = re.fullmatch(r"0x([0-9a-fA-F]{1,2})", cell)
        if match is not None:
            mask = int(match.group(1), 16)
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
        token = _normalize_action_token(cell.strip("`"))
        if token is not None:
            return token, mask
    return None


def _normalize_button_action_cell(cell: str) -> str | None:
    normalized = cell.strip("`").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.replace("_", "")
    button_map = {
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
    }
    return button_map.get(normalized)


def _select_default_action(action_ids: tuple[str, ...]) -> str:
    for action_id in ("noop", "stay", "wait", "up", "move_north"):
        if action_id in action_ids:
            return action_id
    return action_ids[0] if action_ids else "noop"


def _extract_quoted_tokens(line: str) -> list[str]:
    return re.findall(r"\"([A-Za-z][A-Za-z0-9_-]{0,48})\"", line)


def _normalize_action_token(token: str) -> str | None:
    normalized = token.strip().lower().replace("-", "_")
    if normalized in _ACTION_STOPWORDS:
        return None
    if normalized.endswith("_"):
        return None
    if len(normalized) < 2 and normalized not in _KNOWN_ACTION_TERMS:
        return None
    if len(normalized) > 48:
        return None
    if not re.fullmatch(r"[a-z][a-z0-9_]*", normalized):
        return None
    if normalized.startswith(("type_", "protocol_", "observation_")):
        return None
    return normalized


def _is_negative_action_claim(line: str) -> bool:
    lowered = line.lower()
    negative_phrases = (
        " no other action",
        " no attack",
        " no special",
        " no item",
        " no chat",
        "does not wait",
        "not in directions",
        "not a valid",
        "invalid ",
        "malformed",
        "missing ",
        "fatal",
        "websocket closes",
    )
    return any(phrase in lowered for phrase in negative_phrases)


def _extract_game_title(bundle: GuideBundle) -> str | None:
    for filename in ("README.md", "GAME_OVERVIEW.md"):
        document = bundle.get(filename)
        if document is None:
            continue
        for line in document.content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    return None


def _extract_hidden_information_rules(bundle: GuideBundle, *, limit: int = 6) -> tuple[Evidence, ...]:
    document = bundle.get("MEMORY_AND_HIDDEN_INFORMATION.md")
    if document is None:
        return ()
    rules: list[Evidence] = []
    for line_no, line in enumerate(document.content.splitlines(), start=1):
        cleaned = _clean_line(line)
        lowered = cleaned.lower()
        if cleaned and any(keyword in lowered for keyword in _HIDDEN_KEYWORDS):
            rules.append(Evidence(document.filename, line_no, cleaned))
            if len(rules) >= limit:
                break
    return tuple(rules)


_VISUAL_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("packed_framebuffer", re.compile(r"\bpacked\b.*\bframe ?buffer\b|\bframe ?buffer\b", re.I), 1.6),
    ("pixel", re.compile(r"\bpixels?\b|\bpalette\b|\bscreenshot\b|\bimage payload\b|\braw image\b", re.I), 1.2),
    ("binary_frame", re.compile(r"\bbinary\b.*\b(frame|message|payload)\b", re.I), 1.1),
    ("render_packet", re.compile(r"\brender(ed|er)?\b|\bsprite protocol\b", re.I), 0.9),
    ("known_shape", re.compile(r"\b128\s*[xX]\s*128\b|\b8192 bytes\b", re.I), 1.2),
)

_SYMBOLIC_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("json", re.compile(r"\bjson\b|\bsend_json\b|\biter_json\b", re.I), 1.6),
    ("structured", re.compile(r"\bstructured\b|\bobject\b|\bfields?\b|\bschema\b", re.I), 1.0),
    ("token", re.compile(r"\btoken array\b|\bobservation_kind\b.*\btoken\b|\btoken\b.*\bfeatures?\b", re.I), 1.4),
    ("state_fields", re.compile(r"\bpositions\b|\btile_owners\b|\bscores\b|\bfeatures\b|\btags\b", re.I), 1.2),
    ("native_array", re.compile(r"\bnative observation\b|\bfeature array\b|\bvector\b", re.I), 1.1),
)

_ALTERNATE_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("alternate", re.compile(r"\balternate\b|\balternative\b|\bside channel\b|\bdebug\b", re.I), 0.5),
    ("admissible", re.compile(r"\bonline-admissible\b|\bplayer-facing\b|\bplayable channel\b", re.I), 0.5),
)

_ACTION_LINE_KEYWORDS = (
    "action",
    "actions",
    "move",
    "moves",
    "button",
    "input",
    "valid values",
    "action_names",
    "mask",
    "control",
)

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

_ACTION_STOPWORDS = {
    "action",
    "actions",
    "action_names",
    "admin",
    "binary",
    "button",
    "client",
    "control",
    "done",
    "final",
    "global",
    "json",
    "message",
    "move",
    "observation",
    "observations",
    "player",
    "player_config",
    "policy",
    "protocol",
    "server",
    "slot",
    "token",
    "type",
    "websocket",
    "await",
    "binarymessage",
    "buttona",
    "buttonb",
    "consumed",
    "diagonal",
    "directions",
    "finally",
    "height",
    "keyerror",
    "none",
    "null",
    "paused",
    "play",
    "run",
    "str",
    "tick",
    "use",
    "wait",
    "width",
}

_RUNTIME_KEYWORDS = (
    "endpoint",
    "websocket",
    "server",
    "token",
    "slot",
    "tick",
    "final",
    "reset",
    "episode",
    "connect",
    "disconnect",
)

_HIDDEN_KEYWORDS = (
    "hidden",
    "private",
    "partial",
    "fog",
    "unobserved",
    "belief",
    "memory",
    "infer",
)
