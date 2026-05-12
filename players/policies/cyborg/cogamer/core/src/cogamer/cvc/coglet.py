"""Base Coglet class — the universal COG/LET primitive.

Every Coglet has two interfaces:
  LET (data + control): @listen, @enact, transmit
  COG (supervision):    create, observe, guide

Handler discovery uses __init_subclass__ to scan the MRO for @listen/@enact
decorated methods. Both sync and async handlers are supported.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from cogamer.cvc.channel import ChannelBus, ChannelStats
from cogamer.cvc.handle import CogBase, CogletHandle, Command

# --- Decorators ---


def listen(channel: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a method as a data-plane handler for a named channel."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._listen_channel = channel  # type: ignore[attr-defined]
        return fn

    return decorator


def enact(command_type: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a method as a control-plane handler for a named command."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._enact_command = command_type  # type: ignore[attr-defined]
        return fn

    return decorator


# --- Base class ---


class Coglet:
    """Universal Coglet primitive.

    LET interface: @listen, @enact, transmit
    COG interface: create, observe, guide
    """

    # Populated by __init_subclass__
    _listen_handlers: dict[str, str]  # channel -> method name
    _enact_handlers: dict[str, str]  # command_type -> method name

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        listen_handlers: dict[str, str] = {}
        enact_handlers: dict[str, str] = {}
        for base in reversed(cls.__mro__):
            base_listen = getattr(base, "_listen_handlers", None)
            if isinstance(base_listen, dict):
                listen_handlers.update(base_listen)
            base_enact = getattr(base, "_enact_handlers", None)
            if isinstance(base_enact, dict):
                enact_handlers.update(base_enact)
            for name in vars(base):
                method = vars(base)[name]
                ch = getattr(method, "_listen_channel", None)
                if ch is not None:
                    listen_handlers[ch] = name
                cmd = getattr(method, "_enact_command", None)
                if cmd is not None:
                    enact_handlers[cmd] = name

        cls._listen_handlers = listen_handlers
        cls._enact_handlers = enact_handlers

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bus = ChannelBus()
        self._inbound_stats = ChannelStats()  # tracks @listen inbound messages
        self._children: list[CogletHandle] = []
        self._runtime: Any = None  # set by CogletRuntime
        self._handle: Any = None  # set by CogletRuntime

    @property
    def handle(self) -> CogletHandle:
        """This coglet's own handle (for self-linking)."""
        return self._handle

    # --- LET: transmit ---

    async def transmit(self, channel: str, data: Any) -> None:
        await self._bus.transmit(channel, data)

    def transmit_sync(self, channel: str, data: Any) -> None:
        self._bus.transmit_nowait(channel, data)

    # --- COG: create, observe, guide ---

    async def create(self, config: CogBase) -> CogletHandle:
        if self._runtime is None:
            raise RuntimeError("Coglet not attached to a runtime")
        handle: CogletHandle = await self._runtime.spawn(config, parent=self)
        self._children.append(handle)
        return handle

    def link(self, src: CogletHandle, src_channel: str, dest: CogletHandle, dest_channel: str):
        """Wire src's output channel to dest's input channel via the runtime."""
        if self._runtime is None:
            raise RuntimeError("Coglet not attached to a runtime")
        return self._runtime.link(src, src_channel, dest, dest_channel)

    async def send(self, handle: CogletHandle, channel: str, data: Any) -> None:
        """Send data to a child's channel."""
        if self._runtime is None:
            raise RuntimeError("Coglet not attached to a runtime")
        await self._runtime.send(handle, channel, data)

    async def observe(self, handle: CogletHandle, channel: str) -> AsyncIterator[Any]:
        async for data in handle.observe(channel):
            yield data

    async def guide(self, handle: CogletHandle, command: Command) -> None:
        await handle.guide(command)

    # --- Supervision hook ---

    async def on_child_error(self, handle: CogletHandle, error: Exception) -> str:
        """Called when a child coglet errors. Override to customize.

        Return:
            "restart" — restart the child (respects CogBase limits)
            "stop"    — stop the child (default)
            "escalate" — re-raise the error in this coglet
        """
        return "stop"

    # --- Internal dispatch ---

    async def _dispatch_listen(self, channel: str, data: Any) -> None:
        self._inbound_stats.record(channel, data)
        # Push to bus so linked subscribers (from runtime.link()) see this data
        await self._bus.transmit(channel, data)
        method_name = self._listen_handlers.get(channel)
        if method_name is None:
            return
        method = getattr(self, method_name)
        result = method(data)
        if hasattr(result, "__await__"):
            await result

    async def _dispatch_enact(self, command: Command) -> None:
        method_name = self._enact_handlers.get(command.type)
        if method_name is None:
            return
        method = getattr(self, method_name)
        result = method(command.data)
        if hasattr(result, "__await__"):
            await result
