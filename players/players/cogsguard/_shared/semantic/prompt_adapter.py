from __future__ import annotations

from collections.abc import Mapping

from cogsguard.semantic import render_cogsguard_skill_library
from players.cogsguard._shared.semantic.learnings import render_cogsguard_learnings
from players.cogsguard._shared.semantic.scenarios import CogsguardScenarioPresets
from mettagrid.sdk.agent import MettagridState
from mettagrid.sdk.agent.progress import ProgressSnapshot


class CogsguardPromptAdapter:
    def render_state(self, state: MettagridState) -> str:
        self_state = state.self_state
        team_summary = state.team_summary
        assert team_summary is not None
        inventory_text = _format_mapping(self_state.inventory)
        status_text = ", ".join(self_state.status) if self_state.status else "none"
        lines = [
            "SELF",
            f"step: {state.step}",
            f"team: {team_summary.team_id}",
            f"role: {self_state.role}",
            f"position: ({self_state.position.x}, {self_state.position.y})",
            f"inventory: {inventory_text}",
            f"status: {status_text}",
            f"talk: {_format_talk(self_state.attributes)}",
            f"shared_inventory: {_format_mapping(team_summary.shared_inventory)}",
            f"shared_objectives: {', '.join(team_summary.shared_objectives) or 'none'}",
            "VISIBLE",
        ]
        for entity in state.visible_entities:
            attribute_text = _format_mapping(entity.attributes)
            label_text = ", ".join(entity.labels)
            lines.append(
                f"- {entity.entity_type} at ({entity.position.x}, {entity.position.y}) [{label_text}] {attribute_text}"
            )
        if state.recent_events:
            lines.append("RECENT_EVENTS")
            for event in state.recent_events:
                lines.append(f"- {event.event_type}: {event.summary}")
        return "\n".join(lines)

    def render_skill_library(self) -> str:
        return render_cogsguard_skill_library()

    def render_reference_notes(self, *, objective: str, progress: ProgressSnapshot | None = None) -> str:
        return "\n".join(
            [
                "SCENARIO_PRESETS",
                *_render_pairs(CogsguardScenarioPresets.library()),
                "TACTICAL_LEARNINGS",
                render_cogsguard_learnings(objective=objective, progress=progress, limit=4),
            ]
        )


def _format_mapping(values: Mapping[str, str | int | float | bool]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


def _format_talk(attributes: Mapping[str, str | int | float | bool]) -> str:
    talk_text = attributes.get("talk_text")
    if not isinstance(talk_text, str) or not talk_text:
        return "none"
    remaining_steps = attributes.get("talk_remaining_steps", 0)
    return f"{talk_text} (ttl={remaining_steps})"


def _render_pairs(lines: tuple[tuple[str, str], ...]) -> list[str]:
    return [f"- {name}: {description}" for name, description in lines]
