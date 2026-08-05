"""Typed adapter over coworld-crewrift ``expand_replay`` JSONL.

The input is the newline-delimited JSON the game repo's
``tools/expand_replay.nim`` prints in snapshot mode::

    expand_replay --format jsonl --snapshot-every N <replay.bitreplay>

Each line is an envelope ``{"ts": tick, "player": slot, "key": ..., "value":
...}`` (``player == -1`` for episode-scoped rows). This module parses one
episode's stream into an :class:`Episode`; it never re-simulates anything,
so the per-tick tracks exist only when the JSONL was generated with a
positive ``--snapshot-every`` (samples may be strided).

Schema facts this adapter encodes (each verified against the emitter):

- A skip vote is ``value.target == "skip"`` with **no** ``target_slot``;
  :class:`Vote` models it as ``target is None``, never a sentinel int.
- ``died`` fires only for ejections; murder victims emit ``kill`` and no
  ``died`` row. :attr:`Episode.deaths` takes the min over both.
- ``player_manifest.color`` is the palette color *name* and is the reliable
  identity; ``color_id`` is an internal engine byte, not a palette index.
- Meetings teleport everyone and freeze play: spans run from the
  ``MeetingCall`` phase tick to the first phase change after ``VoteResult``.
- Ghosts keep moving (through walls) and completing tasks; every behavioral
  consumer should mask through :meth:`PlayerTrack.playing_alive`.

Origin: adapted from Ron Dahlgren's (swgy) crewrift tooling
(``swgy_tools.spatial.eventlog`` + ``swgy_tools.tasks.eventlog``), merged
into one typed episode object.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

__all__ = [
    "PLAYING",
    "ChatMessage",
    "CrewriftLogError",
    "Episode",
    "Kill",
    "MeetingSpan",
    "Player",
    "PlayerTrack",
    "Sighting",
    "Vote",
    "load_episode",
    "parse_episode",
]

PLAYING = "Playing"


class CrewriftLogError(ValueError):
    """Raised when the JSONL is not usable expand_replay snapshot output."""


@dataclass(frozen=True)
class Player:
    """One seat, from ``player_manifest``."""

    slot: int
    role: str  # "crew" | "imposter"
    color: str  # palette color NAME (see module docstring re color_id)
    label: str
    address: str  # policy/uploader identity (the join name)
    assigned_tasks: tuple[int, ...]
    home_x: int
    home_y: int


@dataclass(frozen=True)
class Vote:
    """One ballot. ``target is None`` means skip."""

    tick: int
    voter: int
    target: int | None
    target_label: str
    meeting: int  # index into Episode.meetings; -1 if outside every span


@dataclass(frozen=True)
class ChatMessage:
    tick: int
    speaker: int
    text: str
    phase: str


@dataclass(frozen=True)
class Kill:
    """One murder, located at the victim's corpse."""

    tick: int
    killer: int
    victim: int
    x: int
    y: int
    room: str


@dataclass(frozen=True)
class Sighting:
    """One line-of-sight interval (the engine's own raycast, not a
    reconstruction): ``observer`` saw ``target`` for ``[tick_start,
    tick_end]`` inclusive."""

    observer: int
    observer_role: str
    target_kind: str  # "player" | "body"
    target: int
    tick_start: int
    tick_end: int
    room: str
    x: int
    y: int

    def spans(self, tick: int) -> bool:
        return self.tick_start <= tick <= self.tick_end

    def ticks(self) -> int:
        return self.tick_end - self.tick_start + 1


@dataclass(frozen=True)
class MeetingSpan:
    """One meeting: the teleport at ``MeetingCall`` through the first phase
    change after ``VoteResult``."""

    index: int
    start: int
    end: int
    kind: str  # "body" | "button" | "" (no matching vote_called_* row)
    caller: int  # reporter slot, -1 unknown
    body_owner: int  # victim slot for body reports, -1 otherwise


@dataclass
class PlayerTrack:
    """Column store of one player's ``player_state`` samples (all phases
    kept; filter through the masks)."""

    slot: int
    ticks: np.ndarray  # int64, sorted
    x: np.ndarray  # float64
    y: np.ndarray
    alive: np.ndarray  # bool
    active_task: np.ndarray  # int64, -1 = none
    playing: np.ndarray  # bool: sample's phase == "Playing"

    def playing_alive(self) -> np.ndarray:
        """The standard behavioral mask: alive, and play running (meetings
        teleport everyone; ghosts keep moving)."""
        return self.playing & self.alive

    def window(self, start: int, end: int) -> np.ndarray:
        """Mask of samples with ``start <= tick <= end``."""
        return (self.ticks >= start) & (self.ticks <= end)


@dataclass
class Episode:
    episode_id: str
    map_w: int
    map_h: int
    tasks: list[tuple[int, int]]  # station centres; 41 on croatoan
    vents: list[tuple[int, int]]  # 11 on croatoan
    players: dict[int, Player]
    phases: list[tuple[int, str]]  # sorted (tick, phase)
    playing_spans: list[tuple[int, int]]  # [start, end) per Playing phase
    meetings: list[MeetingSpan]
    votes: list[Vote]
    chats: list[ChatMessage]
    kills: list[Kill]
    deaths: dict[int, int]  # slot -> first death tick (murder or ejection)
    sightings: list[Sighting]
    tracks: dict[int, PlayerTrack]
    snapshot_stride: int
    end_tick: int
    config: dict = field(default_factory=dict)

    @property
    def imposters(self) -> list[int]:
        return sorted(s for s, p in self.players.items() if p.role == "imposter")

    @property
    def crew(self) -> list[int]:
        return sorted(s for s, p in self.players.items() if p.role != "imposter")

    def alive_at(self, slot: int, tick: int) -> bool:
        return tick < self.deaths.get(slot, np.iinfo(np.int64).max)

    def sightings_of(self, slot: int, *, kind: str = "player") -> list[Sighting]:
        """Sightings in which ``slot`` is the one being seen."""
        return [s for s in self.sightings if s.target == slot and s.target_kind == kind]


def _centres(rects: list[dict]) -> list[tuple[int, int]]:
    """Centre points of the authored 14x14 rects (``x``/``y`` top-left)."""
    return [(int(r["x"]) + int(r["w"]) // 2, int(r["y"]) + int(r["h"]) // 2) for r in rects]


_SNAPSHOT_HINT = (
    "This analysis consumes coworld-crewrift `expand_replay --format jsonl "
    "--snapshot-every N <replay>` output; regenerate the input with a "
    "positive --snapshot-every."
)


def parse_episode(lines: Iterable[str], *, episode_id: str = "") -> Episode:
    """Parse one episode's expand_replay JSONL into an :class:`Episode`.

    Strict about the input: a malformed line raises (expand_replay stdout is
    pure JSONL by construction, so damage means the wrong file), and missing
    ``map_geometry``/``player_state``/``player_manifest`` rows raise
    :class:`CrewriftLogError` with the regeneration hint.
    """
    map_w = map_h = 0
    tasks: list[tuple[int, int]] = []
    vents: list[tuple[int, int]] = []
    players: dict[int, Player] = {}
    phases: list[tuple[int, str]] = []
    raw_votes: list[tuple[int, int, int | None, str]] = []
    chats: list[ChatMessage] = []
    calls: list[tuple[int, str, int, int]] = []  # (ts, kind, caller, body_owner)
    kill_events: dict[int, tuple[int, int]] = {}  # victim -> (tick, killer)
    body_loc: dict[int, dict] = {}  # victim -> first body_state
    died: dict[int, int] = {}
    sightings: list[Sighting] = []
    samples: dict[int, list[tuple[int, int, int, bool, int, bool]]] = {}
    stride = 0
    config: dict = {}
    end_tick = 0

    for lineno, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CrewriftLogError(
                f"{episode_id or 'input'}: line {lineno} is not JSON ({exc}); "
                "expected raw expand_replay JSONL output"
            ) from None
        key = row.get("key")
        ts = int(row.get("ts", 0))
        slot = int(row.get("player", -1))
        val = row.get("value") or {}
        end_tick = max(end_tick, ts)

        if key == "map_geometry":
            map_w, map_h = int(val.get("width", 0)), int(val.get("height", 0))
            tasks = _centres(val.get("tasks", []))
            vents = _centres(val.get("vents", []))
        elif key == "player_manifest":
            players[slot] = Player(
                slot=slot,
                role=str(val.get("role", "")),
                color=str(val.get("color", "")),
                label=str(val.get("label", "")),
                address=str(val.get("address") or val.get("label") or ""),
                assigned_tasks=tuple(val.get("assigned_tasks") or ()),
                home_x=int(val.get("home_x", 0)),
                home_y=int(val.get("home_y", 0)),
            )
        elif key == "phase":
            phases.append((ts, str(val.get("phase", ""))))
        elif key == "chat":
            chats.append(ChatMessage(ts, slot, str(val.get("text", "")), str(val.get("phase", ""))))
        elif key == "vote_cast":
            target_slot = val.get("target_slot")
            skip = val.get("target") == "skip" or target_slot is None
            raw_votes.append(
                (ts, slot, None if skip else int(target_slot), str(val.get("target_label", "")))
            )
        elif key == "vote_called_body":
            calls.append((ts, "body", slot, int(val.get("body_owner_slot", -1))))
        elif key == "vote_called_button":
            calls.append((ts, "button", slot, -1))
        elif key == "kill":
            kill_events[int(val.get("victim_slot", -1))] = (ts, slot)
        elif key == "body_state":
            victim = int(val.get("victim_slot", slot))
            body_loc.setdefault(
                victim,
                {
                    "x": int(val.get("x", 0)),
                    "y": int(val.get("y", 0)),
                    "room": str(val.get("room", "")),
                    "kill_tick": int(val.get("kill_tick", ts)),
                    "killer_slot": int(val.get("killer_slot", -1)),
                },
            )
        elif key == "died":
            died.setdefault(slot, ts)
        elif key == "player_visible_interval" or key == "body_visible_interval":
            sightings.append(
                Sighting(
                    observer=int(val.get("observer_slot", -1)),
                    observer_role=str(val.get("observer_role", "")),
                    target_kind=str(val.get("target_kind", "player")),
                    target=int(val.get("target_slot", -1)),
                    tick_start=int(val.get("tick_start", ts)),
                    tick_end=int(val.get("tick_end", ts)),
                    room=str(val.get("room", "")),
                    x=int(val.get("x", 0)),
                    y=int(val.get("y", 0)),
                )
            )
        elif key == "player_state":
            samples.setdefault(slot, []).append(
                (
                    ts,
                    int(val.get("x", 0)),
                    int(val.get("y", 0)),
                    bool(val.get("alive", True)),
                    int(val.get("active_task", -1)),
                    val.get("phase") == PLAYING,
                )
            )
        elif key == "episode_metadata":
            stride = int(val.get("snapshot_every_ticks", 0))
            config = dict(val.get("config") or {})

    name = episode_id or "input"
    if map_w == 0 or not samples:
        raise CrewriftLogError(
            f"{name}: no per-tick snapshot rows found (map_geometry/player_state missing). "
            + _SNAPSHOT_HINT
        )
    if not players:
        raise CrewriftLogError(
            f"{name}: no player_manifest rows found, so roles and colors are unknown. "
            + _SNAPSHOT_HINT
        )

    phases.sort()
    tracks = {slot: _track(slot, rows) for slot, rows in samples.items()}
    if stride <= 0:
        densest = max(tracks.values(), key=lambda t: t.ticks.size)
        diffs = np.diff(densest.ticks)
        stride = int(np.median(diffs)) if diffs.size else 1
    stride = max(stride, 1)

    playing_spans, meetings = _spans(phases, calls, end_tick)
    votes = [
        Vote(ts, voter, target, label, _meeting_of(ts, meetings))
        for ts, voter, target, label in sorted(raw_votes)
    ]

    deaths = dict(died)
    for victim, (tick, _killer) in kill_events.items():
        deaths[victim] = min(deaths.get(victim, tick), tick)

    kills = _resolve_kills(kill_events, body_loc, tracks)

    return Episode(
        episode_id=name,
        map_w=map_w,
        map_h=map_h,
        tasks=tasks,
        vents=vents,
        players=players,
        phases=phases,
        playing_spans=playing_spans,
        meetings=meetings,
        votes=votes,
        chats=sorted(chats, key=lambda c: c.tick),
        kills=kills,
        deaths=deaths,
        sightings=sightings,
        tracks=tracks,
        snapshot_stride=stride,
        end_tick=end_tick,
        config=config,
    )


def load_episode(path: str | Path) -> Episode:
    """Parse one ``<episode_id>.jsonl`` file (the id is the file stem)."""
    p = Path(path)
    with p.open(encoding="utf-8") as fh:
        return parse_episode(fh, episode_id=p.stem)


def _track(slot: int, rows: list[tuple[int, int, int, bool, int, bool]]) -> PlayerTrack:
    rows.sort()
    arr = np.array(rows, dtype=np.float64)
    return PlayerTrack(
        slot=slot,
        ticks=arr[:, 0].astype(np.int64),
        x=arr[:, 1],
        y=arr[:, 2],
        alive=arr[:, 3].astype(bool),
        active_task=arr[:, 4].astype(np.int64),
        playing=arr[:, 5].astype(bool),
    )


def _spans(
    phases: list[tuple[int, str]],
    calls: list[tuple[int, str, int, int]],
    end_tick: int,
) -> tuple[list[tuple[int, int]], list[MeetingSpan]]:
    playing: list[tuple[int, int]] = []
    meetings: list[MeetingSpan] = []
    for i, (ts, ph) in enumerate(phases):
        nxt = phases[i + 1][0] if i + 1 < len(phases) else end_tick
        if ph == PLAYING:
            playing.append((ts, nxt))
        elif ph == "MeetingCall":
            vote_result = next((t for t, p in phases[i + 1 :] if p == "VoteResult"), None)
            if vote_result is None:
                end = end_tick
            else:
                end = next((t for t, _ in phases if t > vote_result), end_tick)
            meetings.append(MeetingSpan(len(meetings), ts, end, "", -1, -1))

    # A call lands at (or just before) its MeetingCall row: meeting i takes
    # the first unconsumed call that happens before the meeting resolves.
    calls = sorted(calls)
    j = 0
    resolved: list[MeetingSpan] = []
    for m in meetings:
        if j < len(calls) and calls[j][0] <= m.end:
            _, kind, caller, body_owner = calls[j]
            j += 1
            resolved.append(MeetingSpan(m.index, m.start, m.end, kind, caller, body_owner))
        else:
            resolved.append(m)
    return playing, resolved


def _meeting_of(tick: int, meetings: list[MeetingSpan]) -> int:
    for m in meetings:
        if m.start <= tick <= m.end:
            return m.index
    return -1


def _resolve_kills(
    kill_events: dict[int, tuple[int, int]],
    body_loc: dict[int, dict],
    tracks: dict[int, PlayerTrack],
) -> list[Kill]:
    """Join kill events with corpse locations; fall back to the victim's
    last track sample at/before the kill (rare: stride skipped the body)."""
    kills: list[Kill] = []
    for victim in sorted(set(kill_events) | set(body_loc)):
        loc = body_loc.get(victim)
        ev = kill_events.get(victim)
        tick = loc["kill_tick"] if loc else (ev[0] if ev else 0)
        killer = loc["killer_slot"] if loc else -1
        if killer < 0 and ev:
            killer = ev[1]
        if loc:
            x, y, room = loc["x"], loc["y"], loc["room"]
        else:
            x, y, room = 0, 0, ""
            track = tracks.get(victim)
            if track is not None:
                before = np.nonzero(track.ticks <= tick)[0]
                if before.size:
                    x, y = int(track.x[before[-1]]), int(track.y[before[-1]])
        kills.append(Kill(tick, killer, victim, x, y, room))
    return sorted(kills, key=lambda k: k.tick)
