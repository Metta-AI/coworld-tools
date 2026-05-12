"""S4 empty_extractor_skipped — tier 1.

Reframed from the original design-doc form of "pre-drain a nearby
extractor, place a full one farther" — that version is not reachable
at MettaGridConfig level because ExtractorsVariant.initial_amount is
global. See design doc §7a.

This version asserts the same behavior via self-drain: whenever the
agent mines a target for >= `heavy_threshold` bumps (a proxy for
draining the extractor to empty within one trip), the agent's next
mining trip is at a different position. A regression that had the
agent re-target a freshly-drained extractor would trip this check.

Calibrated against seed=42 on 2026-04-13 on tutorial.miner with
miner gear granted: 46 post-discovery trips; heavy trips (>= 30
bumps) always switched target. heavy_threshold=30 picks up the
observed "big fill" trips without flagging ordinary top-ups.
"""

from __future__ import annotations

from typing import Any

from cvc_policy.scenarios import Scenario, scenario
from cvc_policy.scenarios.assertions import (
    after_heavy_trip_switches_target,
    no_crash,
)


def _grant_miner_gear(env_cfg: Any) -> None:
    env_cfg.game.agents[0].inventory.initial["miner"] = 1


@scenario
def empty_extractor_skipped() -> Scenario:
    return Scenario(
        name="empty_extractor_skipped",
        tier=1,
        mission="tutorial.miner",
        cogs=1,
        steps=400,
        seed=42,
        setup=_grant_miner_gear,
        assertions=[
            no_crash(),
            after_heavy_trip_switches_target(agent=0, heavy_threshold=30),
        ],
    )
