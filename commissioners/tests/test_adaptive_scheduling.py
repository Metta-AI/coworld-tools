"""Adaptive (uncertainty-weighted) two-team scheduling."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml

from commissioners.common.commissioners import RulesetStrategyCommissioner
from commissioners.common.protocol import (
    DivisionInfo,
    LeagueInfo,
    MembershipInfo,
    RecentResult,
    RoundStart,
    VariantInfo,
)
from commissioners.common.ruleset_strategy.config import (
    AdaptiveScheduleConfig,
    RulesetStrategyCommissionerConfig,
)
from commissioners.common.ruleset_strategy.uncertainty import (
    entrant_uncertainties,
    episode_budget,
)

CONFIG_DIR = (
    Path(__file__).parents[1]
    / "commissioners"
    / "ruleset_strategy_commissioner"
    / "configs"
)

CONFIG = AdaptiveScheduleConfig(enabled=True)


def _ruleset_config(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / f"{name}.yaml").read_text())


def _round_start(
    *,
    policy_version_ids: list[UUID],
    num_agents: int,
    division_id: UUID | None = None,
) -> RoundStart:
    active_division_id = division_id or uuid4()
    league_id = uuid4()
    return RoundStart(
        round_id=uuid4(),
        round_number=1,
        league=LeagueInfo(id=league_id, commissioner_config={}),
        divisions=[
            DivisionInfo(
                id=active_division_id, name="Competition", level=1, type="competition"
            )
        ],
        memberships=[
            MembershipInfo(
                id=uuid4(),
                league_id=league_id,
                division_id=active_division_id,
                policy_version_id=policy_version_id,
                player_id=f"player-{index}",
                status="competing",
                substatus="active",
                is_champion=True,
            )
            for index, policy_version_id in enumerate(policy_version_ids)
        ],
        recent_results=[],
        variants=[
            VariantInfo(
                id="default", name="Default", game_config={"num_agents": num_agents}
            )
        ],
        state=None,
    )


def _results(
    policy_scores: dict[UUID, list[float]],
    *,
    division_id: UUID,
    episodes_per_round: int | None = None,
) -> list[RecentResult]:
    """One completed round per score index, every policy with a score in each round it has one."""
    metadata = {"completed_episode_count": episodes_per_round} if episodes_per_round else {}
    rounds: dict[int, UUID] = {}
    results: list[RecentResult] = []
    for policy_version_id, scores in policy_scores.items():
        for round_number, score in enumerate(scores):
            round_id = rounds.setdefault(round_number, uuid4())
            results.append(
                RecentResult(
                    round_id=round_id,
                    division_id=division_id,
                    round_number=round_number,
                    policy_version_id=policy_version_id,
                    rank=1,
                    score=score,
                    result_metadata=metadata,
                )
            )
    return results


def _appearances(schedule) -> dict[UUID, int]:
    counts: dict[UUID, int] = defaultdict(int)
    for episode in schedule.episodes:
        for policy_version_id in set(episode.policy_version_ids):
            counts[policy_version_id] += 1
    return counts


def test_uncertainty_new_policy_is_fully_uncertain() -> None:
    policy = uuid4()
    parts = entrant_uncertainties([policy], [], CONFIG)[policy]
    assert parts.rounds_on_record == 0
    assert parts.newness == 1.0
    assert parts.value == 1.0


def test_uncertainty_flat_veteran_is_settled() -> None:
    policy = uuid4()
    division = uuid4()
    results = _results({policy: [0.5] * 8}, division_id=division)
    parts = entrant_uncertainties([policy], results, CONFIG)[policy]
    assert parts.rounds_on_record == 8
    assert parts.newness == 0.0
    assert parts.volatility == 0.0
    assert parts.trend == 0.0
    assert parts.value == 0.0


def test_uncertainty_trending_veteran_is_uncertain() -> None:
    policy = uuid4()
    division = uuid4()
    # Flat at 0.9 for 5 rounds, then a sustained drop to 0.3: trend saturates.
    results = _results({policy: [0.9] * 5 + [0.3] * 3}, division_id=division)
    parts = entrant_uncertainties([policy], results, CONFIG)[policy]
    assert parts.newness == 0.0
    assert parts.trend == 1.0
    assert parts.value == 1.0


def test_uncertainty_volatile_veteran_is_uncertain() -> None:
    policy = uuid4()
    division = uuid4()
    results = _results({policy: [0.2, 0.8] * 4}, division_id=division)
    parts = entrant_uncertainties([policy], results, CONFIG)[policy]
    assert parts.volatility == 1.0


def test_episode_budget_interpolates_and_clamps() -> None:
    assert episode_budget(0.0, min_episodes=4, max_episodes=16) == 4
    assert episode_budget(1.0, min_episodes=4, max_episodes=16) == 16
    assert episode_budget(0.5, min_episodes=4, max_episodes=16) == 10
    assert (
        episode_budget(1.0, min_episodes=4, max_episodes=2) == 4
    )  # ceiling below floor


def test_ctf_adaptive_no_history_schedules_dense_interleaved_round() -> None:
    """With no history everyone is new: everyone gets the ceiling, seats stay interleaved."""
    policy_version_ids = [uuid4() for _ in range(3)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=16,
    )

    commissioner = RulesetStrategyCommissioner(_ruleset_config("ctf"))
    schedule = commissioner.schedule_episodes_for_round_start(round_start)

    appearances = _appearances(schedule)
    for policy_version_id in policy_version_ids:
        assert appearances[policy_version_id] >= 16
    # Each episode consumes at least one unit of budget, so the round is bounded.
    assert len(schedule.episodes) <= 3 * 16
    for episode in schedule.episodes:
        assert len(episode.policy_version_ids) == 16
        red_team = set(episode.policy_version_ids[0::2])
        blue_team = set(episode.policy_version_ids[1::2])
        assert len(red_team) == 1
        assert len(blue_team) == 1
        assert red_team != blue_team


def test_ctf_adaptive_new_entrant_outschedules_settled_field() -> None:
    """A new champion gets the ceiling while flat veterans stay near the floor."""
    division_id = uuid4()
    veterans = [uuid4() for _ in range(5)]
    newcomer = uuid4()
    round_start = _round_start(
        policy_version_ids=[*veterans, newcomer],
        num_agents=16,
        division_id=division_id,
    )
    # Veterans have 8 flat rounds on record; the newcomer's only history is a
    # qualifier crash-check round, which must not count as settling evidence.
    round_start.recent_results = [
        *_results(
            {veteran: [0.5] * 8 for veteran in veterans}, division_id=division_id
        ),
        *_results({newcomer: [1.0]}, division_id=uuid4()),
    ]

    commissioner = RulesetStrategyCommissioner(_ruleset_config("ctf"))
    schedule = commissioner.schedule_episodes_for_round_start(round_start)

    appearances = _appearances(schedule)
    assert appearances[newcomer] >= 16
    for veteran in veterans:
        assert appearances[veteran] >= 4  # floor honored
        # Floor + incidental episodes drafted by the newcomer's cycles, spread
        # across the field — well below the newcomer's ceiling.
        assert appearances[veteran] < appearances[newcomer]
    # The whole round is far smaller than the uniform 10-episodes-each schedule
    # (6 entrants -> 30 episodes) while still sampling the newcomer harder.
    assert len(schedule.episodes) < 30


def test_ctf_adaptive_max_round_episodes_caps_all_new_field() -> None:
    config = _ruleset_config("ctf")
    config["defaults"]["adaptive"]["max_round_episodes"] = 10
    policy_version_ids = [uuid4() for _ in range(8)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=16,
    )

    schedule = RulesetStrategyCommissioner(config).schedule_episodes_for_round_start(
        round_start
    )

    assert len(schedule.episodes) == 10


def test_max_episodes_per_entrant_requires_adaptive() -> None:
    config = _ruleset_config("ctf")
    config["defaults"]["adaptive"]["enabled"] = False
    with pytest.raises(ValueError, match="max_episodes_per_entrant requires"):
        RulesetStrategyCommissionerConfig.from_mapping(config)


def test_stage_ceiling_below_floor_rejected() -> None:
    config = _ruleset_config("ctf")
    config["defaults"]["stage"]["max_episodes_per_entrant"] = 2
    with pytest.raises(ValueError, match="max_episodes_per_entrant must be >="):
        RulesetStrategyCommissionerConfig.from_mapping(config)


def test_uncertainty_noisy_but_stable_win_rates_stay_settled() -> None:
    """Round-899 regression: binomial sampling noise alone must not saturate the signals.

    A stable mid-field policy's win rate over ~10 episodes has sampling std ~0.16 —
    above the volatility scale. Without the noise floor every veteran in the live
    field read vol=1.00/trend=1.00 and the whole round went dense.
    """
    policy = uuid4()
    division = uuid4()
    results = _results(
        {policy: [0.5, 0.6, 0.4, 0.7, 0.5, 0.4, 0.6, 0.5]},
        division_id=division,
        episodes_per_round=10,
    )
    parts = entrant_uncertainties([policy], results, CONFIG)[policy]
    assert parts.volatility == 0.0
    assert parts.trend == 0.0
    assert parts.value == 0.0


def test_uncertainty_true_regime_shift_clears_noise_floor() -> None:
    policy = uuid4()
    division = uuid4()
    results = _results(
        {policy: [0.9, 0.9, 0.9, 0.9, 0.9, 0.3, 0.3, 0.3]},
        division_id=division,
        episodes_per_round=10,
    )
    parts = entrant_uncertainties([policy], results, CONFIG)[policy]
    assert parts.trend == 1.0
