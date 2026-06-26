"""A champion promoted after the round was scheduled must still be seated that round."""

from __future__ import annotations

import uuid
from pathlib import Path

import yaml

from commissioners.common.commissioners import RulesetStrategyCommissioner
from commissioners.common.protocol import (
    DivisionInfo,
    LeagueInfo,
    MembershipInfo,
    RoundStart,
    VariantInfo,
)

_CONFIG_DIR = Path(__file__).parents[1] / "commissioners" / "ruleset_strategy_commissioner" / "configs"


def test_champion_promoted_after_scheduling_is_seated() -> None:
    config = yaml.safe_load((_CONFIG_DIR / "agricogla.yaml").read_text())
    commissioner = RulesetStrategyCommissioner(config)

    league_id, division_id = uuid.UUID(int=1), uuid.UUID(int=10)
    policy = {n: uuid.UUID(int=n) for n in range(1, 5)}  # champions A, B, C, D
    memberships = [
        MembershipInfo(
            id=uuid.UUID(int=50 + n),
            league_id=league_id,
            division_id=division_id,
            policy_version_id=policy[n],
            player_id=f"ply_{uuid.UUID(int=500 + n)}",
            status="competing",
            substatus="active",
            is_champion=True,
        )
        for n in range(1, 5)
    ]
    # The round was scheduled with only A, B, C; D was promoted (uploaded) afterwards.
    state = {
        "round_config": {
            "current_division_id": str(division_id),
            "entrant_policy_version_ids": [str(policy[1]), str(policy[2]), str(policy[3])],
        }
    }
    round_start = RoundStart(
        round_id=uuid.UUID(int=1000),
        round_number=1,
        league=LeagueInfo(id=league_id, commissioner_key="config_driven", commissioner_config={}),
        divisions=[DivisionInfo(id=division_id, name="Competition", level=1, type="competition")],
        memberships=memberships,
        recent_results=[],
        variants=[VariantInfo(id="default", name="default", game_config={"num_agents": 4})],
        state=state,
    )

    schedule = commissioner.schedule_episodes_for_round_start(round_start)
    seated = {str(pv) for episode in schedule.episodes for pv in episode.policy_version_ids}

    # the late-promoted champion D is seated this round, not held out
    assert str(policy[4]) in seated
    assert all(str(policy[n]) in seated for n in range(1, 5))
