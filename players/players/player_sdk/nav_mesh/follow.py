"""Following a cached plan tick-by-tick: :class:`NavState`.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(swgy-crewrift; original module ``swgy_base.nav.follow``). The original's
dead velocity-error helpers (``_axis_button``/``_axis_unit``) were removed
here; the shipped control law -- bang-bang hold + release-and-coast
arrival -- is exactly what the original ran in production.

A policy computes a :class:`~.plan.NavPlan` once (via
:func:`~.astar.find_path`), stores it in a ``NavState``, then each
tick calls ``update(me)`` to advance the cursor + run stuck detection and
``heading(me, others)`` to get a quantized travel direction. The direction
goal-seeks toward the current waypoint -- which on the dense lattice already
drives diagonals where they pay (45-deg edges) and cardinals on shallow slopes,
so the engine's +41% diagonal speed is exploited automatically. It can also blend
a soft *buffer* away from nearby agents (``others``) -- a pure preference (the
origin engine has no agent-to-agent collision), off unless
``params.min_follow_distance > 0``.

``heading`` returns ``(dx, dy)`` sign components only; map them to your engine's
input encoding (e.g. a d-pad button mask) in game code -- kept separate so
``nav_mesh`` stays free of protocol coupling.

==============================================================================
CONTRACT FOR POLICIES -- DO NOT FIGHT THE FOLLOWER. READ THIS BEFORE "FIXING"
TASK/MOVEMENT BEHAVIOUR.
==============================================================================
This follower already models the engine's inertia/friction. You give it a
DESTINATION; it drives there and **comes to rest ON the destination** -- it
releases the d-pad within ``params.arrival_radius`` so the residual velocity
*coasts the last few px to a stop on the goal* (that is why arrival_radius can
exceed a small target rect: the coast closes the gap). It deliberately does NOT
do velocity-error braking (braking steered the *opposite* way mid-path and
stalled the agent -- see ``heading``).

So, from a policy, the ENTIRE correct usage is:

    if nav.plan is None or nav.needs_replan or target != planned_for:
        install_plan(me, target)          # ONE destination; do not jitter it per tick
    nav.update(me)
    dx, dy = nav.heading(me)
    if (dx, dy) == (0, 0):                 # ARRIVED -- at rest on the goal
        ...do the at-destination action (e.g. hold A on a task)...
    else:
        emit movement mask_from_heading(dx, dy)

``heading == (0, 0)`` is the ONLY "I am there" signal. Act on it; nothing else.

Do **NOT**, ever:
  * brake / add velocity-error correction / "kill momentum" -- the follower
    handles inertia; your braking just emits movement that fights the settle
    AND (for tasks) zeroes engine task-progress, so the hold never completes.
  * act the instant you are merely NEAR / TOUCHING the target (e.g. the moment
    the collision point grazes a task-rect edge). You still have approach
    inertia there; you will drift back out and re-enter forever. Wait for
    ``heading == (0, 0)``. (This "edge-hold" shipped ~0 task completions and
    cost multiple league rounds. Don't.)
  * re-implement settling / "ease onto the exact pixel" / "centre myself" --
    the arrival_radius coast already lands you on the goal; an easing nudge
    re-accelerates and overshoots.
  * jitter or replan the destination every tick -- that resets the cursor so it
    never reports arrived.

If the agent isn't reaching/holding the target, the bug is the DESTINATION you
gave it (wrong point, or jittered), not the follower. Fix the destination.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from .astar import find_path
from .model import NavGrid, NavMesh
from .params import NavParams
from .plan import NavPlan

# Bump-and-dodge: probe the walkability grid these many px ahead along a candidate
# heading. The engine collision point is 1x1 (sim.nim CollisionW/H == 1), so a single
# pixel probe a few px out reliably feels a wall before we wedge into it. Two depths so
# we don't clip a wall corner that the nearer probe just misses.
_PROBE_PX = (5, 10)
# The 8 unit directions, for sliding along an obstacle when the straight push is blocked.
_DIRS8 = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))


@dataclass
class NavState:
    """Mutable follower over a cached :class:`NavPlan`."""

    params: NavParams = field(default_factory=NavParams)
    plan: NavPlan | None = None
    cursor: int = 0
    stuck: bool = False
    velocity: tuple[float, float] = (0.0, 0.0)
    grid: NavGrid | None = None  # walkability bitmap for bump-and-dodge (None -> no wall sensing)
    history: deque[tuple[int, int]] = field(default_factory=deque, init=False)
    _replan: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.history = deque(maxlen=self.params.stuck_window)

    # --- lifecycle ---------------------------------------------------------

    def set_plan(self, plan: NavPlan | None) -> None:
        """Install a freshly computed plan and reset cursor/history/flags."""
        self.plan = plan
        self.cursor = 0
        self.stuck = False
        self._replan = False
        self.velocity = (0.0, 0.0)
        self.history.clear()

    def replan(
        self, mesh: NavMesh, me_world: tuple[int, int], goal: int | tuple[int, int]
    ) -> NavPlan | None:
        """Route from ``me_world`` to ``goal`` and install the result."""
        plan = find_path(mesh, me_world, goal, self.params)
        self.set_plan(plan)
        return plan

    # --- per-tick ----------------------------------------------------------

    def update(self, me_world: tuple[int, int]) -> None:
        """Advance the cursor past reached waypoints and run stuck detection.

        Also estimates current velocity (px/tick) from the last two positions
        (exposed for policies/telemetry; the controller itself deliberately
        does not consume it -- see the module docstring).
        """
        if self.history:
            prev = self.history[-1]
            self.velocity = (
                float(me_world[0] - prev[0]),
                float(me_world[1] - prev[1]),
            )
        self.history.append(me_world)
        # Advance while the current waypoint is within arrival_radius; the loop
        # collapses several clustered waypoints reached in a single tick.
        r2 = self.params.arrival_radius * self.params.arrival_radius
        while self.plan is not None and self.cursor < len(self.plan):
            wx, wy = self.plan.waypoints[self.cursor]
            dx, dy = wx - me_world[0], wy - me_world[1]
            if dx * dx + dy * dy <= r2:
                self.cursor += 1
            else:
                break
        self._detect_stuck()

    def _detect_stuck(self) -> None:
        # Once the window is full, a bounding-box span below stuck_epsilon means
        # little net travel -- this catches both standing still and oscillation
        # (ping-ponging between two waypoints, or two crewmates repelling).
        if len(self.history) < self.history.maxlen:
            return
        xs = [p[0] for p in self.history]
        ys = [p[1] for p in self.history]
        span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        if span < self.params.stuck_epsilon:
            self.stuck = True
            if self.params.replan_on_stuck:
                self._replan = True

    def target(self) -> tuple[int, int] | None:
        """Current waypoint coordinate, or ``None`` if the plan is done/absent."""
        if self.plan is None or self.cursor >= len(self.plan):
            return None
        return self.plan.waypoints[self.cursor]

    def heading(
        self,
        me_world: tuple[int, int],
        others: Iterable[tuple[int, int]] = (),
        collision: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        """Desired button direction as ``(dx, dy)`` signs in ``{-1, 0, 1}``.

        Goal-seek toward the current waypoint, blended with repulsion from any
        ``others`` within ``min_follow_distance``. With ``others`` empty or
        ``avoidance_weight`` 0 this reduces to pure seek. Honors
        ``params.diagonal`` (4-way collapses the smaller axis to 0).

        With ``params.inertia`` the engine integrates acceleration and coasts
        under friction, so the follower HOLDS the buttons straight at the
        current waypoint (per-axis, beyond ``axis_deadband``) and releases only
        within ``arrival_radius`` of the *final* waypoint -- residual velocity
        then coasts the last few px to a stop on the goal. Velocity-error
        braking was tried and removed (see the inline comment below).

        Finally, if a ``grid`` is set, the chosen direction is run through
        bump-and-dodge (:meth:`_dodge`): if pushing straight would drive into a
        wall, slide along it instead. ``collision`` is the engine's 1x1 collision
        point used for the wall probe (defaults to ``me_world`` if omitted).
        """
        tgt = self.target()
        if tgt is None:
            return (0, 0)

        mx, my = me_world
        to_x, to_y = tgt[0] - mx, tgt[1] - my
        sx, sy = self._separation(me_world, others)
        aw = self.params.avoidance_weight
        probe = collision if collision is not None else me_world

        if not self.params.inertia:
            # Raw direction to target + separation, no momentum compensation.
            ux, uy = _unit(to_x, to_y)
            return self._dodge(probe, *self._quantize(ux + aw * sx, uy + aw * sy))

        # HOLD the buttons straight at the current waypoint at full speed. Press an axis whenever
        # the waypoint is more than a small deadband off on it; a genuinely diagonal target drives
        # BOTH axes, and since the engine clamps velX/velY independently that yields |v| =
        # max_speed*sqrt(2) -- the +41% diagonal boost -- automatically. We deliberately do NOT
        # do velocity-error braking here: that pressed the *opposite* way mid-path (it once
        # steered DOWN toward an UP waypoint) and stalled the agent in place. We only release to
        # stop once we've reached the FINAL goal, so a crew agent still settles onto its task rect.
        if (
            self.cursor >= len(self.plan) - 1
            and to_x * to_x + to_y * to_y <= self.params.arrival_radius**2
        ):
            return (0, 0)  # arrived at the final goal -> stop
        dead = self.params.axis_deadband
        dx = 0 if abs(to_x) < dead else (1 if to_x > 0 else -1)
        dy = 0 if abs(to_y) < dead else (1 if to_y > 0 else -1)
        # blend crew separation: only steer onto an axis we're not already driving toward the goal
        if aw > 0.0:
            if dx == 0 and abs(sx) * aw > 0.5:
                dx = 1 if sx > 0 else -1
            if dy == 0 and abs(sy) * aw > 0.5:
                dy = 1 if sy > 0 else -1
        if not self.params.diagonal and dx and dy:  # 4-way: keep the dominant axis
            if abs(to_x) >= abs(to_y):
                dy = 0
            else:
                dx = 0
        return self._dodge(probe, dx, dy)

    def _dodge(self, origin: tuple[int, int], dx: int, dy: int) -> tuple[int, int]:
        """Proactive wall-dodge: if a ``grid`` says pushing ``(dx, dy)`` drives straight into a
        wall, steer to the nearest open direction instead, so we don't waste ticks shoving into
        geometry (the engine itself slides along walls; this just aims true). No grid / open ahead
        / boxed in -> input unchanged; stuck-detection + replan remain the backstop."""
        if self.grid is None or (dx == 0 and dy == 0):
            return (dx, dy)
        if self._walkable_ahead(origin, dx, dy):
            return (dx, dy)  # open ahead -> go straight
        base = math.atan2(dy, dx)
        for cand in sorted(
            (d for d in _DIRS8 if d != (dx, dy)),
            key=lambda d: _angle_diff(math.atan2(d[1], d[0]), base),
        ):
            if self._walkable_ahead(origin, *cand):
                return cand  # slide to the nearest open direction
        return (dx, dy)  # boxed in -> let stuck/replan handle

    def _walkable_ahead(self, origin: tuple[int, int], cx: int, cy: int) -> bool:
        """True iff the grid is walkable at each ``_PROBE_PX`` step along unit ``(cx, cy)``."""
        ox, oy = origin
        norm = math.hypot(cx, cy) or 1.0
        for d in _PROBE_PX:
            if not self.grid.is_walkable(
                int(round(ox + cx / norm * d)), int(round(oy + cy / norm * d))
            ):
                return False
        return True

    def _separation(
        self, me_world: tuple[int, int], others: Iterable[tuple[int, int]]
    ) -> tuple[float, float]:
        r = self.params.min_follow_distance
        if r <= 0.0:
            return (0.0, 0.0)
        mx, my = me_world
        sx = sy = 0.0
        for ox, oy in others:
            dx, dy = mx - ox, my - oy
            d = math.hypot(dx, dy)
            if d == 0.0:
                continue  # coincident: no defined push direction
            if d < r:
                ux, uy = dx / d, dy / d
                falloff = 1.0 - d / r  # strongest up close, 0 at the threshold
                sx += ux * falloff
                sy += uy * falloff
        return (sx, sy)

    def _quantize(self, dx: float, dy: float) -> tuple[int, int]:
        eps = 1e-9
        if not self.params.diagonal:
            # Keep only the dominant axis (4-way movement).
            if abs(dx) >= abs(dy):
                dy = 0.0
            else:
                dx = 0.0
        sx = 0 if abs(dx) < eps else (1 if dx > 0 else -1)
        sy = 0 if abs(dy) < eps else (1 if dy > 0 else -1)
        return (sx, sy)

    # --- signals -----------------------------------------------------------

    @property
    def arrived(self) -> bool:
        """True once the cursor has passed the final waypoint."""
        return self.plan is not None and self.cursor >= len(self.plan)

    @property
    def needs_replan(self) -> bool:
        """True when stuck detection has requested a fresh plan."""
        return self._replan


def _angle_diff(a: float, b: float) -> float:
    """Smallest absolute angle (radians) between headings ``a`` and ``b``."""
    d = abs(a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


def _unit(x: float, y: float) -> tuple[float, float]:
    d = math.hypot(x, y)
    if d == 0.0:
        return (0.0, 0.0)
    return (x / d, y / d)

