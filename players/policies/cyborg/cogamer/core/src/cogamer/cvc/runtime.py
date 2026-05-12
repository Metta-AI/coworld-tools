"""CogletRuntime — boots and manages a coglet supervision tree on asyncio.

Responsibilities:
  - spawn/shutdown: lifecycle management with LifeLet/TickLet integration
  - tree(): ASCII visualization of the live coglet hierarchy
  - Restart: exponential backoff restart via on_child_error + CogBase policy
  - Tracing: optional jsonl event recording via CogletTrace
"""

from __future__ import annotations

import asyncio
from typing import Any

from cogamer.cvc.coglet import Coglet
from cogamer.cvc.handle import CogBase, CogletHandle
from cogamer.cvc.lifelet import LifeLet
from cogamer.cvc.ticklet import TickLet
from cogamer.cvc.trace import CogletTrace


class CogletRuntime:
    """Boots and manages a Coglet tree on asyncio."""

    def __init__(self, trace: CogletTrace | None = None):
        self._handles: list[CogletHandle] = []
        self._coglets: list[Coglet] = []
        self._configs: dict[int, CogBase] = {}  # id(coglet) -> config
        self._parents: dict[int, Coglet] = {}  # id(coglet) -> parent
        self._restart_counts: dict[int, int] = {}  # id(coglet) -> count
        self._trace = trace
        self._on_spawn: list[Any] = []  # callbacks: (handle, config, parent) -> None
        self._on_link: list[Any] = []  # callbacks: (src, src_ch, dest, dest_ch, task) -> None

    def _instantiate(self, config: CogBase) -> Coglet:
        coglet = config.cls(**config.kwargs)
        coglet._runtime = self
        if self._trace:
            self._install_trace(coglet)
        return coglet

    def _install_trace(self, coglet: Coglet) -> None:
        """Wrap transmit and _dispatch_enact to record trace events."""
        trace = self._trace
        coglet_name = type(coglet).__name__

        original_transmit = coglet.transmit

        async def traced_transmit(channel: str, data: Any) -> None:
            trace.record(coglet_name, "transmit", channel, data)
            await original_transmit(channel, data)

        coglet.transmit = traced_transmit  # type: ignore[assignment]

        original_dispatch = coglet._dispatch_enact

        async def traced_dispatch(command: Any) -> None:
            trace.record(coglet_name, "enact", command.type, command.data)
            await original_dispatch(command)

        coglet._dispatch_enact = traced_dispatch  # type: ignore[assignment]

    async def spawn(self, config: CogBase, parent: Coglet | None = None) -> CogletHandle:
        coglet = self._instantiate(config)
        handle = CogletHandle(coglet)
        coglet._handle = handle
        self._handles.append(handle)
        self._coglets.append(coglet)
        self._configs[id(coglet)] = config
        if parent is not None:
            self._parents[id(coglet)] = parent
        self._restart_counts[id(coglet)] = 0

        for cb in self._on_spawn:
            cb(handle, config, parent)

        if isinstance(coglet, LifeLet):
            await coglet.on_start()

        if isinstance(coglet, TickLet):
            await coglet._start_tickers()

        return handle

    async def run(self, config: CogBase) -> CogletHandle:
        """Boot a root coglet and return its handle."""
        return await self.spawn(config)

    def link(self, src: CogletHandle, src_channel: str, dest: CogletHandle, dest_channel: str) -> asyncio.Task:
        """Wire src's transmit channel to dest's @listen handler.

        Returns the background task piping data. Cancel it to unlink.
        """
        sub = src.coglet._bus.subscribe(src_channel)

        async def _pipe():
            try:
                async for data in sub:
                    try:
                        await dest.coglet._dispatch_listen(dest_channel, data)
                    except Exception as e:
                        import traceback

                        print(f"[link] error in {dest_channel}: {e}")
                        traceback.print_exc()
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_pipe())
        # Notify listeners (e.g. CLI registry)
        for cb in self._on_link:
            cb(src, src_channel, dest, dest_channel, task)
        return task

    async def send(self, handle: CogletHandle, channel: str, data: Any) -> None:
        """Send data to a coglet's channel (fires handler + pushes to bus)."""
        await handle.coglet._dispatch_listen(channel, data)

    async def shutdown(self) -> None:
        """Stop all coglets in reverse order."""
        for coglet in reversed(self._coglets):
            if isinstance(coglet, TickLet):
                await coglet._stop_tickers()
            if isinstance(coglet, LifeLet):
                await coglet.on_stop()
        self._coglets.clear()
        self._handles.clear()
        self._configs.clear()
        self._parents.clear()
        self._restart_counts.clear()
        if self._trace:
            self._trace.close()

    # --- Supervision: restart ---

    async def handle_child_error(self, handle: CogletHandle, error: Exception) -> None:
        """Process a child error according to config and parent policy."""
        coglet = handle.coglet
        config = self._configs.get(id(coglet))
        parent = self._parents.get(id(coglet))

        # Ask parent what to do
        action = "stop"
        if parent is not None:
            action = await parent.on_child_error(handle, error)

        if action == "escalate":
            raise error

        if action == "restart" and config and config.restart != "never":
            count = self._restart_counts.get(id(coglet), 0)
            if count < config.max_restarts:
                await self._restart_child(handle, config, count)
                return

        # Default: stop the child
        await self._stop_coglet(coglet)

    async def _restart_child(self, handle: CogletHandle, config: CogBase, restart_count: int) -> None:
        old_coglet = handle.coglet
        await self._stop_coglet(old_coglet)

        delay = config.backoff_s * (2**restart_count)
        await asyncio.sleep(delay)

        new_coglet = self._instantiate(config)
        handle._coglet = new_coglet
        self._coglets.append(new_coglet)
        self._configs[id(new_coglet)] = config
        parent = self._parents.get(id(old_coglet))
        if parent:
            self._parents[id(new_coglet)] = parent
        self._restart_counts[id(new_coglet)] = restart_count + 1

        if isinstance(new_coglet, LifeLet):
            await new_coglet.on_start()
        if isinstance(new_coglet, TickLet):
            await new_coglet._start_tickers()

    def _get_descendants(self, coglet: Coglet) -> list[Coglet]:
        """Get all descendants of a coglet (depth-first)."""
        descendants = []
        for child_handle in coglet._children:
            descendants.append(child_handle.coglet)
            descendants.extend(self._get_descendants(child_handle.coglet))
        return descendants

    async def _stop_coglet(self, coglet: Coglet) -> None:
        """Stop a coglet and all its descendants (children first)."""
        # Collect all descendants, stop in reverse (leaves first)
        descendants = self._get_descendants(coglet)
        for desc in reversed(descendants):
            await self._stop_one(desc)
        await self._stop_one(coglet)
        # Remove from parent's children list
        parent = self._parents.get(id(coglet))
        if parent:
            parent._children = [h for h in parent._children if h.coglet is not coglet]

    async def _stop_one(self, coglet: Coglet) -> None:
        """Stop a single coglet (no cascade)."""
        if isinstance(coglet, TickLet):
            await coglet._stop_tickers()
        if isinstance(coglet, LifeLet):
            await coglet.on_stop()
        if coglet in self._coglets:
            self._coglets.remove(coglet)
        self._configs.pop(id(coglet), None)
        self._parents.pop(id(coglet), None)
        self._restart_counts.pop(id(coglet), None)

    # --- Tree visualization ---

    def tree(self, id_map: dict[int, str] | None = None) -> str:
        """Return ASCII visualization of the coglet tree.

        *id_map* maps ``id(coglet)`` → registry ID string so that IDs
        are shown next to each node.
        """
        roots = [c for c in self._coglets if id(c) not in self._parents]
        if not roots:
            return "CogletRuntime (empty)"
        lines = ["CogletRuntime"]
        for i, root in enumerate(roots):
            self._tree_node(root, lines, prefix="", is_last=(i == len(roots) - 1), id_map=id_map)
        return "\n".join(lines)

    def _tree_node(
        self,
        coglet: Coglet,
        lines: list[str],
        prefix: str,
        is_last: bool,
        id_map: dict[int, str] | None = None,
    ) -> None:
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        mixins = [
            cls.__name__
            for cls in type(coglet).__mro__
            if cls.__name__.endswith("Let") and cls.__name__ not in ("Coglet",)
        ]
        name = type(coglet).__name__
        cid = (id_map or {}).get(id(coglet), "")
        id_str = f" ({cid})" if cid else ""
        mixin_str = f" [{', '.join(mixins)}]" if mixins else ""
        lines.append(f"{prefix}{connector}{name}{id_str}{mixin_str}")

        child_prefix = prefix + ("    " if is_last else "\u2502   ")

        # Channel stats
        subs = coglet._bus._subscribers
        if subs:
            ch_parts = []
            for ch_name, sub_list in subs.items():
                ch_parts.append(f"{ch_name}({len(sub_list)} subs)")
            lines.append(f"{child_prefix}channels: {', '.join(ch_parts)}")

        # Suppression info
        suppressed_ch = getattr(coglet, "_suppressed_channels", None)
        suppressed_cmd = getattr(coglet, "_suppressed_commands", None)
        suppressed = []
        if suppressed_ch:
            suppressed.append(f"channels={list(suppressed_ch)}")
        if suppressed_cmd:
            suppressed.append(f"commands={list(suppressed_cmd)}")
        if suppressed:
            lines.append(f"{child_prefix}suppressed: {', '.join(suppressed)}")

        # Children
        children = coglet._children
        for j, child_handle in enumerate(children):
            self._tree_node(
                child_handle.coglet,
                lines,
                child_prefix,
                is_last=(j == len(children) - 1),
                id_map=id_map,
            )
