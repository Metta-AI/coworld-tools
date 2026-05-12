"""CvCLearner — LLM-based learner that proposes patches to the program table.

Receives experience, evaluation, and loss signals from the PCO loop,
builds an LLM prompt showing current program source code and performance
data, and parses the response into program patches (code or prompt type).
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any

from cogamer.cvc.proglet import Program
from cogamer.pco.learner import LearnerCoglet

logger = logging.getLogger(__name__)


class CvCLearner(LearnerCoglet):
    """LLM-based learner that proposes patches to the program table."""

    def __init__(
        self,
        client: Any | None = None,
        model: str = "claude-sonnet-4-20250514",
        current_programs: dict[str, Program] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.client = client
        self.model = model
        self.current_programs: dict[str, Program] = current_programs or {}

    def update_programs(self, programs: dict[str, Program]) -> None:
        """Update reference to current programs."""
        self.current_programs = programs

    async def learn(
        self,
        experience: Any,
        evaluation: Any,
        signals: list[Any],
    ) -> dict:
        """Propose program patches based on experience and evaluation."""
        if self.client is None:
            return {}

        prompt = self._build_learner_prompt(experience, evaluation, signals)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            return self._parse_patch(text)
        except Exception:
            logger.exception("LLM call failed in CvCLearner.learn")
            return {}

    def _build_learner_prompt(
        self,
        experience: Any,
        evaluation: Any,
        signals: list[Any],
    ) -> str:
        """Build prompt showing evaluation, signals, programs, and experience."""
        lines: list[str] = []

        # Evaluation
        lines.append("## Evaluation")
        lines.append(json.dumps(evaluation, default=str, indent=2))

        # Loss signals
        lines.append("\n## Loss Signals")
        for sig in signals:
            if isinstance(sig, dict):
                lines.append(f"- {sig.get('name', '?')}: magnitude={sig.get('magnitude', '?')}")
                if "feedback" in sig:
                    lines.append(f"  feedback: {sig['feedback']}")
            else:
                lines.append(f"- {sig}")

        # Current program source code
        lines.append("\n## Current Programs")
        for name, prog in self.current_programs.items():
            lines.append(f"\n### {name} (executor={prog.executor})")
            if prog.fn is not None:
                try:
                    source = inspect.getsource(prog.fn)
                    lines.append(f"```python\n{source}```")
                except (OSError, TypeError):
                    # Dynamically compiled functions may not have source
                    src = getattr(prog.fn, "_source", None)
                    if src:
                        lines.append(f"```python\n{src}```")
                    else:
                        lines.append("(source unavailable)")
            elif prog.system is not None:
                if callable(prog.system):
                    try:
                        source = inspect.getsource(prog.system)
                        lines.append(f"```python\n{source}```")
                    except (OSError, TypeError):
                        lines.append("system prompt: (callable, source unavailable)")
                else:
                    lines.append(f"system prompt: {prog.system[:200]}")

        # Experience summary
        lines.append("\n## Experience Summary")
        if isinstance(experience, dict):
            lines.append(json.dumps(experience, default=str, indent=2))
        else:
            lines.append(str(experience)[:500])

        lines.append(
            "\n## GameState API Reference"
            "\nAll programs receive a `gs` (GameState) object. Available methods:"
            "\n"
            "\n### Properties"
            "\n- `gs.hp` → int (current HP)"
            "\n- `gs.position` → tuple[int, int] (absolute position)"
            "\n- `gs.step_index` → int (current step 0-10000)"
            "\n- `gs.role` → str ('miner', 'aligner', 'scrambler')"
            "\n- `gs.resource_bias` → str ('carbon', 'oxygen', 'germanium', 'silicon')"
            "\n- `gs.agent_id` → int (0-7)"
            "\n- `gs.mg_state` → MettagridState (raw game state, may be None)"
            "\n"
            "\n### Queries"
            "\n- `gs.nearest_hub()` → KnownEntity | None"
            "\n- `gs.nearest_extractor(resource: str)` → KnownEntity | None"
            "\n- `gs.known_junctions(predicate)` → list[KnownEntity]"
            "\n- `gs.should_retreat()` → bool"
            "\n- `gs.desired_role(objective=None)` → str"
            "\n- `gs.has_role_gear(role: str)` → bool"
            "\n- `gs.team_can_afford_gear(role: str)` → bool"
            "\n- `gs.needs_emergency_mining()` → bool"
            "\n- `gs.resource_priority()` → list[str]"
            "\n- `gs.team_id()` → str"
            "\n"
            "\n### Actions (return tuple[Action, str])"
            "\n- `gs.choose_action(role)` — full engine decision tree (THE DEFAULT)"
            "\n- `gs.miner_action(summary_prefix='')` — mining logic"
            "\n- `gs.aligner_action()` — alignment logic"
            "\n- `gs.scrambler_action()` — scramble logic"
            "\n- `gs.move_to_known(entity, summary='move')` — A* pathfinding to entity"
            "\n- `gs.move_to_position(target, summary='move')` — A* pathfinding to position"
            "\n- `gs.hold(summary='hold')` — no-op"
            "\n- `gs.explore(role)` — explore pattern"
            "\n- `gs.unstick(role)` — unstick agent"
            "\n"
            "\n### Helpers (from `cvc.agent`)"
            "\n- `manhattan(pos1, pos2)` → int"
            "\n- `team_id(state)` → str (use with gs.mg_state)"
            "\n- `resource_total(state)` → int"
            "\n- `team_min_resource(state)` → int"
            "\n"
            "\n### KnownEntity"
            "\n- `.position` → tuple[int, int]"
            "\n- `.owner` → str | None"
            "\n- `.entity_type` → str"
            "\n"
            "\n## Instructions"
            "\n\nYou are optimizing a CvC (Cogs vs Clips) tournament agent. 8 independent agents"
            "\non a team compete to capture and hold junctions on an 88x88 grid for 10,000 steps."
            "\n\nIMPORTANT RULES:"
            "\n- Make ONE small, targeted change. Do NOT rewrite entire functions from scratch."
            "\n- The `step` program delegates to `gs.choose_action(gs.role)` — the proven decision tree."
            "\n  Only modify `step` to add a SPECIFIC pre-check, not to replace the entire dispatch."
            "\n- ONLY use the GameState API methods listed above. Do NOT invent methods."
            "\n- Focus on the HIGHEST loss signal magnitude."
            "\n- Prefer tuning constants (thresholds, distances) over rewriting logic."
            "\n\nRespond with ONLY a JSON object mapping program names to patches:"
            '\n{"program_name": {"type": "code", "source": "def _func_name(gs): ..."}}'
            "\n\nFor code patches: provide the COMPLETE function definition."
            "\nThe function signature must match the original (same name, same args)."
        )
        return "\n".join(lines)

    def _parse_patch(self, text: str) -> dict:
        """Extract JSON from LLM response, build Program objects for each patch."""
        # Try to extract JSON from the response
        try:
            # Handle markdown code blocks
            cleaned = text.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
            raw = json.loads(cleaned.strip())
        except (json.JSONDecodeError, IndexError, ValueError):
            logger.debug("Failed to parse LLM response as JSON: %s", text[:200])
            return {}

        if not isinstance(raw, dict):
            return {}

        patches: dict[str, Program] = {}
        for name, patch in raw.items():
            if not isinstance(patch, dict) or "type" not in patch or "source" not in patch:
                continue

            if patch["type"] == "code":
                source = patch["source"]
                try:
                    namespace: dict[str, Any] = {}
                    exec(source, namespace)  # noqa: S102
                    # Find the function defined in the source
                    fn = None
                    for v in namespace.values():
                        if callable(v) and not isinstance(v, type):
                            fn = v
                            break
                    if fn is None:
                        continue
                    fn._source = source  # type: ignore[attr-defined]
                    patches[name] = Program(executor="code", fn=fn)
                except Exception:
                    logger.debug("Failed to compile code patch for %s", name)
                    continue

            elif patch["type"] == "prompt":
                current = self.current_programs.get(name)
                patches[name] = Program(
                    executor="llm",
                    system=patch["source"],
                    parser=current.parser if current else None,
                    config=dict(current.config) if current else {},
                )

        return patches
