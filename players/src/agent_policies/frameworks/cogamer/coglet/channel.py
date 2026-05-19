"""Async pub/sub channel system for coglet communication.

Each Coglet owns a ChannelBus. transmit() pushes data to all subscribers on a
named channel. Each subscribe() call creates an independent queue — no message
loss from slow consumers, but subscribers must exist before transmit (no replay).

ChannelStats tracks message counts in rolling windows (1s, 5s, 60s, 1h, 24h)
and retains the last N messages per channel.
"""

from __future__ import annotations

import asyncio
import collections
import time
from typing import Any, AsyncIterator

# Rolling window durations in seconds
STAT_WINDOWS = {"1s": 1, "5s": 5, "60s": 60, "1h": 3600, "24h": 86400}
HISTORY_SIZE = 100  # last N messages retained per channel


class ChannelStats:
    """Track message counts in rolling time windows and retain recent history."""

    def __init__(self):
        # deque of timestamps per channel
        self._timestamps: dict[str, collections.deque] = {}
        # last N messages per channel (each entry: {"ts": monotonic, "data": ...})
        self._history: dict[str, collections.deque] = {}
        # Offset to convert monotonic → epoch
        self._epoch_offset = time.time() - time.monotonic()

    def record(self, channel: str, data: Any) -> None:
        now = time.monotonic()
        if channel not in self._timestamps:
            self._timestamps[channel] = collections.deque()
            self._history[channel] = collections.deque(maxlen=HISTORY_SIZE)
        self._timestamps[channel].append(now)
        self._history[channel].append({"ts": now, "data": data})

    def counts(self, channel: str) -> dict[str, int]:
        """Return message counts for each window."""
        now = time.monotonic()
        ts = self._timestamps.get(channel, collections.deque())
        # Prune timestamps older than 24h
        cutoff = now - STAT_WINDOWS["24h"]
        while ts and ts[0] < cutoff:
            ts.popleft()
        result = {}
        for label, secs in STAT_WINDOWS.items():
            threshold = now - secs
            result[label] = sum(1 for t in ts if t >= threshold)
        return result

    def history(self, channel: str, n: int | None = None) -> list:
        """Return last N messages with epoch timestamps."""
        hist = self._history.get(channel, collections.deque())
        items = list(hist) if n is None else list(hist)[-n:]
        return [{"ts": entry["ts"] + self._epoch_offset, "data": entry["data"]} for entry in items]

    def all_counts(self) -> dict[str, dict[str, int]]:
        """Return counts for all channels."""
        return {ch: self.counts(ch) for ch in self._timestamps}


class Channel:
    """Single named async channel backed by an asyncio.Queue."""

    def __init__(self, maxsize: int = 0):
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)

    async def put(self, data: Any) -> None:
        await self._queue.put(data)

    def put_nowait(self, data: Any) -> None:
        self._queue.put_nowait(data)

    async def get(self) -> Any:
        return await self._queue.get()

    async def __aiter__(self) -> AsyncIterator[Any]:
        while True:
            yield await self.get()

    def subscribe(self) -> ChannelSubscription:
        """Create a new subscription (separate queue) for this channel."""
        return ChannelSubscription(self)


class ChannelSubscription:
    """Independent subscriber to a channel. Each subscriber gets its own queue."""

    def __init__(self, parent: Channel):
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._parent = parent

    async def get(self) -> Any:
        return await self._queue.get()

    async def __aiter__(self) -> AsyncIterator[Any]:
        while True:
            yield await self.get()


class ChannelBus:
    """Per-Coglet outbound channel registry.

    transmit() pushes to named channels. Observers subscribe to get
    independent async iterators over channel data. Stats are tracked
    per channel (message counts in rolling windows + last N messages).
    """

    def __init__(self):
        self._channels: dict[str, Channel] = {}
        self._subscribers: dict[str, list[ChannelSubscription]] = {}
        self.stats = ChannelStats()

    def _ensure_channel(self, name: str) -> Channel:
        if name not in self._channels:
            self._channels[name] = Channel()
            self._subscribers[name] = []
        return self._channels[name]

    async def transmit(self, channel: str, data: Any) -> None:
        self._ensure_channel(channel)
        self.stats.record(channel, data)
        for sub in self._subscribers[channel]:
            await sub._queue.put(data)

    def transmit_nowait(self, channel: str, data: Any) -> None:
        self._ensure_channel(channel)
        self.stats.record(channel, data)
        for sub in self._subscribers[channel]:
            sub._queue.put_nowait(data)

    def subscribe(self, channel: str) -> ChannelSubscription:
        self._ensure_channel(channel)
        sub = ChannelSubscription(self._channels[channel])
        self._subscribers[channel].append(sub)
        return sub
