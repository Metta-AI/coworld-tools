"""ProgLet mixin — unified program table with pluggable executors.

Programs are named units of computation. Each program specifies an executor
type (e.g. "code", "llm") and the executor handles dispatch. This generalizes
CodeLet's function table into a richer abstraction.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from cogamer.cvc.coglet import enact


@dataclass
class Program:
    """A named unit of computation with executor-specific configuration."""

    executor: str
    fn: Callable | None = None
    system: str | Callable[..., str] | None = None
    tools: list[str] = field(default_factory=list)
    parser: Callable[[str], Any] | None = None
    config: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Executor(Protocol):
    """Protocol for program executors."""

    async def run(
        self,
        program: Program,
        context: Any,
        invoke: Callable[[str, Any], Awaitable[Any]],
    ) -> Any: ...


class CodeExecutor:
    """Runs program.fn(context). Supports sync and async callables."""

    async def run(
        self,
        program: Program,
        context: Any,
        invoke: Callable[[str, Any], Awaitable[Any]],
    ) -> Any:
        assert program.fn is not None
        result = program.fn(context)
        if inspect.isawaitable(result):
            result = await result
        return result


class ProgLet:
    """Mixin: unified program table with pluggable executors.

    Programs are registered via @enact("register") and executed via invoke().
    Custom executors are registered via @enact("executor").
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.programs: dict[str, Program] = {}
        self.executors: dict[str, Executor] = {"code": CodeExecutor()}

    @enact("register")
    async def _proglet_register(self, programs: dict[str, Program]) -> None:
        self.programs.update(programs)

    @enact("executor")
    async def _proglet_executor(self, executors: dict[str, Executor]) -> None:
        self.executors.update(executors)

    async def invoke(self, name: str, context: Any = None) -> Any:
        program = self.programs[name]
        executor = self.executors[program.executor]
        return await executor.run(program, context, self.invoke)
