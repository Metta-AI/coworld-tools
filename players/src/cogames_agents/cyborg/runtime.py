from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeAlias, TypeVar

from cogames_agents.cyborg.modes import ModeRegistry
from cogames_agents.cyborg.strategy import StrategyRunner
from cogames_agents.cyborg.trace import NullTraceSink, TraceEvent, TraceSink
from cogames_agents.cyborg.types import BeliefSnapshot, ModeDirective, StrategyResult

ObservationT = TypeVar("ObservationT")
PerceptT = TypeVar("PerceptT")
BeliefT = TypeVar("BeliefT")
ActionStateT = TypeVar("ActionStateT")
IntentT = TypeVar("IntentT")
CommandT = TypeVar("CommandT")


@dataclass(frozen=True)
class RuntimeContext(Generic[BeliefT, ActionStateT]):
    """Read-only context passed to reflex callbacks."""

    tick: int
    belief: BeliefT
    action_state: ActionStateT
    active_directive: ModeDirective
    active_mode_name: str


Reflex: TypeAlias = Callable[[RuntimeContext[BeliefT, ActionStateT]], ModeDirective | None]


class AgentRuntime(Generic[ObservationT, PerceptT, BeliefT, ActionStateT, IntentT, CommandT]):
    """Fast inner-loop runtime for cyborg agents.

    The runtime is intentionally game-agnostic. Game-specific code supplies
    perception, belief update, mode implementations, and action resolution.
    """

    def __init__(
        self,
        *,
        belief: BeliefT,
        action_state: ActionStateT,
        perceive: Callable[[ObservationT, int], PerceptT],
        update_belief: Callable[[BeliefT, PerceptT], None],
        resolve_action: Callable[[IntentT, BeliefT, ActionStateT], CommandT],
        mode_registry: ModeRegistry[BeliefT, ActionStateT, IntentT],
        default_directive: ModeDirective | Callable[[BeliefT], ModeDirective],
        strategy_runner: StrategyRunner[BeliefT, ActionStateT] | None = None,
        reflexes: Iterable[Reflex[BeliefT, ActionStateT]] = (),
        trace_sink: TraceSink | None = None,
        copy_snapshot: Callable[[object], object] = copy.deepcopy,
        apply_inferences: Callable[[BeliefT, dict], None] | None = None,
    ) -> None:
        self.belief = belief
        self.action_state = action_state
        self.perceive = perceive
        self.update_belief = update_belief
        self.resolve_action = resolve_action
        self.mode_registry = mode_registry
        self.default_directive = default_directive
        self.strategy_runner = strategy_runner
        self.reflexes = tuple(reflexes)
        self.trace_sink = trace_sink if trace_sink is not None else NullTraceSink()
        self.copy_snapshot = copy_snapshot
        self.apply_inferences = apply_inferences
        self.latest_inferences: dict = {}
        self.tick = 0

        initial = self._default_directive().issued(self.tick)
        self.mode_registry.validate(initial)
        self.active_directive = initial
        self.active_mode = self.mode_registry.create(initial)
        self.active_mode.on_enter(self.belief, self.action_state)
        self._trace(
            "mode_entered",
            {
                "mode": self.active_directive.mode,
                "source": self.active_directive.source,
                "reason": "initial",
            },
        )

    @property
    def active_mode_name(self) -> str:
        return self.active_directive.mode

    def step(self, observation: ObservationT) -> CommandT:
        """Run one perception -> belief -> mode -> action tick."""

        self.tick += 1
        percept = self.perceive(observation, self.tick)
        self._trace("perception", {"percept_type": type(percept).__name__})

        self.update_belief(self.belief, percept)
        self._trace("belief_updated", {"belief_type": type(self.belief).__name__})

        self._observe_strategy()
        self._consume_strategy_result()
        self._run_reflexes()
        self._reconcile_fallbacks()

        intent = self.active_mode.decide(self.belief, self.action_state)
        self._trace(
            "action_intent",
            {
                "mode": self.active_mode_name,
                "intent_type": type(intent).__name__,
                "intent": repr(intent),
            },
        )

        command = self.resolve_action(intent, self.belief, self.action_state)
        self._trace(
            "act_command",
            {"command_type": type(command).__name__, "command": repr(command)},
        )
        return command

    def close(self) -> None:
        """Close the optional strategy runner."""

        if self.strategy_runner is not None:
            self.strategy_runner.close()

    def install_directive(self, directive: ModeDirective, *, reason: str) -> bool:
        """Validate and install a directive.

        Returns ``True`` when a directive was accepted. Reaffirming the current
        mode updates directive metadata but preserves the live mode instance.
        """

        error = self.mode_registry.validation_error(directive)
        if error is not None:
            self._trace(
                "directive_rejected",
                {"mode": directive.mode, "reason": reason, "error": error},
            )
            return False

        issued = directive.issued(self.tick)
        if self.active_mode.matches_directive(issued):
            self.active_directive = issued
            self._trace(
                "directive_reaffirmed",
                {
                    "mode": issued.mode,
                    "source": issued.source,
                    "reason": reason,
                },
            )
            return True

        old_mode = self.active_directive.mode
        self.active_mode.on_exit(self.belief, self.action_state, issued)
        self._trace(
            "mode_exited",
            {"old_mode": old_mode, "new_mode": issued.mode, "reason": reason},
        )

        self.active_directive = issued
        self.active_mode = self.mode_registry.create(issued)
        self.active_mode.on_enter(self.belief, self.action_state)
        self._trace(
            "mode_entered",
            {
                "old_mode": old_mode,
                "mode": issued.mode,
                "source": issued.source,
                "reason": reason,
            },
        )
        return True

    def _observe_strategy(self) -> None:
        if self.strategy_runner is None:
            return
        snapshot = BeliefSnapshot(
            tick=self.tick,
            belief=self.copy_snapshot(self.belief),
            action_state=self.copy_snapshot(self.action_state),
            active_directive=self.active_directive,
        )
        self.strategy_runner.observe(snapshot)
        self._trace("snapshot_submitted", {"mode": self.active_mode_name})

    def _consume_strategy_result(self) -> None:
        if self.strategy_runner is None:
            return
        result = self.strategy_runner.poll()
        if result is None:
            return

        self._apply_strategy_inferences(result)
        if result.directive is not None:
            self.install_directive(result.directive, reason="strategy")

    def _apply_strategy_inferences(self, result: StrategyResult) -> None:
        if not result.inferences:
            return
        self.latest_inferences = dict(result.inferences)
        if self.apply_inferences is not None:
            self.apply_inferences(self.belief, self.latest_inferences)
        self._trace(
            "strategy_inferences",
            {"keys": sorted(str(key) for key in self.latest_inferences)},
        )

    def _run_reflexes(self) -> None:
        if not self.reflexes:
            return
        context = RuntimeContext(
            tick=self.tick,
            belief=self.belief,
            action_state=self.action_state,
            active_directive=self.active_directive,
            active_mode_name=self.active_mode_name,
        )
        for reflex in self.reflexes:
            directive = reflex(context)
            if directive is None:
                continue
            accepted = self.install_directive(directive, reason="reflex")
            if accepted:
                self._trace(
                    "reflex_fired",
                    {"mode": directive.mode, "source": directive.source},
                )
                return

    def _reconcile_fallbacks(self) -> None:
        if self.active_directive.expired_at(self.tick):
            self.install_directive(self._default_directive(), reason="ttl_expired")
            return

        if not self.active_mode.is_legal(self.belief):
            self.install_directive(self._default_directive(), reason="mode_illegal")

    def _default_directive(self) -> ModeDirective:
        if isinstance(self.default_directive, ModeDirective):
            return self.default_directive
        return self.default_directive(self.belief)

    def _trace(self, name: str, data: dict) -> None:
        self.trace_sink.record(TraceEvent(tick=self.tick, name=name, data=data))
