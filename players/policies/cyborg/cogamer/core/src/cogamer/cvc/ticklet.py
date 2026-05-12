"""TickLet — mixin for periodic tick-based coglets.

Stub: the original coglet.ticklet was not present in the source repo.
Only the interface used by CogletRuntime is defined here.
"""

from __future__ import annotations


class TickLet:
    """Mixin for coglets that run periodic ticks."""

    async def _start_tickers(self) -> None:
        """Start periodic tick tasks."""

    async def _stop_tickers(self) -> None:
        """Stop periodic tick tasks."""
