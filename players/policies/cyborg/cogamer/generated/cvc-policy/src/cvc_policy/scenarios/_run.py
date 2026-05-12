"""Run — typed view over a run folder.

Loads `events.json` and `result.json` from a run directory and
exposes helpers for assertion code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MiningTrip:
    """One segment of mining toward a single target extractor."""

    target_pos: tuple[int, int]
    target_kind: str
    start_step: int
    end_step: int
    bump_count: int


class Run:
    """Typed view over `runs/<id>/{events.json, result.json}`."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        events_path = run_dir / "events.json"
        if not events_path.exists():
            raise FileNotFoundError(events_path)
        self.events: list[dict[str, Any]] = json.loads(events_path.read_text())
        result_path = run_dir / "result.json"
        self.result: dict[str, Any] = (
            json.loads(result_path.read_text()) if result_path.exists() else {}
        )

    def events_of_type(self, type_: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == type_]

    def events_for_agent(self, agent: int) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("agent") == agent]

    def first_target_for_agent(self, agent: int) -> dict[str, Any] | None:
        for e in self.events:
            if e["type"] == "target" and e.get("agent") == agent:
                return e
        return None

    def mining_trips(self, agent: int) -> list[MiningTrip]:
        """Segment target events and subsequent mining actions into trips.

        A trip starts at a `target` event whose `kind` contains
        "extractor". Its bump count is the number of subsequent
        `action` events whose `summary` starts with "mine_" before
        the next `target` event.
        """
        trips: list[MiningTrip] = []
        current: dict[str, Any] | None = None
        bumps = 0
        last_bump_step: int | None = None
        for e in self.events:
            if e.get("agent") != agent:
                continue
            if e["type"] == "target":
                kind = e["payload"].get("kind", "")
                pos = tuple(e["payload"].get("pos", []))
                if "extractor" not in kind:
                    # non-mining target closes any open trip
                    if current is not None:
                        trips.append(_finalize_trip(current, bumps, last_bump_step))
                        current = None
                        bumps = 0
                        last_bump_step = None
                    continue
                cur_pos = (
                    tuple(current["payload"].get("pos", [])) if current is not None else None
                )
                if current is not None and pos == cur_pos:
                    # Same target re-asserted; ongoing trip, ignore.
                    continue
                if current is not None:
                    trips.append(_finalize_trip(current, bumps, last_bump_step))
                current = e
                bumps = 0
                last_bump_step = None
            elif e["type"] == "action" and current is not None:
                summary = e["payload"].get("summary", "")
                if summary.startswith("mine_"):
                    bumps += 1
                    last_bump_step = e["step"]
        if current is not None:
            trips.append(_finalize_trip(current, bumps, last_bump_step))
        return trips


def _finalize_trip(
    target_event: dict[str, Any], bumps: int, last_bump_step: int | None
) -> MiningTrip:
    pos = target_event["payload"]["pos"]
    return MiningTrip(
        target_pos=tuple(pos),  # type: ignore[arg-type]
        target_kind=target_event["payload"].get("kind", ""),
        start_step=target_event["step"],
        end_step=last_bump_step if last_bump_step is not None else target_event["step"],
        bump_count=bumps,
    )
