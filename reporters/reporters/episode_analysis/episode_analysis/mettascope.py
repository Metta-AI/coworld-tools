"""MettaScope ``replay.json`` decoding: delta fields -> per-tick series.

The compact replay format shared by every MettaGrid-based game stores most
object fields **delta-encoded**: either a plain value (constant for the whole
episode) or a list of ``[step, value]`` change pairs. This module is the
one shared decoder for that convention — the kernel that lets any reporter
turn any MettaGrid replay into per-tick series and canonical event-log rows.

Origin: extracted from Ron Dahlgren's (swgy) replay-audit tooling
(sm-policies ``replay_audit.py``/``replay_audit2.py``); the conventions are
cross-checked against the in-repo ``cogs_vs_clips_summarizer`` (which carried
its own private copy of the same kernel — this module is the shared home).

stdlib only (``json``/``zlib``/``bisect``).

Location axis order: MettaGrid replays store agent ``location`` as a 2-list
whose axis order is game-configuration-defined. This module never interprets
it; :func:`to_event_rows` takes a ``location_order`` parameter ("xy" or
"rc") and the README documents how to verify against a non-square map.
"""

from __future__ import annotations

import json
import zlib
from bisect import bisect_right
from typing import Any, Callable, Iterable

__all__ = [
    "agent_objects",
    "is_delta",
    "load_replay",
    "materialize",
    "max_steps_of",
    "objects_of_type",
    "to_event_rows",
    "value_at",
]


def load_replay(data: bytes) -> dict:
    """Parse replay bytes: zlib-compressed JSON (cogames on-disk replays,
    sniffed by the ``0x78`` zlib magic) or plain JSON (episode bundles)."""
    if data[:1] == b"\x78":
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass  # plain JSON that merely starts with 'x'
    return json.loads(data)


def is_delta(field: Any) -> bool:
    """True iff ``field`` uses the ``[[step, value], ...]`` delta encoding.

    Caveat (same as every consumer of this format): a genuinely constant
    field whose *value* is itself a list of 2-lists starting with an int is
    indistinguishable from a delta series. Pass a value predicate to
    :func:`value_at`/:func:`materialize` when that ambiguity matters (e.g.
    inventories, which are lists of ``[item_id, count]`` pairs).
    """
    return (
        isinstance(field, list)
        and bool(field)
        and all(
            isinstance(item, list) and len(item) == 2 and isinstance(item[0], int)
            and not isinstance(item[0], bool)
            for item in field
        )
    )


def _changes(field: Any, value_predicate: Callable[[Any], bool] | None) -> list[tuple[int, Any]]:
    if is_delta(field) and (
        value_predicate is None or all(value_predicate(item[1]) for item in field)
    ):
        return [(int(step), value) for step, value in field]
    return [(0, field)]


def value_at(
    field: Any, step: int, value_predicate: Callable[[Any], bool] | None = None
) -> Any:
    """The field's value at ``step`` (the last change at or before it)."""
    changes = _changes(field, value_predicate)
    steps = [s for s, _ in changes]
    idx = bisect_right(steps, step) - 1
    return changes[max(idx, 0)][1]


def materialize(
    field: Any,
    max_steps: int,
    value_predicate: Callable[[Any], bool] | None = None,
) -> list[Any]:
    """Expand a (possibly delta-encoded) field into a per-step list of
    length ``max_steps + 1`` (steps 0..max_steps inclusive)."""
    changes = _changes(field, value_predicate)
    out: list[Any] = []
    cur: Any = None
    i = 0
    for t in range(max_steps + 1):
        while i < len(changes) and changes[i][0] <= t:
            cur = changes[i][1]
            i += 1
        out.append(cur)
    return out


def max_steps_of(replay: dict) -> int:
    """Episode length, across the two dialects seen in the wild: bundle
    replays carry top-level ``max_steps``; cogames on-disk replays carry
    ``infos.attributes.steps``."""
    if isinstance(replay.get("max_steps"), int):
        return replay["max_steps"]
    infos = replay.get("infos") or {}
    attrs = infos.get("attributes") or {}
    if isinstance(attrs.get("steps"), int):
        return attrs["steps"]
    raise KeyError("replay carries neither max_steps nor infos.attributes.steps")


def objects_of_type(replay: dict, type_name: str) -> list[dict]:
    return [o for o in replay.get("objects", []) if o.get("type_name") == type_name]


def agent_objects(replay: dict) -> list[tuple[int, dict]]:
    """``(agent_id, object)`` pairs for every agent object, sorted by id.

    ``agent_id`` itself may be delta-encoded in exotic replays; take its
    step-0 value.
    """
    out: list[tuple[int, dict]] = []
    for obj in objects_of_type(replay, "agent"):
        if "agent_id" not in obj:
            continue
        agent_id = value_at(obj["agent_id"], 0)
        if isinstance(agent_id, int) and not isinstance(agent_id, bool):
            out.append((agent_id, obj))
    out.sort(key=lambda pair: pair[0])
    return out


def _is_location(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(c, int) and not isinstance(c, bool) for c in value)
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def to_event_rows(
    replay: dict,
    *,
    location_order: str = "xy",
    position_key: str = "position",
    reward_key: str = "reward",
    death_key: str = "death",
    stamp: Callable[[Any], str] = json.dumps,
) -> list[dict]:
    """Derive canonical ``(ts, player, key, value)`` event-log rows from a
    MettaScope replay.

    Emitted keys (all payloads JSON-encoded via ``stamp`` — pass
    ``reporter_sdk.zip_writer.stable_json`` from a reporter for byte-stable
    output):

    - ``position`` (per agent, on change): ``{"x": .., "y": ..}``.
      ``location_order`` says how to read the replay's 2-list: ``"xy"``
      (default) maps ``loc[0]->x``; ``"rc"`` maps ``loc[0]->row`` (y).
    - ``reward`` (per agent, on total_reward change):
      ``{"delta": .., "total": ..}``.
    - ``death`` (per agent, on alive True->False): ``{}``.
    - ``episode`` (one global row at ts 0, player -1):
      ``{"max_steps": .., "num_agents": ..}``.
    """
    if location_order not in ("xy", "rc"):
        raise ValueError(f"location_order must be 'xy' or 'rc', got {location_order!r}")
    steps = max_steps_of(replay)
    agents = agent_objects(replay)

    rows: list[dict] = [
        {
            "ts": 0,
            "player": -1,
            "key": "episode",
            "value": stamp({"max_steps": steps, "num_agents": len(agents)}),
        }
    ]

    for agent_id, obj in agents:
        if "location" in obj:
            last: Any = None
            for t, loc in enumerate(materialize(obj["location"], steps, _is_location)):
                if loc is None or loc == last:
                    continue
                last = loc
                if location_order == "xy":
                    payload = {"x": loc[0], "y": loc[1]}
                else:
                    payload = {"x": loc[1], "y": loc[0]}
                rows.append(
                    {"ts": t, "player": agent_id, "key": position_key, "value": stamp(payload)}
                )
        if "total_reward" in obj:
            last_total = 0.0
            for t, total in enumerate(materialize(obj["total_reward"], steps, _is_number)):
                if total is None or total == last_total:
                    continue
                rows.append(
                    {
                        "ts": t,
                        "player": agent_id,
                        "key": reward_key,
                        "value": stamp({"delta": total - last_total, "total": total}),
                    }
                )
                last_total = total
        if "alive" in obj:
            was_alive = True
            for t, alive in enumerate(materialize(obj["alive"], steps)):
                if alive is None:
                    continue
                if was_alive and alive is False:
                    rows.append(
                        {"ts": t, "player": agent_id, "key": death_key, "value": stamp({})}
                    )
                was_alive = bool(alive)

    rows.sort(key=lambda r: (r["ts"], r["player"], r["key"]))
    return rows


def iter_series(
    obj: dict, field: str, max_steps: int, value_predicate: Callable[[Any], bool] | None = None
) -> Iterable[tuple[int, Any]]:
    """Convenience: ``(step, value)`` pairs of a materialized object field."""
    return enumerate(materialize(obj.get(field), max_steps, value_predicate))
