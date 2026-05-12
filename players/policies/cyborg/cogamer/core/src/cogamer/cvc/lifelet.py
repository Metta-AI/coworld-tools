"""LifeLet mixin — process lifecycle hooks (on_start / on_stop).

Called by CogletRuntime during spawn() and shutdown(). Raising in either
aborts the transition. Shutdown calls on_stop in reverse spawn order (LIFO).
"""

from __future__ import annotations


class LifeLet:
    """Mixin: process lifecycle hooks.

    on_start() — called when the coglet process starts.
    on_stop()  — called on shutdown.
    Raising in either aborts the transition.
    """

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass
