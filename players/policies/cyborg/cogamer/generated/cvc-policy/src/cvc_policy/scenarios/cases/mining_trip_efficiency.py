"""S3 mining_trip_efficiency — tier 1.

Extends mining_discovers_cap to a longer run and asserts no single
mining trip after cap discovery exceeds a cap-derived bump budget.

Trip segmentation counts bumps from a single target position; a
change of target (or end of run) closes the trip. `max_bumps_per_trip`
is calibrated against seed=42 on 2026-04-13: observed max across
46 post-discovery trips was 36, covering the worst case of mining
an extractor to fill a nearly-empty cargo up to cap=200. We assert
<= 40 to leave a small regression margin.
"""

from __future__ import annotations

from typing import Any

from cvc_policy.scenarios import Scenario, scenario
from cvc_policy.scenarios.assertions import mining_trips_efficient, no_crash


def _grant_miner_gear(env_cfg: Any) -> None:
    env_cfg.game.agents[0].inventory.initial["miner"] = 1


@scenario
def mining_trip_efficiency() -> Scenario:
    return Scenario(
        name="mining_trip_efficiency",
        tier=1,
        mission="tutorial.miner",
        cogs=1,
        steps=400,
        seed=42,
        setup=_grant_miner_gear,
        assertions=[
            no_crash(),
            mining_trips_efficient(agent=0, max_bumps_per_trip=40),
        ],
    )
