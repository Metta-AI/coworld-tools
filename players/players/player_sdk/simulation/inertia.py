"""Integer fixed-point inertial movement: a reference engine for tests.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (swgy-crewrift;
original module ``swgy_tools.navbench.enginesim``, itself a byte-faithful
Python port of the CrewRift engine's player-movement step in ``sim.nim``:
``applyInput`` per-axis accel/friction, the slide-direction preferences,
``applyMomentumAxis`` carry sub-stepping, ``trySlideMove``/``canSlide*``,
and ``canOccupy`` collision against the walk layer).

The engine constants are parameterized into :class:`InertiaParams`; the
defaults are the validated reference profile, so ``Engine(grid)`` with
default params reproduces the origin engine's movement bit-for-bit (the
ported physics tests pin this). Supply different params to approximate
another engine's accel/friction/clamp model.

Everything is integer fixed-point like the origin engine: velocity is in
units where ``motion_scale`` units == 1 pixel/tick, position is integer
pixels, and a per-axis ``carry`` accumulates sub-pixel motion. Nim's ``div``
truncates toward zero, so the friction divide uses :func:`_tdiv` (Python
``//`` floors -- wrong for negative velocity).

Key emergent property of the reference profile: velX/velY clamp
**independently**, so holding a diagonal reaches ``|v| = terminal * sqrt(2)``
-- the +41% diagonal speed boost the ``nav_mesh`` follower exploits.

The grid is duck-typed (:class:`Walkability`): anything with
``is_walkable(x, y) -> bool`` works, including ``nav_mesh.NavGrid``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["Body", "Engine", "InertiaParams", "Walkability"]


@runtime_checkable
class Walkability(Protocol):
    """Anything that answers per-pixel walkability (e.g. ``nav_mesh.NavGrid``)."""

    def is_walkable(self, x: int, y: int) -> bool: ...


@dataclass(frozen=True)
class InertiaParams:
    """The movement constants. Defaults = the byte-faithful reference profile
    (CrewRift ``sim.nim``)."""

    motion_scale: int = 256
    """Velocity units per pixel/tick."""

    accel: int = 76
    """Velocity units added per tick per held input axis (~0.30 px/tick²)."""

    friction_num: int = 144
    friction_den: int = 256
    """With no input, velocity multiplies by ``friction_num/friction_den``
    (~0.5625) each tick, truncated toward zero."""

    stop_threshold: int = 8
    """Velocity magnitude below which friction snaps an axis to 0."""

    max_speed: int = 704
    """Per-axis velocity clamp (704/256 = 2.75 px/tick). Axes clamp
    independently — diagonals reach ``terminal_px * sqrt(2)``."""

    slide_max_scan: int = 3
    """Max perpendicular offset scanned when sliding along a wall."""

    collision_w: int = 1
    collision_h: int = 1
    """Body collision box in pixels (the reference engine's is 1x1)."""

    @property
    def terminal_px(self) -> float:
        """Cardinal per-axis terminal speed in px/tick."""
        return self.max_speed / self.motion_scale


def _tdiv(a: int, b: int) -> int:
    """Integer division truncating toward zero, matching Nim's ``div``."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _sign(v: int) -> int:
    return (v > 0) - (v < 0)


def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


@dataclass
class Body:
    """Mutable kinematic state (integer fixed-point, like the engine)."""

    x: int
    y: int
    velX: int = 0
    velY: int = 0
    carryX: int = 0
    carryY: int = 0

    @property
    def pos(self) -> tuple[int, int]:
        return (self.x, self.y)


class Engine:
    """The movement step over a fixed walkability grid."""

    def __init__(self, grid: Walkability, params: InertiaParams = InertiaParams()) -> None:
        self.grid = grid
        self.params = params

    def center_of(self, b: Body) -> tuple[int, int]:
        """The gameplay center (the engine measures from ``pos + collision//2``)."""
        return (b.x + self.params.collision_w // 2, b.y + self.params.collision_h // 2)

    def speed_px_of(self, b: Body) -> float:
        """Current speed magnitude in px/tick."""
        return (b.velX * b.velX + b.velY * b.velY) ** 0.5 / self.params.motion_scale

    # --- collision ----------------------------------------------------------

    def can_occupy(self, x: int, y: int) -> bool:
        for dy in range(self.params.collision_h):
            for dx in range(self.params.collision_w):
                if not self.grid.is_walkable(x + dx, y + dy):
                    return False
        return True

    # --- the per-tick step ---------------------------------------------------

    def step(self, b: Body, inputX: int, inputY: int) -> None:
        """Advance ``b`` one tick under held input ``inputX``/``inputY`` in {-1,0,1}."""
        self._apply_input(b, inputX, inputY)
        preferred_slide_y = inputY if inputY != 0 else _sign(b.velY)
        preferred_slide_x = inputX if inputX != 0 else _sign(b.velX)
        self._apply_momentum_axis(b, preferred_slide_y, horizontal=True)
        self._apply_momentum_axis(b, preferred_slide_x, horizontal=False)

    def _apply_input(self, b: Body, inputX: int, inputY: int) -> None:
        p = self.params
        if inputX != 0:
            b.velX = _clamp(b.velX + inputX * p.accel, -p.max_speed, p.max_speed)
        else:
            b.velX = _tdiv(b.velX * p.friction_num, p.friction_den)
            if abs(b.velX) < p.stop_threshold:
                b.velX = 0
        if inputY != 0:
            b.velY = _clamp(b.velY + inputY * p.accel, -p.max_speed, p.max_speed)
        else:
            b.velY = _tdiv(b.velY * p.friction_num, p.friction_den)
            if abs(b.velY) < p.stop_threshold:
                b.velY = 0

    def _apply_momentum_axis(self, b: Body, preferred_slide: int, *, horizontal: bool) -> None:
        scale = self.params.motion_scale
        velocity = b.velX if horizontal else b.velY
        carry = (b.carryX if horizontal else b.carryY) + velocity
        while abs(carry) >= scale:
            step = -1 if carry < 0 else 1
            nx = b.x + step if horizontal else b.x
            ny = b.y if horizontal else b.y + step
            if self.can_occupy(nx, ny):
                if horizontal:
                    b.x = nx
                else:
                    b.y = ny
                carry -= step * scale
            else:
                radius = self._slide_scan_radius(carry, velocity)
                if self._try_slide_move(b, step, radius, preferred_slide, horizontal):
                    carry -= step * scale
                else:
                    carry = 0
                    break
        if horizontal:
            b.carryX = carry
        else:
            b.carryY = carry

    def _slide_scan_radius(self, carry: int, velocity: int) -> int:
        scale = self.params.motion_scale
        pending = abs(carry) // scale
        speed = (abs(velocity) + scale - 1) // scale
        return _clamp(max(1, max(pending, speed)), 1, self.params.slide_max_scan)

    def _try_slide_move(
        self, b: Body, step: int, radius: int, preferred_slide: int, horizontal: bool
    ) -> bool:
        if radius <= 0:
            return False
        preferred = _sign(preferred_slide)
        for distance in range(1, radius + 1):
            if preferred != 0:
                if self._try_slide_offset(b, step, preferred * distance, horizontal):
                    return True
                if self._try_slide_offset(b, step, -preferred * distance, horizontal):
                    return True
            else:
                if self._try_slide_offset(b, step, -distance, horizontal):
                    return True
                if self._try_slide_offset(b, step, distance, horizontal):
                    return True
        return False

    def _try_slide_offset(self, b: Body, step: int, offset: int, horizontal: bool) -> bool:
        if horizontal:
            if not self._can_slide_horizontal(b.x, b.y, step, offset):
                return False
            b.x += step
            b.y += offset
        else:
            if not self._can_slide_vertical(b.x, b.y, step, offset):
                return False
            b.x += offset
            b.y += step
        return True

    def _can_slide_horizontal(self, x: int, y: int, step: int, offset: int) -> bool:
        if offset == 0:
            return False
        slide_step = _sign(offset)
        for i in range(1, abs(offset) + 1):
            if not self.can_occupy(x, y + slide_step * i):
                return False
        return self.can_occupy(x + step, y + offset)

    def _can_slide_vertical(self, x: int, y: int, step: int, offset: int) -> bool:
        if offset == 0:
            return False
        slide_step = _sign(offset)
        for i in range(1, abs(offset) + 1):
            if not self.can_occupy(x + slide_step * i, y):
                return False
        return self.can_occupy(x + offset, y + step)
