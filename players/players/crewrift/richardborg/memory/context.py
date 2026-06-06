"""Meeting memory context for Richardborg."""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from typing import Any

from players.crewrift.crewborg.strategy.meeting.context import serialize_meeting_context
from players.crewrift.crewborg.strategy.meeting.schema import VOTE_SKIP
from players.crewrift.crewborg.strategy.suspicion import top_suspect
from players.crewrift.crewborg.types import Belief, PlayerEvent, PlayerRecord

MAX_OBSERVATIONS = 18


def serialize_richard_meeting_context(
    belief: Belief,
    *,
    trigger: str,
    tentative_vote: str | None = None,
    sent_chat_texts: set[str] | None = None,
    last_chat_tick: int | None = None,
) -> dict[str, Any]:
    context = serialize_meeting_context(
        belief,
        trigger=trigger,
        tentative_vote=tentative_vote,
        sent_chat_texts=sent_chat_texts,
        last_chat_tick=last_chat_tick,
    )
    vote_target = top_suspect(belief) or VOTE_SKIP
    context["memory"] = {
        "summary_md": _memory_file("summary.md"),
        "templates_md": _memory_file("templates.md"),
        "canonical_observations": _canonical_observations(belief),
        "vote_recommendation": {
            "target": vote_target,
            "reason": _vote_reason(belief, vote_target),
        },
    }
    return context


@cache
def _memory_file(name: str) -> str:
    return files(__package__).joinpath(name).read_text(encoding="utf-8").strip()


def _canonical_observations(belief: Belief) -> list[dict[str, Any]]:
    items: list[tuple[int, dict[str, Any]]] = []
    for color in sorted(belief.confirmed_imposters):
        items.append(
            (
                belief.last_tick,
                {
                    "tick": belief.last_tick,
                    "kind": "confirmed_imposter",
                    "text": f"I directly confirmed {color} as an imposter from a kill or vent transition.",
                    "player": color,
                    "target": None,
                },
            )
        )
    for color, record in sorted(belief.roster.items()):
        items.extend(_record_observations(belief, color, record))
    items.sort(key=lambda item: item[0], reverse=True)
    return [payload for _, payload in items[:MAX_OBSERVATIONS]]


def _record_observations(
    belief: Belief, color: str, record: PlayerRecord
) -> list[tuple[int, dict[str, Any]]]:
    observations: list[tuple[int, dict[str, Any]]] = []
    for event in record.events:
        text = _event_text(belief, color, event)
        if text is None:
            continue
        observations.append(
            (
                event.end_tick,
                {
                    "tick": event.end_tick,
                    "kind": event.kind,
                    "text": text,
                    "player": color,
                    "target": event.target_color,
                    "duration_ticks": event.duration_ticks,
                    "region": _region_name(belief, event),
                    "min_dist": event.min_dist,
                },
            )
        )
    return observations


def _event_text(belief: Belief, color: str, event: PlayerEvent) -> str | None:
    region = _region_name(belief, event)
    if event.kind == "proximity" and event.target_color is not None:
        target = event.target_color
        target_record = belief.roster.get(target)
        if target_record is not None and target_record.life_status == "dead":
            return f"I saw {color} with {target} shortly before {target} died."
        return f"I saw {color} and {target} together."
    if event.kind == "near_body" and event.target_color is not None:
        return f"I saw {color} near {event.target_color}'s body."
    if event.kind == "vent":
        location = f" near {region}" if region is not None else ""
        return f"I saw {color} at a vent{location}."
    if event.kind == "task":
        location = f" at {region}" if region is not None else ""
        return f"I saw {color} at a task{location}."
    if event.kind == "room":
        location = f" in {region}" if region is not None else ""
        return f"I saw {color}{location}."
    return None


def _region_name(belief: Belief, event: PlayerEvent) -> str | None:
    if belief.map is None or event.region_index is None:
        return None
    index = event.region_index
    if event.kind == "room" and 0 <= index < len(belief.map.rooms):
        return belief.map.rooms[index].name
    if event.kind == "task" and 0 <= index < len(belief.map.tasks):
        return belief.map.tasks[index].name
    if event.kind == "vent" and 0 <= index < len(belief.map.vents):
        vent = belief.map.vents[index]
        return f"vent {vent.group}:{vent.group_index}"
    return None


def _vote_reason(belief: Belief, vote_target: str) -> str:
    if vote_target == VOTE_SKIP:
        return "No live suspect crossed the deterministic vote threshold."
    score = belief.suspicion[vote_target]
    return f"{vote_target} is the highest deterministic suspect at P(imposter)={score:.4f}."
