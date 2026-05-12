"""LossCoglet — base class for loss computation in the PCO graph.

Listens on "experience" and "evaluation" channels. When both are received,
calls compute_loss() and transmits the result on "signal". Subclasses must
override compute_loss().
"""

from __future__ import annotations

from typing import Any

from cogamer.cvc.coglet import Coglet, listen


class LossCoglet(Coglet):
    """Abstract base for loss computation.

    Subclasses implement compute_loss(experience, evaluation) -> signal dict.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pending_experience: Any = None
        self._pending_evaluation: Any = None

    @listen("experience")
    async def _on_experience(self, data: Any) -> None:
        self._pending_experience = data
        await self._try_compute()

    @listen("evaluation")
    async def _on_evaluation(self, data: Any) -> None:
        self._pending_evaluation = data
        await self._try_compute()

    async def _try_compute(self) -> None:
        if self._pending_experience is None or self._pending_evaluation is None:
            return
        experience = self._pending_experience
        evaluation = self._pending_evaluation
        self._pending_experience = None
        self._pending_evaluation = None
        result = await self.compute_loss(experience, evaluation)
        await self.transmit("signal", result)

    async def compute_loss(self, experience: Any, evaluation: Any) -> Any:
        raise NotImplementedError("Subclasses must implement compute_loss()")
