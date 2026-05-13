from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import write_text


class PolicyBuildError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PolicyBuildResult:
    labels_read: int
    rules_written: int
    files: tuple[Path, ...]


def build_policy_from_labels(output_dir: Path) -> PolicyBuildResult:
    output_path = output_dir.expanduser().resolve()
    manifest = _load_manifest(output_path)
    labels = _load_labels(output_path / "visual_bootstrap" / "labels")
    allowed_actions = _candidate_action_ids(manifest)
    fallback = _fallback_action(allowed_actions)
    rules = _extract_rules(labels, allowed_actions=allowed_actions)

    policy_file = output_path / "agent" / "policy_from_labels.py"
    notes_file = output_path / "agent" / "POLICY_BOOTSTRAP.md"
    test_prefix = _test_module_prefix(str(manifest.get("game_slug", "game")), output_path)
    test_file = output_path / "agent" / "tests" / f"test_{test_prefix}_policy_from_labels.py"
    _remove_generated_policy_tests(output_path / "agent" / "tests")

    write_text(policy_file, _render_policy(rules, fallback, allowed_actions))
    write_text(notes_file, _render_notes(manifest, labels, rules, fallback))
    write_text(test_file, _render_policy_tests(rules, fallback))
    return PolicyBuildResult(
        labels_read=len(labels),
        rules_written=len(rules),
        files=(policy_file, notes_file, test_file),
    )


def _load_manifest(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "maker_manifest.json"
    if not path.exists():
        raise PolicyBuildError(f"maker manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PolicyBuildError(f"maker manifest must be a JSON object: {path}")
    return payload


def _load_labels(labels_dir: Path) -> list[dict[str, Any]]:
    if not labels_dir.exists():
        raise PolicyBuildError(f"visual labels directory not found: {labels_dir}")
    labels: list[dict[str, Any]] = []
    for path in sorted(labels_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("schema_version") == "maker.visual_label.v1":
            labels.append(payload)
    if not labels:
        raise PolicyBuildError(f"no maker.visual_label.v1 labels found in: {labels_dir}")
    return labels


def _extract_rules(
    labels: list[dict[str, Any]],
    *,
    allowed_actions: list[str],
) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    evidence: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for label in labels:
        response = label.get("response")
        validation = label.get("action_validation")
        if not isinstance(response, dict) or not isinstance(validation, dict):
            continue
        if validation.get("valid") is not True:
            continue
        action_id = validation.get("action_id")
        if action_id not in allowed_actions:
            continue
        view = _classification_id(response.get("view"))
        phase = _classification_id(response.get("phase"))
        key = (view, phase)
        counts[key][str(action_id)] += 1
        evidence[(view, phase, str(action_id))].extend(_evidence_for(response))

    rules = []
    for (view, phase), action_counts in sorted(counts.items()):
        action_id, count = action_counts.most_common(1)[0]
        rules.append(
            {
                "view": view,
                "phase": phase,
                "action_id": action_id,
                "label_count": count,
                "evidence": evidence[(view, phase, action_id)][:5],
            }
        )
    return rules


def _render_policy(rules: list[dict[str, Any]], fallback: str, allowed_actions: list[str]) -> str:
    allowed_actions_literal = json.dumps(allowed_actions, indent=4)
    return f'''from __future__ import annotations

from typing import Any


ALLOWED_ACTIONS: set[str] = set({allowed_actions_literal})
FALLBACK_ACTION = {fallback!r}
RULES: dict[tuple[str, str], str] = {{
{_rules_literal(rules)}
}}


def choose_action(label_or_response: dict[str, Any] | None = None) -> str:
    if not isinstance(label_or_response, dict):
        return FALLBACK_ACTION
    response = label_or_response.get("response", label_or_response)
    if not isinstance(response, dict):
        return FALLBACK_ACTION
    view = _classification_id(response.get("view"))
    phase = _classification_id(response.get("phase"))
    action = RULES.get((view, phase))
    if action in ALLOWED_ACTIONS:
        return action
    return FALLBACK_ACTION


def _classification_id(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("id"), str) and value["id"]:
        return value["id"]
    return "unknown"
'''


def _rules_literal(rules: list[dict[str, Any]]) -> str:
    lines = []
    for rule in rules:
        lines.append(f"    ({rule['view']!r}, {rule['phase']!r}): {rule['action_id']!r},")
    return "\n".join(lines)


def _render_notes(
    manifest: dict[str, Any],
    labels: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    fallback: str,
) -> str:
    rule_lines = "\n".join(
        f"- view `{rule['view']}`, phase `{rule['phase']}` -> `{rule['action_id']}` "
        f"({rule['label_count']} label{'s' if rule['label_count'] != 1 else ''})"
        for rule in rules
    ) or "- No valid label-derived rules were produced."
    return f"""# Policy Bootstrap

Generated by `maker_v1` from schema-validated VLM labels.

This is a generated artifact. It is a starter policy surface, not a final
competitive policy.

## Inputs

- Game: `{manifest.get("game_slug", "unknown")}`
- Labels read: `{len(labels)}`
- Rules written: `{len(rules)}`
- Fallback action: `{fallback}`

## Label-Derived Rules

{rule_lines}

## Next Step

Use `policy_from_labels.py` as a seed for deterministic policy generation.
Rules should be promoted only after their perception labels have matching
decoder/parser fixtures. Keep validating actions through the generated action
controller or protocol layer.
"""


def _render_policy_tests(rules: list[dict[str, Any]], fallback: str) -> str:
    if rules:
        rule = rules[0]
        specific_test = f'''def test_label_rule_selects_action() -> None:
    label = {{"response": {{"view": {{"id": {rule["view"]!r}}}, "phase": {{"id": {rule["phase"]!r}}}}}}}
    assert policy.choose_action(label) == {rule["action_id"]!r}
'''
    else:
        specific_test = '''def test_no_rules_falls_back() -> None:
    assert policy.choose_action({"response": {"view": {"id": "x"}, "phase": {"id": "y"}}}) == policy.FALLBACK_ACTION
'''
    return f'''from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_policy() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "policy_from_labels.py"
    spec = importlib.util.spec_from_file_location("_generated_policy_from_labels", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = _load_policy()


def test_empty_label_falls_back() -> None:
    assert policy.choose_action(None) == {fallback!r}


{specific_test}'''


def _classification_id(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("id"), str) and value["id"]:
        return value["id"]
    return "unknown"


def _evidence_for(response: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for key in ("view", "phase"):
        value = response.get(key)
        if isinstance(value, dict):
            raw = value.get("evidence")
            if isinstance(raw, list):
                evidence.extend(str(item) for item in raw if isinstance(item, str))
    recommended = response.get("recommended_action")
    if isinstance(recommended, dict) and isinstance(recommended.get("rationale"), str):
        evidence.append(recommended["rationale"])
    return evidence


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
    return actions[0] if actions else "noop"


def _test_module_prefix(game_slug: str, output_dir: Path) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", game_slug).strip("_").lower() or "game"
    output_name = re.sub(r"[^0-9A-Za-z_]+", "_", output_dir.name).strip("_").lower()
    if not output_name or output_name == slug:
        return slug
    return f"{slug}_{output_name}"


def _remove_generated_policy_tests(test_dir: Path) -> None:
    for path in test_dir.glob("test_*_policy_from_labels.py"):
        if path.exists() and _looks_like_generated_policy_test(path):
            path.unlink()


def _looks_like_generated_policy_test(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return 'Path(__file__).resolve().parents[1] / "policy_from_labels.py"' in text
