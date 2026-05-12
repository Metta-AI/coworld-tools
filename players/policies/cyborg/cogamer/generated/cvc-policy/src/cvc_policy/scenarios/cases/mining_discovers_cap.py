"""S2 mining_discovers_cap — tier 1.

Tutorial miner mission, 1 cog, seed 42. Pre-grants miner gear via
config-level setup so the agent skips gear fetch and goes straight
to mining. CargoCapTracker should observe the first cap_discovered
event early in the run.

Calibrated against seed=42 on 2026-04-13: first cap_discovered fires
at step 29 with cap=200 on tutorial.miner. We assert by_step=55 as
a loose bound that still catches regressions.
"""

from __future__ import annotations

from typing import Any

from cvc_policy.scenarios import Scenario, scenario
from cvc_policy.scenarios.assertions import cap_discovered_by, no_crash


def _grant_miner_gear(env_cfg: Any) -> None:
    env_cfg.game.agents[0].inventory.initial["miner"] = 1


@scenario
def mining_discovers_cap() -> Scenario:
    return Scenario(
        name="mining_discovers_cap",
        tier=1,
        mission="tutorial.miner",
        cogs=1,
        steps=100,
        seed=42,
        setup=_grant_miner_gear,
        assertions=[
            no_crash(),
            cap_discovered_by(
                agent=0, gear_sig=("miner",), expected_cap=200, by_step=55
            ),
        ],
    )
