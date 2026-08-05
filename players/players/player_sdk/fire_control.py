"""Adaptive fire control: a self-calibrating rotation controller for any
game with turret-like aiming mechanics.

Games that expose a discrete aim angle rotated by held commands change the
rotation physics from version to version (step size, quantization, frame
cadence). A policy that hardcodes those constants breaks silently when
they move: its controller overshoots or oscillates, its predicted
alignments become phantoms, and its fire rate collapses even though every
individual component still "works". This component learns the actual
rotation rate from the game's own aim feedback and plans rotation on the
reachable-angle lattice that rate implies, so the policy keeps aiming
correctly across physics changes with no code edits.

Origin: the 2026-08-05 Paintbot Arena GameVersion 36 update changed the
aim step from 5/256ths to 40/256ths of a turn per tick with no config
diff. Policies with hardcoded rates rotated on ~90% of combat decides and
fired single-digit shots per episode. This controller, measured against
the live server build, restored normal fire volume the same night and is
generalized here.

Contract — what the game must provide for this component to work:

1. AIM ON A MODULAR CIRCLE. The aim is an integer on a circle of
   ``circle`` units (e.g. 256 brads, 360 degrees, 4096 ticks of arc).
   All arithmetic is modular; the unit does not matter.

2. CONSTANT-RATE HELD ROTATION. While a rotate command is held, the aim
   changes by a fixed integer number of units per tick, the same every
   tick, in the commanded direction. The rate is UNKNOWN and may change
   between game versions — that is the point — but within an episode it
   must be constant. (Slot-quantized aims satisfy this automatically:
   a slot step of k units/tick is a constant rate; the lattice math
   below handles the reachability consequences.)

3. AUTHORITATIVE AIM READBACK. The game reports the true aim value each
   observation (a HUD label, a state field, a telemetry channel). Feed
   it to :meth:`observe` every frame, or ``None`` on gaps (death, lobby,
   dropped frame). Learning uses only consecutive readbacks bracketing a
   known held command; gaps simply discard that sample.

4. KNOWN HOLD DURATION. The caller knows how many ticks each issued
   command persists before the next decision (the ``held_ticks``
   argument, often called "advance" in frame-stepped protocols).

5. CALLER OWNS ACTUATION AND FIRING. :meth:`command` returns a direction
   (+1 = aim increasing, -1 = decreasing, 0 = hold) and the predicted
   post-command error. Mapping direction to buttons, gating trigger
   pulls on the residual error, and modeling any fire windup/aim-lock
   mechanics remain the caller's job — those are game-specific.

What the component does with that contract:

- LEARNS THE RATE ONLINE. Consecutive readbacks under a held direction
  vote for units-per-tick; ``votes_to_switch`` agreeing observations
  replace the current rate. Frames where the game froze the aim (e.g.
  during a fire windup lock) produce non-positive movement and never
  vote, so lock mechanics cannot corrupt the estimate.

- PLANS ON THE REACHABLE LATTICE. At rate r on a circle of C units, the
  aims reachable from a start point form a lattice spaced gcd(r, C).
  Reaching the nearest lattice point to a bearing can require WRAPPING
  walks (at r=40, C=256: seven +40 steps net +24). :meth:`command`
  searches signed step counts up to ``max_plan_steps`` and issues the
  first step of the best plan, parking (direction 0) when no plan
  improves the error.

- DERIVES ITS SETTLE BAND. Within half the lattice spacing of the
  bearing, rotation cannot help; the residual must close through
  bearing motion (strafe, target motion) or the caller's fire gate.
  The band adapts automatically when the learned rate changes.

Minimal usage::

    fc = AdaptiveFireControl(circle=256, initial_rate=5)
    # each decision frame:
    fc.observe(game.own_aim_readback)          # None on gaps
    direction, err = fc.command(desired_aim, held_ticks=advance)
    mask = CCW_BUTTON if direction > 0 else CW_BUTTON if direction < 0 else 0
    if abs_error_is_within_your_fire_window(err):
        mask |= FIRE_BUTTON
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["AdaptiveFireControl"]


def circular_delta(from_angle: int, to_angle: int, circle: int) -> int:
    """Signed shortest arc from -> to, in [-circle/2, circle/2)."""
    half = circle // 2
    return ((to_angle - from_angle + half) % circle) - half


@dataclass
class AdaptiveFireControl:
    """Self-calibrating rotation controller. See the module docstring for
    the game contract.

    Parameters
    ----------
    circle:
        Units in a full turn (256 for brads, 360 for degrees, ...).
    initial_rate:
        Starting units-per-tick estimate. A wrong value costs a few
        observed rotations before the learner corrects it; a right value
        costs nothing. Use the current game version's documented rate.
    votes_to_switch:
        Consecutive-agreement threshold before adopting a newly observed
        rate. Higher = more noise-resistant, slower to adapt.
    min_settle_band:
        Floor on the "close enough, stop rotating" band, in circle
        units, for very fine rates where half the lattice spacing would
        be smaller than the game's own aim jitter.
    max_plan_steps:
        Longest wrapping walk considered. 16 reaches every lattice point
        for any rate on a 256-circle; scale with circle if you use finer
        units (the search is O(max_plan_steps) per command).
    """

    circle: int = 256
    initial_rate: int = 1
    votes_to_switch: int = 3
    min_settle_band: int = 2
    max_plan_steps: int = 16

    rate: int = field(init=False)
    aim: int = field(init=False, default=0)
    _votes: dict = field(init=False, default_factory=dict)
    _last_readback: int | None = field(init=False, default=None)
    _pending_dir: int = field(init=False, default=0)
    _pending_ticks: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        if self.circle < 4:
            raise ValueError("circle must be at least 4 units")
        if not 1 <= self.initial_rate < self.circle:
            raise ValueError("initial_rate must be in [1, circle)")
        self.rate = int(self.initial_rate)

    # -- properties derived from the learned rate ---------------------------

    @property
    def lattice_spacing(self) -> int:
        """Distance between reachable aims: gcd(rate, circle)."""
        return math.gcd(self.rate, self.circle)

    @property
    def settle_band(self) -> int:
        """|error| at or below this is parked: rotation cannot improve it."""
        return max(self.min_settle_band, self.lattice_spacing // 2)

    # -- the two calls a policy makes per decision --------------------------

    def observe(self, readback: int | None) -> None:
        """Feed the game's authoritative aim readback (or None on a gap).

        Call once per observation, BEFORE :meth:`command`. Learning pairs
        this readback with the previous one when a single direction was
        held between them for a known tick count; the aim moving by a
        positive integer multiple of that count votes for the implied
        per-tick rate. Gaps and frozen-aim frames (windup locks) never
        vote.
        """
        if readback is None:
            self._last_readback = None
            self._pending_dir = 0
            self._pending_ticks = 0
            return
        rb = readback % self.circle
        if (self._last_readback is not None and self._pending_dir != 0
                and self._pending_ticks > 0):
            moved = circular_delta(self._last_readback, rb,
                                   self.circle) * self._pending_dir
            if moved > 0 and moved % self._pending_ticks == 0:
                per_tick = moved // self._pending_ticks
                if 1 <= per_tick <= self.circle // 2:
                    n = self._votes.get(per_tick, 0) + 1
                    self._votes[per_tick] = n
                    if per_tick != self.rate and n >= self.votes_to_switch:
                        self.rate = per_tick
                        self._votes = {per_tick: n}
        self._last_readback = rb
        self.aim = rb
        self._pending_dir = 0
        self._pending_ticks = 0

    def command(self, desired: int, held_ticks: int = 1) -> tuple[int, int]:
        """Rotation direction toward ``desired`` and the residual error.

        Returns ``(direction, error)``: direction is +1 (aim increasing),
        -1 (decreasing), or 0 (parked at the best reachable aim); error is
        the signed circular delta from the post-command aim estimate to
        ``desired``. Plans multi-step wrapping walks on the reachable
        lattice and issues the first step of the best one; parks when no
        walk improves the error. ``held_ticks`` is how many ticks this
        command will be held before the next decision.
        """
        err = circular_delta(self.aim, desired, self.circle)
        if abs(err) <= self.settle_band:
            return 0, err
        turn = self.rate * max(1, int(held_ticks))
        best_abs, best_k = abs(err), 0
        for k in range(1, self.max_plan_steps + 1):
            for sign in (1, -1):
                cand = circular_delta((self.aim + sign * k * turn) % self.circle,
                                      desired, self.circle)
                if abs(cand) < best_abs:
                    best_abs, best_k = abs(cand), sign * k
        if best_k == 0:
            return 0, err
        direction = 1 if best_k > 0 else -1
        self.aim = (self.aim + direction * turn) % self.circle
        self._pending_dir = direction
        self._pending_ticks = max(1, int(held_ticks))
        return direction, circular_delta(self.aim, desired, self.circle)

    def ticks_to(self, desired: int, held_ticks: int = 1) -> int:
        """Commands needed to park at the best reachable aim for `desired`
        (0 when already parked). Useful for engagement planning."""
        if abs(circular_delta(self.aim, desired, self.circle)) <= self.settle_band:
            return 0
        turn = self.rate * max(1, int(held_ticks))
        err = circular_delta(self.aim, desired, self.circle)
        best_abs, best_k = abs(err), 0
        for k in range(1, self.max_plan_steps + 1):
            for sign in (1, -1):
                cand = circular_delta((self.aim + sign * k * turn) % self.circle,
                                      desired, self.circle)
                if abs(cand) < best_abs:
                    best_abs, best_k = abs(cand), sign * k
        return abs(best_k)
