"""S1 exploration_small — tier 1.

Tutorial mission with miner variant, 1 cog, 300 steps. Asserts the
agent accumulated meaningful world-model state during the run.

We use `known_entities_at_least` — an honest entity count — as a
direct signal that observation processing ran and the agent moved
around. Calibrated against seed=42 on 2026-04-13: run produced
known_entities=112; we require >= 30 as a conservative lower bound.
Extractors are pruned from the world model when their cell is in view
and empty, so we cannot assert extractors_currently_known>0 at end
of run reliably.

See design doc §7a for the caveat.
"""

from __future__ import annotations

from cvc_policy.scenarios import Scenario, scenario
from cvc_policy.scenarios.assertions import known_entities_at_least, no_crash


@scenario
def exploration_small() -> Scenario:
    return Scenario(
        name="exploration_small",
        tier=1,
        mission="tutorial.miner",
        cogs=1,
        steps=300,
        seed=42,
        assertions=[
            no_crash(),
            known_entities_at_least(agent=0, minimum=30),
        ],
    )
