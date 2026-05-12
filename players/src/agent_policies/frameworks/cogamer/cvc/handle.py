"""Data types for coglet child management: Command, CogBase, CogletHandle.

CogletHandle is the opaque reference a parent COG holds to a child. It exposes
only observe() and guide() — the parent never accesses the child directly.
CogBase is a bundle of assets used to create a Coglet via runtime.spawn().
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Type


@dataclass
class Command:
    """A control-plane command sent via guide()."""

    type: str
    data: Any = None


@dataclass
class CogBase:
    """A bundle of assets that can be used to create a Coglet.

    Contains the class to instantiate, constructor kwargs, and
    supervision policy (restart behavior, backoff).

    Usage:
        base = CogBase(cls=MyCoglet, kwargs={"name": "worker"})
        handle = await runtime.spawn(base)
    """

    cls: Type
    kwargs: dict[str, Any] = field(default_factory=dict)
    label: str = ""  # optional display label for UI
    restart: str = "never"  # "never" | "on_error" | "always"
    max_restarts: int = 3
    backoff_s: float = 1.0


class CogletHandle:
    """Opaque reference to a running child Coglet.

    Used by parent COG for observe() and guide().
    """

    def __init__(self, coglet: Any):
        self._coglet = coglet

    async def observe(self, channel: str) -> AsyncIterator[Any]:
        sub = self._coglet._bus.subscribe(channel)
        async for data in sub:
            yield data

    def observe_one(self, channel: str) -> asyncio.Task:
        """Subscribe to a channel and return a Task that resolves to the next message.

        The subscription is created immediately (not lazily), so it won't
        miss messages sent between calling observe_one() and awaiting.
        """
        sub = self._coglet._bus.subscribe(channel)
        return asyncio.ensure_future(sub.get())

    async def guide(self, command: Command) -> None:
        """Fire-and-forget command to child's @enact handlers."""
        await self._coglet._dispatch_enact(command)

    @property
    def coglet(self) -> Any:
        return self._coglet
