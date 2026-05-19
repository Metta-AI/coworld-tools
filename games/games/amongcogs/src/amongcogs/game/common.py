"""Shared mission-setting helpers for Among Us variants."""

from __future__ import annotations

from typing import Any

from amongcogs.defaults import (
    DEFAULT_COMMS_SABOTAGE_TIMER_STEPS,
    DEFAULT_INITIAL_KILL_COOLDOWN_STEPS,
    DEFAULT_INITIAL_SABOTAGE_COOLDOWN_STEPS,
    DEFAULT_KILL_COOLDOWN_STEPS,
    DEFAULT_LIGHTS_SABOTAGE_TIMER_STEPS,
    DEFAULT_MEETING_DURATION_STEPS,
    DEFAULT_OXYGEN_SABOTAGE_TIMER_STEPS,
    DEFAULT_REACTOR_SABOTAGE_TIMER_STEPS,
    DEFAULT_SABOTAGE_COOLDOWN_STEPS,
    DEFAULT_VENT_COOLDOWN_STEPS,
)


def _int_attr(obj: Any | None, attr: str, default: int) -> int:
    if obj is not None and hasattr(obj, attr):
        return int(getattr(obj, attr))
    return default


def initial_kill_cooldown_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "initial_kill_cooldown_steps", DEFAULT_INITIAL_KILL_COOLDOWN_STEPS)


def kill_cooldown_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "kill_cooldown_steps", DEFAULT_KILL_COOLDOWN_STEPS)


def meeting_duration_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "meeting_duration_steps", DEFAULT_MEETING_DURATION_STEPS)


def reactor_sabotage_timer_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "reactor_sabotage_timer_steps", DEFAULT_REACTOR_SABOTAGE_TIMER_STEPS)


def oxygen_sabotage_timer_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "oxygen_sabotage_timer_steps", DEFAULT_OXYGEN_SABOTAGE_TIMER_STEPS)


def lights_sabotage_timer_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "lights_sabotage_timer_steps", DEFAULT_LIGHTS_SABOTAGE_TIMER_STEPS)


def comms_sabotage_timer_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "comms_sabotage_timer_steps", DEFAULT_COMMS_SABOTAGE_TIMER_STEPS)


def initial_sabotage_cooldown_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "initial_sabotage_cooldown_steps", DEFAULT_INITIAL_SABOTAGE_COOLDOWN_STEPS)


def sabotage_cooldown_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "sabotage_cooldown_steps", DEFAULT_SABOTAGE_COOLDOWN_STEPS)


def vent_cooldown_steps(mission: Any | None = None) -> int:
    return _int_attr(mission, "vent_cooldown_steps", DEFAULT_VENT_COOLDOWN_STEPS)
