"""Module-level structured logger access for Eurydice.

Eurydice modules are imported before ``policy.run`` creates the concrete
Orpheus ``Logger``.  A stable proxy lets modules use
``from .log import logger`` safely: the imported object stays the same, while
``set_logger`` swaps the underlying target at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orpheus.logging import Logger


class _LoggerProxy:
    """Falsey-until-configured proxy around an Orpheus ``Logger``."""

    def __init__(self) -> None:
        self._target: Logger | None = None

    def set(self, target: Logger | None) -> None:
        """Install or clear the active logger target."""

        self._target = target

    def __bool__(self) -> bool:
        return self._target is not None

    def event(self, category: str, data: dict, level: Any = "events") -> None:
        """Forward a structured event to the active logger if configured."""

        if self._target is not None:
            self._target.event(category, data, level)


logger = _LoggerProxy()


def set_logger(target: Logger | None) -> None:
    """Set the process-local Eurydice logger target."""

    logger.set(target)


__all__ = ["logger", "set_logger"]
