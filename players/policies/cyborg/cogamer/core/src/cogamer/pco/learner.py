"""LearnerCoglet — observes experience and produces actor/critic updates.

Receives the full epoch context (experience, evaluation, loss signals)
and produces an update for the actor and critic.
"""

from __future__ import annotations

from typing import Any

from cogamer.cvc.coglet import Coglet, listen


class LearnerCoglet(Coglet):
    """Abstract base for learner coglets.

    Subclasses must implement learn(experience, evaluation, signals) -> update dict.
    """

    @listen("context")
    async def _on_context(self, context: Any) -> None:
        result = await self.learn(
            experience=context["experience"],
            evaluation=context["evaluation"],
            signals=context["signals"],
        )
        await self.transmit("update", result)

    async def learn(
        self,
        experience: Any,
        evaluation: Any,
        signals: list[Any],
    ) -> Any:
        raise NotImplementedError("Subclasses must implement learn()")
