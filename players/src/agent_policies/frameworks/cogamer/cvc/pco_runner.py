"""PCO Runner — orchestrates PCO epochs between cogames episodes.

Provides an ExperienceActor that replays collected experience and a
``run_pco_epoch()`` helper that wires up the full PCO graph (actor,
critic, losses, constraints, learner) and runs one optimisation epoch.
"""

from __future__ import annotations

from typing import Any

from agent_policies.frameworks.cogamer.cvc.coglet import Coglet, enact
from agent_policies.frameworks.cogamer.cvc.constraints import SafetyConstraint, SyntaxConstraint
from agent_policies.frameworks.cogamer.cvc.critic import CvCCritic
from agent_policies.frameworks.cogamer.cvc.handle import CogBase
from agent_policies.frameworks.cogamer.cvc.learner import CvCLearner
from agent_policies.frameworks.cogamer.cvc.lifelet import LifeLet
from agent_policies.frameworks.cogamer.cvc.losses import JunctionLoss, ResourceLoss, SurvivalLoss
from agent_policies.frameworks.cogamer.cvc.proglet import Program
from agent_policies.frameworks.cogamer.cvc.runtime import CogletRuntime
from agent_policies.frameworks.cogamer.pco.optimizer import ProximalCogletOptimizer


class ExperienceActor(Coglet, LifeLet):
    """Holds collected experience and program references.

    The PCO optimizer guides this actor with "run" to replay experience
    and "update" to apply patches from the learner.
    """

    def __init__(
        self,
        experience: list[dict],
        programs: dict[str, Program] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.experience = experience
        self.programs: dict[str, Program] = programs or {}

    @enact("run")
    async def run_rollout(self, data: Any) -> None:
        """Transmit stored experience on the 'experience' channel."""
        await self.transmit("experience", self.experience)

    @enact("update")
    async def apply_update(self, patch: Any) -> None:
        """Apply a patch dict to the programs table."""
        if isinstance(patch, dict):
            self.programs.update(patch)


async def run_pco_epoch(
    experience: list[dict],
    programs: dict[str, Program],
    client: Any | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Run one PCO epoch over the given experience and programs.

    Args:
        experience: List of game snapshot dicts collected during play.
        programs: Current program table (name -> Program).
        client: Optional Anthropic client for the learner LLM calls.
        max_retries: Number of learner retries on constraint rejection.

    Returns:
        Result dict from the optimizer with keys: accepted, reason,
        signals, patch.
    """
    learner = CvCLearner(client=client, current_programs=programs)

    runtime = CogletRuntime()
    handle = await runtime.spawn(
        CogBase(
            cls=ProximalCogletOptimizer,
            kwargs=dict(
                actor_config=CogBase(
                    cls=ExperienceActor,
                    kwargs=dict(experience=experience, programs=programs),
                ),
                critic_config=CogBase(cls=CvCCritic),
                losses=[ResourceLoss(), JunctionLoss(), SurvivalLoss()],
                constraints=[SyntaxConstraint(), SafetyConstraint()],
                learner=learner,
                max_retries=max_retries,
            ),
        )
    )

    pco = handle.coglet
    result = await pco.run_epoch()
    await runtime.shutdown()
    return result
