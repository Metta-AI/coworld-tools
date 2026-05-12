from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

BeliefT = TypeVar("BeliefT")
ActionStateT = TypeVar("ActionStateT")


class ModeParams(BaseModel):
    """Base class for typed mode parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EmptyModeParams(ModeParams):
    """Parameter object for modes with no parameters."""


class ModeDirective(BaseModel):
    """Instruction from the strategy layer to run a named mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str
    params: SerializeAsAny[ModeParams] = Field(default_factory=EmptyModeParams)
    source: str = "strategy"
    issued_at_tick: int = 0
    ttl_ticks: int = 0
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def issued(self, tick: int) -> ModeDirective:
        """Return a copy stamped with the tick where the inner loop accepted it."""

        return self.model_copy(update={"issued_at_tick": tick})

    def expired_at(self, tick: int) -> bool:
        """Return whether this directive's TTL has elapsed at ``tick``."""

        return self.ttl_ticks > 0 and self.issued_at_tick > 0 and tick - self.issued_at_tick >= self.ttl_ticks


class ActionIntent(BaseModel):
    """Generic symbolic intent a mode can emit.

    Game-specific agents will usually subclass this model or replace it with
    their own intent type. The base shape is useful for examples and small
    agents.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic: str = "noop"
    target: tuple[int, int] | None = None
    text: str | None = None
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionCommand(BaseModel):
    """Generic concrete command returned by an action resolver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str = "noop"
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyResult(BaseModel):
    """Result produced by a strategy loop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    directive: ModeDirective | None = None
    inferences: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class BeliefSnapshot(Generic[BeliefT, ActionStateT]):
    """Immutable envelope handed to strategy loops.

    The runtime owns how belief/action state are copied. By default it uses
    ``copy.deepcopy`` before constructing this snapshot.
    """

    tick: int
    belief: BeliefT
    action_state: ActionStateT
    active_directive: ModeDirective
