"""ConstraintCoglet — abstract base for patch constraint checks.

Listens on "update" for a patch, calls the abstract check() method,
and transmits the result on "verdict".
"""

from __future__ import annotations

from typing import Any

from cogamer.cvc.coglet import Coglet, listen


class ConstraintCoglet(Coglet):
    """Base class for constraint coglets.

    Subclasses must implement check(patch) -> dict with at least {"accepted": bool}.
    """

    @listen("update")
    async def _on_update(self, patch: Any) -> None:
        result = await self.check(patch)
        await self.transmit("verdict", result)

    async def check(self, patch: Any) -> dict:
        """Evaluate a patch and return a verdict dict.

        Must return at minimum {"accepted": True/False}.
        Override in subclasses.
        """
        raise NotImplementedError("subclasses must implement check()")
