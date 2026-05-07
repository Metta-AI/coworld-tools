"""Task contracts for Orpheus act-phase execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from orpheus.types import ActionMask, View


# ---------------------------------------------------------------------------
# Act commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActCommand:
    """Per-tick output envelope from a Task.

    Lowered to protocol packets by the framework's act phase. See DESIGN.md
    §"Tasks".
    - buttons: low-level mask sent as PACKET_INPUT (0 = noop).
    - chat_text: if not None, sent as PACKET_CHAT after the input packet.
    - reset_input: if True, sends RESET_MASK (0xFF) and suppresses normal
      button + chat output for this tick.
    """

    buttons: ActionMask = 0
    chat_text: str | None = None
    reset_input: bool = False


# ---------------------------------------------------------------------------
# Task interface
# ---------------------------------------------------------------------------


class Task(ABC):
    """Abstract base for all task implementations.

    A Task encapsulates how to execute a particular kind of work (movement,
    chat, menu navigation) and produces one ActCommand per tick. Tasks read
    belief state (read-only) and read/mutate action memory (task-private
    state). Tasks do NOT signal their own completion — modes infer
    completion from belief state.
    """

    # Class attribute: which views this task can operate in. Framework
    # checks belief_state.view against this set before calling
    # select_action; on mismatch, emits noop ActCommand without invoking
    # the task. Subclasses MUST override.
    valid_views: set[View] = set()

    @abstractmethod
    def select_action(self, belief_state, action_memory) -> ActCommand:
        """Return the ActCommand for this tick."""
        raise NotImplementedError


__all__ = [
    "ActCommand",
    "Task",
]
