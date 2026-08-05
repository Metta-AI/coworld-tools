"""Deterministic synthetic expand_replay JSONL for tests and smoke checks.

Every number here is scripted so tests can hand-compute expectations:

- 5 seats: slot 0 imposter (red), slots 1-4 crew (blue/green/orange/cyan).
- Real geometry counts: 41 task stations (centres (30i+17, 407)), 11 vents.
- Phases: Lobby 0, GameInfo 10, RoleReveal 20, Playing 30, MeetingCall 300,
  Voting 320, VoteResult 380, Playing 400, MeetingCall 700, Voting 720,
  VoteResult 780, GameOver 800. Playing spans [30,300) and [400,700);
  meetings [300,400] (body, called by slot 1) and [700,800] (button, slot 2).
- player_state every 3 ticks, 0..798. Slot s moves +(s+1) px per sample in
  x (x = 100 + (s+1) * t//3). Slot 0 sits at y=407 (station row) during
  ticks [99,162] and [180,240], else y=300; other slots hold y=100+50s.
- Slot 3 works station 5 during ticks [60,120] (21 samples of 190 playing
  and alive). Slot 0 never has an active task.
- Slot 4 is murdered at tick 250 (body at (610, 300)); slot 0 is ejected at
  tick 780 (the only `died` row). Slot 4 keeps ghost-moving after death and
  ghost-works station 2 in [300,400] - filters must ignore all of it.
- Sightings: obs 1 saw slot 0 for [200,240] (truncating slot 0's second
  near-station run to [180,198]) and slot 2 for [500,540]; obs 2 saw slot 3
  for [60,120]; obs 0 saw slot 1 for [50,80]; obs 1 saw body 4 [290,296].
- Votes m1: 330 s1->0, 340 s0->1, 350 s2 skip, 360 s3->0;
  m2: 725 s1->0, 735 s2->0, 745 s3 skip, 755 s0->3.
- Chats: tick 322 slot 1 "I saw red near navigation"; tick 710 slot 0
  "it was blue".
"""

from __future__ import annotations

import json

COLORS = ("red", "blue", "green", "orange", "cyan")
COLOR_BYTES = (3, 14, 10, 7, 15)  # engine color bytes, deliberately not palette indices
PHASES = (
    (0, "Lobby"),
    (10, "GameInfo"),
    (20, "RoleReveal"),
    (30, "Playing"),
    (300, "MeetingCall"),
    (320, "Voting"),
    (380, "VoteResult"),
    (400, "Playing"),
    (700, "MeetingCall"),
    (720, "Voting"),
    (780, "VoteResult"),
    (800, "GameOver"),
)


def row(ts: int, player: int, key: str, **value) -> str:
    return json.dumps({"ts": ts, "player": player, "key": key, "value": value})


def _phase_at(t: int) -> str:
    current = PHASES[0][1]
    for ts, phase in PHASES:
        if t >= ts:
            current = phase
    return current


def _label(slot: int) -> str:
    return f"{COLORS[slot]}({slot})"


def synthetic_lines(*, stride: int = 3) -> list[str]:
    lines = []
    for s in range(5):
        lines.append(
            row(
                0,
                s,
                "player_manifest",
                role="imposter" if s == 0 else "crew",
                color=COLORS[s],
                color_id=COLOR_BYTES[s],
                label=_label(s),
                address=f"policy-{s}",
                assigned_tasks=[] if s == 0 else [1, 2, 3, 4],
                home_x=600,
                home_y=350,
            )
        )
    tasks = [
        {"id": i, "name": f"task{i}", "room": "hall", "x": 30 * i + 10, "y": 400, "w": 14, "h": 14}
        for i in range(41)
    ]
    vents = [
        {"id": i, "x": 100 * i, "y": 600, "w": 14, "h": 14, "group": i % 4, "room": "hall"}
        for i in range(11)
    ]
    lines.append(
        row(0, -1, "map_geometry", map_name="croatoan", width=1235, height=659, tasks=tasks, vents=vents)
    )
    lines.append(
        row(
            0,
            -1,
            "episode_metadata",
            snapshot_every_ticks=stride,
            config={
                "imposter_count": 1,
                "tasks_per_player": 4,
                "kill_cooldown_ticks": 600,
                "task_complete_ticks": 72,
                "vote_timer_ticks": 600,
            },
        )
    )
    for ts, phase in PHASES:
        lines.append(row(ts, -1, "phase", phase=phase))

    for t in range(0, 801, stride):
        phase = _phase_at(t)
        for s in range(5):
            if s == 0:
                y = 407 if (99 <= t <= 162 or 180 <= t <= 240) else 300
            else:
                y = 100 + 50 * s
            alive = not (s == 4 and t >= 250) and not (s == 0 and t >= 780)
            if s == 3 and 60 <= t <= 120:
                active = 5
            elif s == 4 and 300 <= t <= 400:
                active = 2  # ghost-working a station; must never count
            else:
                active = -1
            lines.append(
                row(
                    t,
                    s,
                    "player_state",
                    label=_label(s),
                    role="imposter" if s == 0 else "crew",
                    alive=alive,
                    x=100 + (s + 1) * (t // stride),
                    y=y,
                    vel_x=s + 1,
                    vel_y=0,
                    room="hall",
                    active_task=active,
                    kill_cooldown=0,
                    vent_cooldown=0,
                    phase=phase,
                )
            )

    lines.append(row(250, 0, "kill", victim_slot=4, victim_label=_label(4)))
    lines.append(
        row(252, 4, "body_state", victim_slot=4, x=610, y=300, room="hall", kill_tick=250, killer_slot=0)
    )
    lines.append(row(298, 1, "vote_called_body", body_owner_slot=4, body_owner_label=_label(4), room="hall"))
    lines.append(row(698, 2, "vote_called_button"))
    lines.append(row(780, 0, "died"))

    lines.append(row(322, 1, "chat", text="I saw red near navigation", actor_role="crew", phase="Voting"))
    lines.append(row(710, 0, "chat", text="it was blue", actor_role="imposter", phase="MeetingCall"))

    for tick, voter, target in ((330, 1, 0), (340, 0, 1), (360, 3, 0), (725, 1, 0), (735, 2, 0), (755, 0, 3)):
        lines.append(
            row(
                tick,
                voter,
                "vote_cast",
                target_slot=target,
                target_label=_label(target),
                actor_role="imposter" if voter == 0 else "crew",
            )
        )
    for tick, voter in ((350, 2), (745, 3)):
        lines.append(row(tick, voter, "vote_cast", target="skip", actor_role="crew"))

    for obs, role, kind, target, t0, t1 in (
        (1, "crew", "player", 0, 200, 240),
        (2, "crew", "player", 3, 60, 120),
        (0, "imposter", "player", 1, 50, 80),
        (1, "crew", "player", 2, 500, 540),
        (1, "crew", "body", 4, 290, 296),
    ):
        lines.append(
            row(
                t1,
                obs,
                "player_visible_interval",
                observer_slot=obs,
                observer_role=role,
                target_kind=kind,
                target_slot=target,
                tick_start=t0,
                tick_end=t1,
                room="hall",
                x=150,
                y=300,
            )
        )
    return lines
