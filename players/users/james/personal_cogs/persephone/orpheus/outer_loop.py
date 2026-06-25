"""Async outer-loop runner for Orpheus strategic mode decisions."""

from __future__ import annotations

import threading
from collections.abc import Callable

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.buffers import BeliefBuffer
from orpheus.logging import LogLevel, Logger
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
        tick_provider: Callable[[], int] | None = None,
    ) -> None:
        self.meta_decide = meta_decide
        self.belief_buffer = belief_buffer
        self.mode_buffer = mode_buffer
        self._logger = logger
        self._tick_provider = tick_provider
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
                self._refresh_logger_metadata(belief_state)
                self._event(
                    "meta_decide_input",
                    {
                        "tick": belief_state.tick,
                        "view": _view_name(getattr(belief_state, "view", None)),
                        "task": _task_name(getattr(belief_state, "current_task", None)),
                    },
                    level=LogLevel.DECISIONS,
                )
                try:
                    result = self.meta_decide(belief_state, action_memory)
                except Exception as exc:
                    self._emit(
                        "meta_decide_failed",
                        {"exception": repr(exc), "consumed_tick": belief_state.tick},
                        f"meta_decide_failed: {exc!r}",
                    )
                    continue
                try:
                    directive, inferences = result
                except (TypeError, ValueError) as exc:
                    self._emit(
                        "meta_decide_bad_return",
                        {
                            "exception": repr(exc),
                            "value": repr(result),
                            "consumed_tick": belief_state.tick,
                        },
                        f"meta_decide_bad_return: {exc!r} value={result!r}",
                    )
                    continue
                self._event(
                    "meta_decide_output",
                    {
                        "directive": repr(directive)
                        if directive is not None
                        else None,
                        "inferences": inferences,
                    },
                    level=LogLevel.DECISIONS,
                )
                self.mode_buffer.push(directive, inferences)
                staleness = None
                if self._tick_provider is not None:
                    try:
                        staleness = self._tick_provider() - belief_state.tick
                    except Exception:
                        pass
                self._event(
                    "outer_loop_cycle",
                    {
                        "consumed_tick": belief_state.tick,
                        "staleness": staleness,
                        "directive": repr(directive)
                        if directive is not None
                        else None,
                    },
                )
            except Exception as exc:
                # Catch-all keeps the thread alive across unexpected errors.
                self._emit(
                    "outer_loop_restart",
                    {"exception": repr(exc)},
                    f"outer_loop_restart: {exc!r}",
                )
                # Loop continues, effectively a "restart in place".

    def _emit(
        self,
        category: str,
        data: dict,
        legacy_msg: str,
        level: LogLevel = LogLevel.EVENTS,
    ) -> None:
        try:
            if isinstance(self._logger, Logger):
                self._logger.event(category, data, level)
            elif self._logger is not None:
                self._logger(legacy_msg)
        except Exception:
            pass

    def _event(
        self,
        category: str,
        data: dict,
        level: LogLevel = LogLevel.EVENTS,
    ) -> None:
        try:
            if isinstance(self._logger, Logger):
                self._logger.event(category, data, level)
        except Exception:
            pass

    def _refresh_logger_metadata(self, belief_state: BeliefState) -> None:
        if not isinstance(self._logger, Logger):
            return
        self._logger.update_metadata(
            tick=belief_state.tick,
            view=_view_name(getattr(belief_state, "view", None)),
            mode=None,
            task=_task_name(getattr(belief_state, "current_task", None)),
        )


def _view_name(view: object) -> str | None:
    if view is None:
        return None
    value = getattr(view, "value", None)
    if isinstance(value, str):
        return value
    return str(view)


def _task_name(task: object) -> str | None:
    if task is None:
        return None
    return type(task).__name__


__all__ = ["OuterLoop"]
