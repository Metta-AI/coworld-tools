"""Cogs vs Clips replay trace reporter.

Reads the canonical Coworld episode bundle (results JSON + MettaScope replay
JSON + optional metadata) and emits a report zip with three surfaces:

- ``summary.md`` for quick human inspection.
- ``trace.jsonl`` for deterministic per-agent tick inspection.
- ``events.parquet`` in the shared ``(ts, player, key, value)`` schema.

This is the Coworld-native port of the old headless Cogames replay-watching
idea: keep the replay as playback data, then make a reporter derive the
inspection timeline from it.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from typing import Any, Callable

from pydantic import BaseModel, Field, NonNegativeInt

from reporter_sdk import (
    BundleReader,
    OutputManifest,
    ReporterInputs,
    build_report_zip,
    load_reporter_inputs,
    stable_json,
    write_events_parquet,
    write_uri,
)

REPORTER_ID = "cogs-vs-clips-summarizer"
ValuePredicate = Callable[[Any], bool]


class CogsVsClipsResults(BaseModel):
    scores: list[float]
    steps: NonNegativeInt
    mission: str


class PlayerMetadata(BaseModel):
    slot: int
    policy_name: str | None = None


class EpisodeMetadata(BaseModel):
    episode_id: str | None = None
    variant_id: str = "unknown"
    duration_seconds: float | None = None
    players: list[PlayerMetadata] = Field(default_factory=list)


class CogsVsClipsReplay(BaseModel):
    version: int
    action_names: list[str]
    item_names: list[str] = Field(default_factory=list)
    type_names: list[str] = Field(default_factory=list)
    map_size: list[int]
    num_agents: NonNegativeInt
    max_steps: NonNegativeInt
    objects: list[dict[str, Any]]
    infos: dict[str, Any] = Field(default_factory=dict)


class TraceRecord(BaseModel):
    tick: int
    agent_id: int
    policy_name: str
    alive: bool
    location: list[int] | None
    action_id: int | None
    action_name: str | None
    action_param: int | None
    action_success: bool | None
    current_reward: float | None
    total_reward: float | None
    inventory: dict[str, float]


class AgentSummary(BaseModel):
    agent_id: int
    policy_name: str
    score: float | None
    final_location: list[int] | None
    final_reward: float | None
    movement_steps: int
    max_idle_streak: int
    visited_tiles: int
    action_counts: dict[str, int]
    final_inventory: dict[str, float]


class BehaviorSummary(BaseModel):
    episode_id: str | None
    variant_id: str
    mission: str
    steps: int
    map_size: list[int]
    scores: list[float]
    agents: list[AgentSummary]
    game_stats: dict[str, Any]
    agent_stats: dict[str, Any]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_policy_infos(value: Any) -> bool:
    return isinstance(value, dict)


def _is_location(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(_is_int(coord) for coord in value)
    )


def _is_inventory(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(pair, list)
        and len(pair) == 2
        and _is_int(pair[0])
        and _is_number(pair[1])
        for pair in value
    )


def _changes(raw: Any, value_predicate: ValuePredicate) -> list[tuple[int, Any]]:
    if (
        isinstance(raw, list)
        and raw
        and all(
            isinstance(item, list)
            and len(item) == 2
            and _is_int(item[0])
            and value_predicate(item[1])
            for item in raw
        )
    ):
        return [(int(item[0]), item[1]) for item in raw]
    return [(0, raw)]


def _value_at(raw: Any, tick: int, value_predicate: ValuePredicate) -> Any:
    changes = _changes(raw, value_predicate)
    value = changes[0][1]
    for step, candidate in changes:
        if step <= tick:
            value = candidate
        else:
            break
    return value


def _agent_id(obj: dict[str, Any]) -> int | None:
    if "agent_id" not in obj:
        return None
    value = _value_at(obj["agent_id"], 0, _is_int)
    return value if _is_int(value) else None


def _policy_name(obj: dict[str, Any], tick: int, fallback: str) -> str:
    if "policy_infos" not in obj:
        return fallback
    value = _value_at(obj["policy_infos"], tick, _is_policy_infos)
    if not isinstance(value, dict):
        return fallback
    policy_name = value.get("policy_name")
    return policy_name if isinstance(policy_name, str) and policy_name else fallback


def _action_name(action_names: list[str], action_id: int | None) -> str | None:
    if action_id is None:
        return None
    if not 0 <= action_id < len(action_names):
        raise ValueError(f"action_id {action_id} is outside action_names")
    return action_names[action_id]


def _named_inventory(raw_inventory: Any, item_names: list[str]) -> dict[str, float]:
    if not _is_inventory(raw_inventory):
        return {}
    named = {}
    for item_id, amount in raw_inventory:
        name = item_names[item_id] if 0 <= item_id < len(item_names) else str(item_id)
        if amount:
            named[name] = float(amount)
    return named


def _location_at(obj: dict[str, Any], tick: int) -> list[int] | None:
    if "location" not in obj:
        return None
    value = _value_at(obj["location"], tick, _is_location)
    return value if _is_location(value) else None


def build_trace_records(
    results: CogsVsClipsResults,
    metadata: EpisodeMetadata,
    replay: CogsVsClipsReplay,
) -> list[TraceRecord]:
    metadata_names = {player.slot: player.policy_name for player in metadata.players}
    agent_objects = [
        (agent_id, obj)
        for obj in replay.objects
        if (agent_id := _agent_id(obj)) is not None
    ]
    agent_objects.sort(key=lambda pair: pair[0])

    records: list[TraceRecord] = []
    tick_count = results.steps or replay.max_steps
    for tick in range(tick_count):
        for agent_id, obj in agent_objects:
            fallback_name = metadata_names.get(agent_id) or f"Agent {agent_id}"
            action_id = (
                _value_at(obj["action_id"], tick, _is_int)
                if "action_id" in obj
                else None
            )
            inventory = (
                _value_at(obj["inventory"], tick, _is_inventory)
                if "inventory" in obj
                else []
            )
            records.append(
                TraceRecord(
                    tick=tick,
                    agent_id=agent_id,
                    policy_name=_policy_name(obj, tick, fallback_name),
                    alive=bool(
                        _value_at(obj["alive"], tick, _is_bool)
                        if "alive" in obj
                        else True
                    ),
                    location=_location_at(obj, tick),
                    action_id=action_id,
                    action_name=_action_name(replay.action_names, action_id),
                    action_param=(
                        _value_at(obj["action_param"], tick, _is_int)
                        if "action_param" in obj
                        else None
                    ),
                    action_success=(
                        _value_at(obj["action_success"], tick, _is_bool)
                        if "action_success" in obj
                        else None
                    ),
                    current_reward=(
                        float(_value_at(obj["current_reward"], tick, _is_number))
                        if "current_reward" in obj
                        else None
                    ),
                    total_reward=(
                        float(_value_at(obj["total_reward"], tick, _is_number))
                        if "total_reward" in obj
                        else None
                    ),
                    inventory=_named_inventory(inventory, replay.item_names),
                )
            )
    return records


def build_event_log_rows(records: list[TraceRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                "ts": record.tick,
                "player": record.agent_id,
                "key": "agent_state",
                "value": stable_json(
                    {
                        "policy_name": record.policy_name,
                        "alive": record.alive,
                        "location": record.location,
                        "action_id": record.action_id,
                        "action_name": record.action_name,
                        "action_param": record.action_param,
                        "action_success": record.action_success,
                        "current_reward": record.current_reward,
                        "total_reward": record.total_reward,
                        "inventory": record.inventory,
                    }
                ),
            }
        )
    return rows


def build_behavior_summary(
    results: CogsVsClipsResults,
    metadata: EpisodeMetadata,
    replay: CogsVsClipsReplay,
    records: list[TraceRecord],
) -> BehaviorSummary:
    by_agent: dict[int, list[TraceRecord]] = defaultdict(list)
    for record in records:
        by_agent[record.agent_id].append(record)

    agents: list[AgentSummary] = []
    for agent_id, agent_records in sorted(by_agent.items()):
        prev_location: list[int] | None = None
        movement_steps = 0
        idle_streak = 0
        max_idle_streak = 0
        visited: set[tuple[int, int]] = set()
        actions: Counter[str] = Counter()
        for record in agent_records:
            if record.location is not None:
                location_tuple = (record.location[0], record.location[1])
                visited.add(location_tuple)
                if prev_location is not None and record.location != prev_location:
                    movement_steps += 1
                    idle_streak = 0
                elif prev_location is not None:
                    idle_streak += 1
                    max_idle_streak = max(max_idle_streak, idle_streak)
                prev_location = record.location
            if record.action_name is not None:
                actions[record.action_name] += 1

        final = agent_records[-1]
        agents.append(
            AgentSummary(
                agent_id=agent_id,
                policy_name=final.policy_name,
                score=results.scores[agent_id]
                if 0 <= agent_id < len(results.scores)
                else None,
                final_location=final.location,
                final_reward=final.total_reward,
                movement_steps=movement_steps,
                max_idle_streak=max_idle_streak,
                visited_tiles=len(visited),
                action_counts=dict(sorted(actions.items())),
                final_inventory=final.inventory,
            )
        )

    return BehaviorSummary(
        episode_id=metadata.episode_id,
        variant_id=metadata.variant_id,
        mission=results.mission,
        steps=results.steps,
        map_size=replay.map_size,
        scores=results.scores,
        agents=agents,
        game_stats=replay.infos.get("game", {}),
        agent_stats=replay.infos.get("agent", {}),
    )


def render_summary_md(summary: BehaviorSummary) -> str:
    lines = [
        "# Cogs vs Clips Episode",
        "",
        f"- Episode: `{summary.episode_id or 'unknown'}`",
        f"- Variant: `{summary.variant_id}`",
        f"- Mission: `{summary.mission}`",
        f"- Steps: `{summary.steps}`",
        f"- Map: `{summary.map_size[0]} x {summary.map_size[1]}`",
        "",
        "| Slot | Policy | Score | Final location | Moves | Max idle | Visited | Top actions |",
        "| ---: | --- | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for agent in summary.agents:
        score = "" if agent.score is None else f"{agent.score:.4f}"
        location = (
            ""
            if agent.final_location is None
            else f"({agent.final_location[0]}, {agent.final_location[1]})"
        )
        top_actions = ", ".join(
            f"{name}:{count}"
            for name, count in Counter(agent.action_counts).most_common(5)
        )
        lines.append(
            f"| {agent.agent_id} | {agent.policy_name} | {score} | {location} | "
            f"{agent.movement_steps} | {agent.max_idle_streak} | "
            f"{agent.visited_tiles} | {top_actions} |"
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `trace.jsonl`: one deterministic JSON object per agent tick.",
            "- `events.parquet`: the same timeline in the shared event-log schema.",
            "- `behavior_summary.json`: aggregate movement, action, score, and inventory facts.",
            "",
        ]
    )
    return "\n".join(lines)


def build_zip_bytes(
    results: CogsVsClipsResults,
    metadata: EpisodeMetadata,
    replay: CogsVsClipsReplay,
) -> bytes:
    records = build_trace_records(results, metadata, replay)
    behavior_summary = build_behavior_summary(results, metadata, replay, records)
    trace_jsonl = (
        "".join(stable_json(record.model_dump()) + "\n" for record in records)
    ).encode("utf-8")
    behavior_json = (
        json.dumps(behavior_summary.model_dump(), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    summary_md = render_summary_md(behavior_summary).encode("utf-8")
    events_parquet = write_events_parquet(build_event_log_rows(records))

    return build_report_zip(
        OutputManifest(
            reporter_id=REPORTER_ID,
            render="summary.md",
            event_log="events.parquet",
            trace="trace.jsonl",
        ),
        [
            ("summary.md", summary_md),
            ("behavior_summary.json", behavior_json),
            ("trace.jsonl", trace_jsonl),
            ("events.parquet", events_parquet),
        ],
    )


def run(inputs: ReporterInputs) -> None:
    with BundleReader(inputs.episode_bundle_uri) as bundle:
        inner = bundle.inner_manifest()
        if inner.status != "success":
            raise RuntimeError(
                f"bundle status={inner.status!r}; reporter cannot operate on a failed episode"
            )
        results = CogsVsClipsResults.model_validate(bundle.read_json("results"))
        replay = CogsVsClipsReplay.model_validate(bundle.read_json("replay"))
        metadata_raw: dict[str, Any] = bundle.read_json_optional("metadata") or {}

    metadata_raw.setdefault("episode_id", inner.ereq_id)
    metadata = EpisodeMetadata.model_validate(metadata_raw)
    payload = build_zip_bytes(results=results, metadata=metadata, replay=replay)
    write_uri(inputs.report_uri, payload, content_type="application/zip")
    print(
        f"[{REPORTER_ID}] wrote zip to {inputs.report_uri}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    run(load_reporter_inputs())
