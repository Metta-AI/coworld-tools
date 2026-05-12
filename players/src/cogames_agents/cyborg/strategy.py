from __future__ import annotations

import threading
from typing import Protocol, TypeVar

from cogames_agents.cyborg.buffers import OverwriteBuffer
from cogames_agents.cyborg.types import BeliefSnapshot, ModeDirective, StrategyResult

BeliefT = TypeVar("BeliefT")
ActionStateT = TypeVar("ActionStateT")


class Strategy(Protocol[BeliefT, ActionStateT]):
    """Strategy object that maps belief snapshots to directives."""

    def decide(self, snapshot: BeliefSnapshot[BeliefT, ActionStateT]) -> StrategyResult | ModeDirective | None: ...


class StrategyRunner(Protocol[BeliefT, ActionStateT]):
    """Runtime-facing wrapper around a strategy loop."""

    def observe(self, snapshot: BeliefSnapshot[BeliefT, ActionStateT]) -> None: ...

    def poll(self) -> StrategyResult | None: ...

    def close(self) -> None: ...


def normalize_strategy_result(
    result: StrategyResult | ModeDirective | None,
) -> StrategyResult | None:
    """Normalize strategy return values into ``StrategyResult``."""

    if result is None:
        return None
    if isinstance(result, StrategyResult):
        return result
    return StrategyResult(directive=result)


class ManualStrategyRunner(StrategyRunner[BeliefT, ActionStateT]):
    """Runner whose directives are manually published by tests or callers."""

    def __init__(self) -> None:
        self._buffer: OverwriteBuffer[StrategyResult] = OverwriteBuffer()

    def publish(self, result: StrategyResult | ModeDirective) -> None:
        normalized = normalize_strategy_result(result)
        if normalized is not None:
            self._buffer.publish(normalized)

    def observe(self, snapshot: BeliefSnapshot[BeliefT, ActionStateT]) -> None:
        del snapshot

    def poll(self) -> StrategyResult | None:
        return self._buffer.take()

    def close(self) -> None:
        self._buffer.close()


class SynchronousStrategyRunner(StrategyRunner[BeliefT, ActionStateT]):
    """Cadence-limited strategy runner evaluated on the inner-loop thread."""

    def __init__(
        self,
        strategy: Strategy[BeliefT, ActionStateT],
        *,
        cadence_ticks: int = 1,
    ) -> None:
        self._strategy = strategy
        self._cadence_ticks = max(cadence_ticks, 1)
        self._last_eval_tick = -1
        self._pending: StrategyResult | None = None

    def observe(self, snapshot: BeliefSnapshot[BeliefT, ActionStateT]) -> None:
        if self._last_eval_tick < 0 or snapshot.tick - self._last_eval_tick >= self._cadence_ticks:
            self._last_eval_tick = snapshot.tick
            self._pending = normalize_strategy_result(self._strategy.decide(snapshot))

    def poll(self) -> StrategyResult | None:
        result = self._pending
        self._pending = None
        return result

    def close(self) -> None:
        self._pending = None


class ThreadedStrategyRunner(StrategyRunner[BeliefT, ActionStateT]):
    """Background strategy runner connected with latest-value buffers."""

    def __init__(
        self,
        strategy: Strategy[BeliefT, ActionStateT],
        *,
        name: str = "cyborg-strategy",
        wait_timeout: float = 0.05,
    ) -> None:
        self._strategy = strategy
        self._wait_timeout = wait_timeout
        self._snapshots: OverwriteBuffer[BeliefSnapshot[BeliefT, ActionStateT]] = OverwriteBuffer()
        self._results: OverwriteBuffer[StrategyResult] = OverwriteBuffer()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=name)
        self._thread.start()

    def observe(self, snapshot: BeliefSnapshot[BeliefT, ActionStateT]) -> None:
        self._snapshots.publish(snapshot)

    def poll(self) -> StrategyResult | None:
        return self._results.take()

    def close(self) -> None:
        self._stop.set()
        self._snapshots.close()
        self._results.close()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            snapshot = self._snapshots.wait_take(timeout=self._wait_timeout)
            if snapshot is None:
                continue
            result = normalize_strategy_result(self._strategy.decide(snapshot))
            if result is not None:
                self._results.publish(result)
