from __future__ import annotations

from mettagrid_sdk.sdk import MettagridState

_WEREWOLF_SKILLS = (
    (
        "public_discussion",
        "During day, rally at the bell, compare claims, and use one short evidence line before committing to a vote.",
    ),
    (
        "public_vote",
        "When the table is converging, push one target with a brief why-clause plus an explicit vote call.",
    ),
    (
        "blend_in",
        "Werewolves should follow public evidence with believable reasons instead of sounding mechanically scripted.",
    ),
    (
        "night_hunt",
        (
            "During night, werewolves should privately converge on one live villager target "
            "with a short reason plus hunt call."
        ),
    ),
    (
        "survive_and_observe",
        "Villagers at night cannot act much; keep memory current and wait for the next public discussion.",
    ),
)

_CONTROL_PRIMITIVES = (
    "objective: choose public_discussion, public_vote, blend_in, night_hunt, or survive_and_observe",
    'target_entity_id: choose a player like "agent-3" when you want to bias discussion or a hunt target',
    (
        "note: preferred short utterance with one evidence clause plus an explicit call, such as "
        '"agent-2 keeps pushing agent-0, vote agent 0" or "quiet villager near us, hunt agent 4"'
    ),
)

_BEST_PRACTICES = (
    (
        "Treat live talk as the main game mechanic. Prefer one evidence clause plus one explicit parseable call "
        "instead of chant loops or long prose."
    ),
    ("Use target_entity_id and note together when you want the low-level base to push one accusation or hunt target."),
    (
        'Keep the exact substring "vote agent N" or "hunt agent N" inside actionable talk '
        "so parsers and other agents keep up."
    ),
    "Day opens with a discussion window before the vote round opens; use it to build suspicion instead of rushing the first target.",
    "If public day discussion stalls, nominate one visible target instead of deadlocking forever.",
    "Night hunts also open later in the phase, so use early night speech to coordinate one target before contact.",
    "Use sdk.heard_speech_events() to name which agent is pushing which target when you explain a vote or hunt.",
    "During public day phases, keep villagers and werewolves physically near the bell so discussion remains audible.",
    (
        "Werewolves already know their own role and packmates through private state; "
        "do not leak that knowledge in day talk."
    ),
)


class WerewolfMafiaPromptAdapter:
    def render_state(self, state: MettagridState) -> str:
        self_state = state.self_state
        team_summary = state.team_summary
        lines = [
            "SELF",
            f"step: {state.step}",
            f"role: {self_state.role}",
            f"phase: {_phase_from_state(state)}",
            f"status: {', '.join(self_state.status) or 'none'}",
            f"inventory: {_format_mapping(self_state.inventory)}",
            f"attributes: {_format_mapping(self_state.attributes)}",
            "VISIBLE_PLAYERS",
        ]
        player_lines = [
            (
                f"- {entity.entity_id} at ({entity.position.x}, {entity.position.y}) "
                f"[{', '.join(entity.labels) or 'none'}] {_format_mapping(entity.attributes)}"
            )
            for entity in state.visible_entities
            if entity.entity_type == "agent"
        ]
        lines.extend(player_lines or ["- none"])
        lines.append("VISIBLE_OBJECTS")
        object_lines = [
            (
                f"- {entity.entity_id} at ({entity.position.x}, {entity.position.y}) "
                f"[{', '.join(entity.labels) or 'none'}] {_format_mapping(entity.attributes)}"
            )
            for entity in state.visible_entities
            if entity.entity_type != "agent"
        ]
        lines.extend(object_lines or ["- none"])
        if team_summary is not None:
            lines.extend(
                [
                    "TEAM",
                    f"team_id: {team_summary.team_id}",
                    f"shared_objectives: {', '.join(team_summary.shared_objectives) or 'none'}",
                ]
            )
        if state.recent_events:
            lines.append("RECENT_EVENTS")
            for event in state.recent_events:
                lines.append(f"- {event.event_type}: {event.summary}")
        return "\n".join(lines)

    def render_skill_library(self) -> str:
        return "\n".join(
            [
                "SKILLS",
                *_render_pairs(_WEREWOLF_SKILLS),
                "CONTROL_PRIMITIVES",
                *_render_lines(_CONTROL_PRIMITIVES),
                "BEST_PRACTICES",
                *_render_lines(_BEST_PRACTICES),
            ]
        )

    def render_reference_notes(self, *, objective: str) -> str:
        lines = [
            "WEREWOLF NOTES",
            f"- current objective: {objective or 'none'}",
            "- day discussion is public and drives accusation/vote convergence once the vote window opens.",
            "- night talk is private to werewolves and should converge on a hunt target before the hunt window opens.",
            "- visible speech is ephemeral, so preserve important claims in memory.md.",
        ]
        if objective == "night_hunt":
            lines.append(
                '- prefer one concrete reason plus an explicit call like "quiet villager near us, hunt agent N"'
            )
        elif objective == "public_vote":
            lines.append('- prefer one short why-clause plus "vote agent N" over empty repetition or target thrash')
        elif objective == "blend_in":
            lines.append("- follow public consensus and cite visible public evidence instead of inventing accusations")
        else:
            lines.append("- use the bell as the anchor point for day discussion and name who is pushing whom")
        return "\n".join(lines)


def _phase_from_state(state: MettagridState) -> str:
    return "day" if "day" in state.self_state.status else "night"


def _format_mapping(values: dict[str, str | int | float | bool]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


def _render_lines(lines: tuple[str, ...]) -> list[str]:
    return [f"- {line}" for line in lines]


def _render_pairs(lines: tuple[tuple[str, str], ...]) -> list[str]:
    return [f"- {name}: {description}" for name, description in lines]
