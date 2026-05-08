"""Mode contracts and registry for Orpheus strategic control."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from orpheus.task import Task


# ---------------------------------------------------------------------------
# Mode directives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeParams:
    """Base class for mode parameters. Subclass per mode (frozen dataclass).

    Modes with no parameters use this bare base.
    """

    pass


@dataclass(frozen=True)
class ModeDirective:
    """A complete mode specification: registry key + parameters.

    Equality is structural (default frozen-dataclass behavior on `mode` and
    `params`). The framework compares directives via `==` to decide
    reaffirmation vs. transition. See DESIGN.md §"Mode interface".
    """

    mode: str
    params: ModeParams = field(default_factory=ModeParams)


# ---------------------------------------------------------------------------
# Mode interface
# ---------------------------------------------------------------------------


class Mode(ABC):
    """Abstract base for all modes.

    Modes are registered in a ModeRegistry by string key. The agent is in
    exactly one mode at a time. See DESIGN.md §"Mode interface" and
    §"Mode switching".

    The framework activates a mode by calling the registered class with no
    arguments, then immediately assigning `mode.params` from the consumed
    ModeDirective. The class-level default keeps initial modes usable before
    the framework has explicitly activated them.
    """

    # Frozen dataclass subclass of ModeParams that this mode accepts.
    # Default is the bare ModeParams (no fields). Subclasses override.
    params_type: type[ModeParams] = ModeParams
    params: ModeParams = ModeParams()

    @abstractmethod
    def select_task(self, belief_state, action_memory) -> Task | None:
        """Per-tick task selection.

        Return a Task to set the active task (framework compares it
        structurally with the previous tick's task to decide whether
        ActionMemory must clear), or None to reaffirm the current task.
        May mutate belief_state directly.
        """
        raise NotImplementedError

    @abstractmethod
    def mode_enter(self, belief_state, action_memory) -> None:
        """One-time setup when this mode becomes active."""
        raise NotImplementedError

    @abstractmethod
    def mode_switch_cleanup(
        self, belief_state, action_memory, new_mode_directive: ModeDirective
    ) -> None:
        """One-time teardown when this mode is being replaced."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Mode registry
# ---------------------------------------------------------------------------


class ModeRegistry:
    """Dict-backed registry mapping string keys to Mode classes."""

    def __init__(self) -> None:
        self._modes: dict[str, type[Mode]] = {}

    def register(self, name: str, mode_cls: type[Mode]) -> None:
        """Register a Mode subclass under `name`. Overwrites any prior."""
        self._modes[name] = mode_cls

    def get(self, name: str) -> type[Mode] | None:
        """Return the registered Mode class for `name`, or None."""
        return self._modes.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._modes

    def __len__(self) -> int:
        return len(self._modes)


__all__ = [
    "Mode",
    "ModeParams",
    "ModeDirective",
    "ModeRegistry",
]
