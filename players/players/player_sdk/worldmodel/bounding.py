"""Bounding-overwatch pairs: alternate movement with a parked cover buddy.

Classic fire-and-movement for engines where a stationary agent performs
better at its job (shooting, scanning, channeling) than a moving one: the
pair advances in alternating bounds — one MOVES between cover points while
the other OVERWATCHES parked — swapping roles via a four-verb handshake:

    cover N   mover N requests cover before its bound
    got_u N   overwatcher confirms it is parked covering N's bound
    ready N   mover N reports in position
    bound N   the erstwhile overwatcher N launches ITS bound (role swap)

N is the rank of the agent whose bound the message concerns. Transport is
the caller's business: the SM emits (verb, rank) through a callback and
consumes (verb, rank, tick) messages — pair it with any channel, or none.

The design carries the two hard-won safety properties:

- EVERY wait has a timeout fallback (bound anyway): a dead, deaf, or
  detached buddy can never deadlock the advance. Degrades gracefully to
  solo movement when no channel exists at all.
- TEMPO GATES: bounding runs only while `contested` (the caller's threat
  signal, decayed over `contested_ticks`); cold transit is full-speed
  SOLO, and a progress guard (< `progress_frac` of direct travel over a
  rolling window) forfeits bounding rather than stall the objective game.

A measured warning for adopters: on an arena where score is dominated by
map TEMPO, the overwatcher's parked time can cost more than its improved
effectiveness returns even when the pair wins its fights — screen the
whole objective loop, not just the engagements.

Pairing is rank arithmetic, no negotiation: buddy = rank ^ 1. The lower
rank moves first; an overwatcher that hears nothing for two wait windows
takes the initiative itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable

SOLO = "solo"
WAIT_ACK = "wait_ack"
MOVE = "move"
OVERWATCH = "overwatch"

VERBS = ("cover", "got_u", "ready", "bound")


def pair_ranks(rank: int) -> int:
    """The buddy of `rank` under xor-pairing (0<->1, 2<->3, ...)."""
    return rank ^ 1


@dataclass
class BoundingSM:
    my_rank: int
    buddy_rank: int
    bound_len: float = 300.0        # target distance of one bound
    wait_ticks: int = 36            # handshake timeout (then bound anyway)
    dead_ticks: int = 180           # buddy silence -> SOLO
    contested_ticks: int = 120      # how long a contact keeps bounding on
    arrive_radius: float = 24.0     # movement stacks stop short; never
                                    # demand closer than the follower gives
    progress_window: int = 240
    progress_frac: float = 0.35
    speed_per_tick: float = 2.2     # conservative net speed for the guard

    state: str = SOLO
    cover_goal: tuple[float, float] | None = None
    _wait_started: int = -1
    _last_buddy_sign: int = -1      # -1 = never seen: stay optimistic, the
                                    # timeouts carry the risk
    _last_contact: int = -(1 << 30)
    _ow_since: int = -1
    _prog_anchor: tuple[int, tuple[float, float]] | None = None
    dbg: dict = field(default_factory=lambda: {
        "bounds": 0, "acks": 0, "timeouts": 0, "solo_progress": 0,
        "ow_ticks": 0})

    # ---- caller-fed signals ---------------------------------------------

    def note_buddy_sign(self, tick: int) -> None:
        self._last_buddy_sign = tick

    def note_contact(self, tick: int) -> None:
        self._last_contact = tick

    def buddy_alive(self, tick: int) -> bool:
        return (self._last_buddy_sign < 0
                or tick - self._last_buddy_sign <= self.dead_ticks)

    def contested(self, tick: int, threatened: bool) -> bool:
        return threatened or tick - self._last_contact <= self.contested_ticks

    # ---- the decision -----------------------------------------------------

    def step(self, tick: int, me_xy, goal, threatened: bool,
             inbox: Iterable[tuple[str, int, int]],
             pick_cover: Callable, tx: Callable[[str, int], None]
             ) -> tuple[tuple[float, float] | None, bool]:
        """One decision. Returns (goal_override, hold_position).

        inbox yields (verb, rank, tick) messages addressed to the pair;
        it is consumed. pick_cover(me_xy, goal, bound_len) -> point | None.
        tx(verb, rank) offers a handshake message to the caller's channel
        (fire-and-forget; the SM never waits on delivery — that is what
        the timeouts are for).
        """
        msgs = list(inbox)
        try:
            inbox.clear()               # type: ignore[attr-defined]
        except AttributeError:
            pass
        for _v, _r, t in msgs:
            self.note_buddy_sign(t)

        if goal is None:
            self.state = SOLO
            return None, False

        if not self.contested(tick, threatened) or not self.buddy_alive(tick):
            if self.state != SOLO:
                self.state = SOLO
                self.cover_goal = None
            return None, False

        if (self._prog_anchor is None
                or tick - self._prog_anchor[0] > self.progress_window):
            if self._prog_anchor is not None and self.state != SOLO:
                t0, (x0, y0) = self._prog_anchor
                d = math.hypot(me_xy[0] - x0, me_xy[1] - y0)
                need = self.progress_frac * self.speed_per_tick * (tick - t0)
                if d < need:
                    self.dbg["solo_progress"] += 1
                    self.state = SOLO
                    self.cover_goal = None
                    self._prog_anchor = (tick, (me_xy[0], me_xy[1]))
                    return None, False
            self._prog_anchor = (tick, (me_xy[0], me_xy[1]))

        heard = {(v, r) for v, r, _t in msgs}

        if self.state == SOLO:
            if ("cover", self.buddy_rank) in heard:
                tx("got_u", self.buddy_rank)
                self.dbg["acks"] += 1
                self.state = OVERWATCH
                self._ow_since = tick
                return None, True
            if self.my_rank < self.buddy_rank:
                cover = pick_cover(me_xy, goal, self.bound_len)
                if cover is not None:
                    self.cover_goal = cover
                    tx("cover", self.my_rank)
                    self.state = WAIT_ACK
                    self._wait_started = tick
                    return None, True
            else:
                self.state = OVERWATCH
                self._ow_since = tick
                return None, True
            return None, False

        if self.state == WAIT_ACK:
            if ("got_u", self.my_rank) in heard or \
                    tick - self._wait_started >= self.wait_ticks:
                if ("got_u", self.my_rank) not in heard:
                    self.dbg["timeouts"] += 1
                self.state = MOVE
                self.dbg["bounds"] += 1
                return self.cover_goal, False
            return None, True

        if self.state == MOVE:
            if self.cover_goal is None:
                self.state = SOLO
                return None, False
            dx = me_xy[0] - self.cover_goal[0]
            dy = me_xy[1] - self.cover_goal[1]
            if dx * dx + dy * dy <= self.arrive_radius ** 2:
                tx("ready", self.my_rank)
                self.state = OVERWATCH
                self._ow_since = tick
                self.cover_goal = None
                return None, True
            return self.cover_goal, False

        # OVERWATCH
        self.dbg["ow_ticks"] += 1
        if ("cover", self.buddy_rank) in heard:
            tx("got_u", self.buddy_rank)
            self.dbg["acks"] += 1
            return None, True
        if ("ready", self.buddy_rank) in heard or \
                ("bound", self.buddy_rank) in heard:
            cover = pick_cover(me_xy, goal, self.bound_len)
            if cover is not None:
                self.cover_goal = cover
                tx("bound", self.my_rank)
                self.state = MOVE
                self.dbg["bounds"] += 1
                return self.cover_goal, False
        if tick - self._ow_since >= 2 * self.wait_ticks:
            cover = pick_cover(me_xy, goal, self.bound_len)
            if cover is not None:
                self.cover_goal = cover
                tx("cover", self.my_rank)
                self.state = WAIT_ACK
                self._wait_started = tick
                return None, True
        return None, True
