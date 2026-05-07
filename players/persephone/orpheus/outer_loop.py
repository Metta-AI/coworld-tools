"""Async outer-loop runner for Orpheus strategic mode decisions."""

from __future__ import annotations

import threading
from collections.abc import Callable

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.buffers import BeliefBuffer
from orpheus.mode import ModeDirective
from orpheus.mode_buffer import ModeBuffer


class OuterLoop:
    """Background worker that turns belief snapshots into mode directives.

    ``DESIGN.md`` describes a watcher thread that restarts the outer loop
    after unexpected termination. This implementation satisfies that
    resilience requirement with a single daemon thread whose top-level loop
    catches unexpected exceptions and continues running. That "restart in
    place" keeps the thread alive without adding a second supervisor thread.
    """

    def __init__(
        self,
        meta_decide: Callable[
            [BeliefState, ActionMemory],
            tuple[ModeDirective, dict | None],
        ],
        belief_buffer: BeliefBuffer,
        mode_buffer: ModeBuffer,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.meta_decide = meta_decide
        self.belief_buffer = belief_buffer
        self.mode_buffer = mode_buffer
        self._logger = logger
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()

    def start(self) -> None:
        """Start the outer-loop thread (daemon=True).

        Idempotent: a second start while running is a no-op.
        """
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="orpheus-outer-loop",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Signal the loop to stop and wait up to `timeout` for the thread to join."""
        self._stop_event.set()
        with self._state_lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                snapshot = self.belief_buffer.consume_blocking(timeout=0.1)
                if snapshot is None:
                    continue
                belief_state, action_memory = snapshot
                try:
                    result = self.meta_decide(belief_state, action_memory)
                except Exception as exc:
                    self._log(f"meta_decide_failed: {exc!r}")
                    continue
                try:
                    directive, inferences = result
                except (TypeError, ValueError) as exc:
                    self._log(f"meta_decide_bad_return: {exc!r} value={result!r}")
                    continue
                self.mode_buffer.push(directive, inferences)
            except Exception as exc:
                # Catch-all keeps the thread alive across unexpected errors.
                self._log(f"outer_loop_restart: {exc!r}")
                # Loop continues, effectively a "restart in place".

    def _log(self, message: str) -> None:
        if self._logger is not None:
            try:
                self._logger(message)
            except Exception:
                pass


__all__ = ["OuterLoop"]
