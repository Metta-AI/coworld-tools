"""ProximalCogletOptimizer — PPO expressed as a coglet graph.

Orchestrates one epoch of: rollout -> critic -> losses -> learner -> constraints,
then applies accepted updates to actor and critic.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cogamer.cvc.coglet import Coglet
from cogamer.cvc.handle import CogBase, CogletHandle, Command
from cogamer.cvc.lifelet import LifeLet
from cogamer.pco.constraint import ConstraintCoglet
from cogamer.pco.learner import LearnerCoglet
from cogamer.pco.loss import LossCoglet


class ProximalCogletOptimizer(Coglet, LifeLet):
    """Orchestrates the PCO training loop as a coglet graph.

    Creates actor and critic children on start, then run_epoch() drives
    one full cycle through rollout, evaluation, loss, learning, and
    constraint checking.
    """

    def __init__(
        self,
        actor_config: CogBase,
        critic_config: CogBase,
        losses: list[LossCoglet],
        constraints: list[ConstraintCoglet],
        learner: LearnerCoglet,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._actor_config = actor_config
        self._critic_config = critic_config
        self._losses = losses
        self._constraints = constraints
        self._learner = learner
        self._max_retries = max_retries
        self._actor_handle: CogletHandle | None = None
        self._critic_handle: CogletHandle | None = None

    async def on_start(self) -> None:
        self._actor_handle = await self.create(self._actor_config)
        self._critic_handle = await self.create(self._critic_config)

    async def run_epoch(self, timeout: float = 5.0) -> dict[str, Any]:
        """Run one full PCO epoch and return a result dict."""
        actor = self._actor_handle
        critic = self._critic_handle

        # 1. Rollout: guide actor to run, collect experience
        exp_sub = actor.coglet._bus.subscribe("experience")
        await self.guide(actor, Command("run"))
        experience = await asyncio.wait_for(exp_sub.get(), timeout=timeout)

        # 2. Critic: dispatch experience, collect evaluation
        eval_sub = critic.coglet._bus.subscribe("evaluation")
        await critic.coglet._dispatch_listen("experience", experience)
        evaluation = await asyncio.wait_for(eval_sub.get(), timeout=timeout)

        # 3. Losses: dispatch (experience, evaluation) to each, collect signals
        signals = []
        signal_subs = []
        for loss in self._losses:
            sub = loss._bus.subscribe("signal")
            signal_subs.append(sub)
            await loss._dispatch_listen("experience", experience)
            await loss._dispatch_listen("evaluation", evaluation)

        for sub in signal_subs:
            signal = await asyncio.wait_for(sub.get(), timeout=timeout)
            signals.append(signal)

        # 4-6. Learner -> Constraints loop with retries
        accepted = False
        reason = None
        update = None
        learner_context = {
            "experience": experience,
            "evaluation": evaluation,
            "signals": signals,
        }

        for _attempt in range(self._max_retries):
            # 4. Learner: dispatch full context, collect update
            update_sub = self._learner._bus.subscribe("update")
            await self._learner._dispatch_listen("context", learner_context)
            update = await asyncio.wait_for(update_sub.get(), timeout=timeout)

            # 5. Constraints: dispatch patch to each, collect verdicts
            verdicts = []
            verdict_subs = []
            for constraint in self._constraints:
                sub = constraint._bus.subscribe("verdict")
                verdict_subs.append(sub)
                await constraint._dispatch_listen("update", update)

            for sub in verdict_subs:
                verdict = await asyncio.wait_for(sub.get(), timeout=timeout)
                verdicts.append(verdict)

            # 6. Check acceptance
            accepted = all(v.get("accepted", False) for v in verdicts)
            if accepted:
                reason = None
                break

            reasons = [v.get("reason", "rejected") for v in verdicts if not v.get("accepted", False)]
            reason = "; ".join(reasons)

            # Feed rejection back as additional context for next attempt
            learner_context = {
                "experience": experience,
                "evaluation": evaluation,
                "signals": signals + [{"rejection": reason}],
            }

        # 7. If accepted, apply update to actor and critic
        if accepted:
            await self.guide(actor, Command("update", update))
            await self.guide(critic, Command("update", update))

        return {
            "accepted": accepted,
            "reason": reason,
            "signals": signals,
            "patch": update,
        }

    async def run(self, num_epochs: int) -> list[dict[str, Any]]:
        """Run multiple epochs, transmitting each result on the 'epoch' channel."""
        results = []
        for _ in range(num_epochs):
            result = await self.run_epoch()
            await self.transmit("epoch", result)
            results.append(result)
        return results
