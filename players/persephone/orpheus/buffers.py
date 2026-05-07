"""Thread-safe consume-on-read buffers for Orpheus async loops."""

from __future__ import annotations

import copy
import threading
import time

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState


class BeliefBuffer:
    """Thread-safe size-1 buffer carrying belief snapshots to the outer loop.

    The buffer stores a deep-copied ``(BeliefState, ActionMemory)`` pair.
    Producers overwrite any unconsumed entry, while consumers remove the
    entry when reading it. A ``Condition`` lets the outer loop block until a
    fresh snapshot is available without ever blocking the inner loop.
    """

    def __init__(self) -> None:
        self._entry: tuple[BeliefState, ActionMemory] | None = None
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

    def push(self, belief_state: BeliefState, action_memory: ActionMemory) -> None:
        """Store a deep-copied snapshot, overwriting any unconsumed entry."""
        snapshot = (copy.deepcopy(belief_state), copy.deepcopy(action_memory))
        with self._condition:
            self._entry = snapshot
            self._condition.notify()

    def consume_blocking(
        self,
        timeout: float | None = None,
    ) -> tuple[BeliefState, ActionMemory] | None:
        """Block until a snapshot is available, then consume and return it.

        Args:
            timeout: Maximum seconds to wait. ``None`` waits indefinitely.

        Returns:
            The consumed snapshot, or ``None`` if no entry arrived before the
            timeout elapsed.
        """
        with self._condition:
            if timeout is None:
                while self._entry is None:
                    self._condition.wait(timeout)
            else:
                deadline = time.monotonic() + timeout
                remaining = timeout
                while self._entry is None and remaining > 0:
                    self._condition.wait(remaining)
                    remaining = deadline - time.monotonic()

            if self._entry is None:
                return None

            entry = self._entry
            self._entry = None
            return entry

    def try_consume(self) -> tuple[BeliefState, ActionMemory] | None:
        """Consume and return the current snapshot without blocking."""
        with self._condition:
            entry = self._entry
            self._entry = None
            return entry


__all__ = ["BeliefBuffer"]
