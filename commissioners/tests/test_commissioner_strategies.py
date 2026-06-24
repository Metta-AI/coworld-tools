from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml

from commissioners.common.models import PolicyMembershipEventChange
from commissioners.common.protocol import (
    DescribeDivisionRequest,
    DivisionInfo,
    EpisodeFailed as ProtocolEpisodeFailed,
    EpisodeRequest as ProtocolEpisodeRequest,
    EpisodeResult as ProtocolEpisodeResult,
    EpisodeScore,
    LeaderboardRoundResultInfo,
    LeagueInfo,
    LeagueMigrationConfigRequest,
    LeagueMigrationRequest,
    MembershipChange as ProtocolMembershipChange,
    MembershipInfo,
    RankDivisionRequest,
    RecentResult,
    RoundCompletedRequest,
    RoundConfig,
    RoundInfo,
    RoundResultInfo,
    ScheduleRoundsRequest,
    RoundStart,
    VariantInfo,
)
from commissioners.common.commissioners import (
    MEAN_ROUND_SCORE_KIND,
    MEAN_SCORE_EWMA_SCORING_MECHANICS,
    RANKED_SCORE_COUNT_METADATA_KEY,
    BaselineCommissioner,
    RulesetStrategyCommissioner,
    EpisodeResult,
    LeagueMigrationConfigContext,
    LeagueSnapshot,
    MembershipChange,
    OnRoundCompletedContext,
    OnRoundCompletedResult,
    PolicyPool,
    PolicyPoolEntry,
    Round,
    RoundSpec,
    RoundPolicyScore,
    V2RoundConfig,
    complete_round_for_round_start,
    describe_division_for_request,
    league_migration_config_for_request,
    migrate_league_for_request,
    rank_division_for_request,
    round_completed_for_request,
    schedule_episodes_for_round_start,
    schedule_rounds_for_request,
)

RULESET_CONFIG_DIR = Path(__file__).parents[1] / "commissioners" / "ruleset_strategy_commissioner" / "configs"


def _ruleset_config(name: str) -> dict:
    return yaml.safe_load((RULESET_CONFIG_DIR / f"{name}.yaml").read_text())


def _ruleset_commissioner(name: str) -> RulesetStrategyCommissioner:
    return RulesetStrategyCommissioner(_ruleset_config(name))


def test_baseline_commissioner_migration_config_echoes_current_divisions() -> None:
    league_id = uuid4()
    division_id = uuid4()

    response = league_migration_config_for_request(
        BaselineCommissioner(),
        LeagueMigrationConfigRequest(
            league=LeagueInfo(id=league_id, commissioner_config={}),
            divisions=[DivisionInfo(id=division_id, name="Existing", level=3, type="competition")],
        ),
    )

    assert response.divisions[0].name == "Existing"
    assert response.divisions[0].level == 3
    assert response.divisions[0].type == "competition"
    assert response.divisions[0].previous_name is None


def test_ruleset_strategy_migration_config_declares_divisions_from_commissioner_config() -> None:
    response = league_migration_config_for_request(
        _ruleset_commissioner("default"),
        LeagueMigrationConfigRequest(
            league=LeagueInfo(id=uuid4(), commissioner_config={}),
            divisions=[],
        ),
    )

    assert [(division.name, division.level, division.type) for division in response.divisions] == [
        ("Qualifiers", -99, "staging"),
        ("Competition", 1, "competition"),
    ]
    assert response.divisions[1].previous_name == "Daily"


@pytest.mark.parametrize("config_path", sorted(RULESET_CONFIG_DIR.glob("*.yaml")))
def test_ruleset_strategy_configs_declare_migration_divisions(config_path: Path) -> None:
    config = _ruleset_config(config_path.stem)
    raw_divisions = config["divisions"]
    assert raw_divisions["qualifiers"]["name"] == "Qualifiers"
    assert raw_divisions["qualifiers"]["level"] == -99
    assert raw_divisions["competition"]["name"] == "Competition"
    assert raw_divisions["competition"]["previous_name"] == "Daily"
    assert raw_divisions["competition"]["level"] == 1

    divisions = RulesetStrategyCommissioner(config).league_migration_config(
        LeagueMigrationConfigContext(
            league=LeagueSnapshot(id=uuid4(), commissioner_key="container", commissioner_config={}),
            divisions=[],
        )
    )
    assert [(division.name, division.previous_name) for division in divisions] == [
        ("Qualifiers", None),
        ("Competition", "Daily"),
    ]


def test_commissioner_migration_hook_defaults_to_no_membership_events() -> None:
    response = migrate_league_for_request(
        _ruleset_commissioner("default"),
        LeagueMigrationRequest(
            league=LeagueInfo(id=uuid4(), commissioner_config={}),
            divisions=[DivisionInfo(id=uuid4(), name="Competition", level=1, type="competition")],
            memberships=[],
        ),
    )

    assert response.policy_membership_events == []


def test_ruleset_strategy_migration_moves_legacy_dirt_and_wood_memberships() -> None:
    league_id = uuid4()
    dirt_id = uuid4()
    wood_id = uuid4()
    competition_id = uuid4()
    dirt_membership_id = uuid4()
    wood_membership_id = uuid4()

    response = migrate_league_for_request(
        _ruleset_commissioner("default"),
        LeagueMigrationRequest(
            league=LeagueInfo(id=league_id, commissioner_config={}),
            divisions=[
                DivisionInfo(id=dirt_id, name="Dirt", level=0, type="competition"),
                DivisionInfo(id=wood_id, name="Wood", level=1, type="competition"),
                DivisionInfo(id=competition_id, name="Competition", level=1, type="competition"),
            ],
            memberships=[
                MembershipInfo(
                    id=dirt_membership_id,
                    league_id=league_id,
                    division_id=dirt_id,
                    policy_version_id=uuid4(),
                    status="competing",
                ),
                MembershipInfo(
                    id=wood_membership_id,
                    league_id=league_id,
                    division_id=wood_id,
                    policy_version_id=uuid4(),
                    status="competing",
                    substatus="champion",
                    is_champion=True,
                ),
                MembershipInfo(
                    id=uuid4(),
                    league_id=league_id,
                    division_id=competition_id,
                    policy_version_id=uuid4(),
                    status="competing",
                ),
            ],
        ),
    )

    events = {event.league_policy_membership_id: event for event in response.policy_membership_events}
    assert set(events) == {dirt_membership_id, wood_membership_id}
    assert events[dirt_membership_id].from_division_id == dirt_id
    assert events[dirt_membership_id].to_division_id is None
    assert events[dirt_membership_id].status == "disqualified"
    assert events[dirt_membership_id].substatus == "inactive"
    assert events[wood_membership_id].from_division_id == wood_id
    assert events[wood_membership_id].to_division_id == competition_id
    assert events[wood_membership_id].status == "competing"
    assert events[wood_membership_id].substatus == "champion"


def _round_start(
    *,
    policy_version_ids: list[UUID],
    num_agents: int,
    commissioner_config: dict | None = None,
    division_name: str = "Bronze",
    division_id: UUID | None = None,
    division_type: str = "competition",
    extra_divisions: list[DivisionInfo] | None = None,
    state: dict | None = None,
) -> RoundStart:
    active_division_id = division_id or uuid4()
    league_id = uuid4()
    divisions = [
        DivisionInfo(id=active_division_id, name=division_name, level=0, type=division_type),
        *(extra_divisions or []),
    ]
    # The helper's members are the active division's entrants: qualifying members in a
    # staging division, champions in a competition division.
    member_status, member_substatus = (
        ("qualifying", None) if division_type == "staging" else ("competing", "active")
    )
    member_is_champion = division_type != "staging"
    return RoundStart(
        round_id=uuid4(),
        round_number=1,
        league=LeagueInfo(id=league_id, commissioner_config=commissioner_config or {}),
        divisions=divisions,
        memberships=[
            MembershipInfo(
                id=uuid4(),
                league_id=league_id,
                division_id=active_division_id,
                policy_version_id=policy_version_id,
                player_id=f"player-{index}",
                status=member_status,
                substatus=member_substatus,
                is_champion=member_is_champion,
            )
            for index, policy_version_id in enumerate(policy_version_ids)
        ],
        recent_results=[],
        variants=[
            VariantInfo(
                id="default",
                name="Default",
                game_config={"num_agents": num_agents},
            )
        ],
        state=state,
    )


def _assert_episode_seeds(episodes: list[ProtocolEpisodeRequest]) -> None:
    for episode in episodes:
        _assert_valid_episode_seed(episode.seed)


def _assert_valid_episode_seed(seed: int) -> None:
    assert 0 <= seed <= 2**31 - 1


def test_episode_request_defaults_random_seed() -> None:
    policy_version_ids = [uuid4(), uuid4()]

    defaulted = ProtocolEpisodeRequest(
        request_id="defaulted",
        variant_id="default",
        policy_version_ids=policy_version_ids,
    )
    explicit_none = ProtocolEpisodeRequest(
        request_id="explicit-none",
        variant_id="default",
        policy_version_ids=policy_version_ids,
        seed=None,
    )

    _assert_valid_episode_seed(defaulted.seed)
    _assert_valid_episode_seed(explicit_none.seed)


def test_default_commissioner_round_robin_generation_and_ranking() -> None:
    policy_version_ids = [uuid4() for _ in range(3)]
    pool = PolicyPool(
        id=uuid4(),
        label="Round",
        pool_type="round",
        config={"num_episodes": 2},
    )
    entries = [
        PolicyPoolEntry(pool_id=pool.id, policy_version_id=policy_version_id, seed_order=index)
        for index, policy_version_id in enumerate(policy_version_ids)
    ]

    commissioner = BaselineCommissioner()
    schedule = commissioner.schedule_episodes(pool=pool, entries=entries, num_agents=4, variant_id="default")

    _assert_episode_seeds(schedule.episodes)
    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0], policy_version_ids[1], policy_version_ids[2], policy_version_ids[0]],
        [policy_version_ids[1], policy_version_ids[2], policy_version_ids[0], policy_version_ids[1]],
    ]

    division_id = uuid4()
    complete = commissioner.complete_round(
        round_row=Round(
            id=uuid4(),
            division_id=division_id,
            round_number=1,
            commissioner_key="auto",
        ),
        pool=pool,
        entries=entries,
        episode_results=[
            EpisodeResult(
                episode_request_id=uuid4(),
                scores=[
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=4.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=2.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[2], score=6.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=8.0),
                ],
            ),
            EpisodeResult(
                episode_request_id=uuid4(),
                scores=[
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=10.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[2], score=0.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=6.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=4.0),
                ],
            ),
        ],
    )

    rankings = complete.results[0].rankings
    assert [ranking.policy_version_id for ranking in rankings] == [
        policy_version_ids[0],
        policy_version_ids[1],
        policy_version_ids[2],
    ]
    assert [ranking.score for ranking in rankings] == pytest.approx([6.0, 16.0 / 3.0, 3.0])


def test_ruleset_strategy_rank_round_score_uses_per_episode_placement() -> None:
    # Same episode results as the mean test above, but with scoring.round_score = "rank": the
    # round score becomes the mean of each policy's per-episode rank points (placement N..1),
    # not the mean raw score.
    policy_version_ids = [uuid4() for _ in range(3)]
    pool = PolicyPool(id=uuid4(), label="Round", pool_type="round", config={"num_episodes": 2})
    entries = [
        PolicyPoolEntry(pool_id=pool.id, policy_version_id=policy_version_id, seed_order=index)
        for index, policy_version_id in enumerate(policy_version_ids)
    ]
    commissioner = RulesetStrategyCommissioner(
        {
            "scoring": {"round_score": "rank"},
            "divisions": {"competition": {"match": {"type": "competition"}, "entrants": "champions"}},
        }
    )

    complete = commissioner.complete_round(
        round_row=Round(id=uuid4(), division_id=uuid4(), round_number=1, commissioner_key="ruleset_strategy"),
        pool=pool,
        entries=entries,
        episode_results=[
            EpisodeResult(
                episode_request_id=uuid4(),
                scores=[
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=4.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=2.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[2], score=6.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=8.0),
                ],
            ),
            EpisodeResult(
                episode_request_id=uuid4(),
                scores=[
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=10.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[2], score=0.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=6.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=4.0),
                ],
            ),
        ],
    )

    rankings = complete.results[0].rankings
    by_policy = {ranking.policy_version_id: ranking for ranking in rankings}
    # Per-episode rank points (N=4 each episode), averaged across a policy's seats:
    #   p0: ep1 scores 4->2pts, 8->4pts; ep2 score 6->3pts  => (2+4+3)/3 = 3.0
    #   p1: ep1 score 2->1pt;            ep2 10->4pts, 4->2pts => (1+4+2)/3 = 7/3
    #   p2: ep1 score 6->3pts;           ep2 score 0->1pt    => (3+1)/2 = 2.0
    assert by_policy[policy_version_ids[0]].score == pytest.approx(3.0)
    assert by_policy[policy_version_ids[1]].score == pytest.approx(7.0 / 3.0)
    assert by_policy[policy_version_ids[2]].score == pytest.approx(2.0)
    assert [ranking.policy_version_id for ranking in rankings] == policy_version_ids
    assert by_policy[policy_version_ids[0]].result_metadata["score_kind"] == "rank_episode_round_score"


def test_ruleset_strategy_win_round_score_uses_binary_win_points() -> None:
    # scoring.round_score = "win": each episode's top scorer earns 1 and everyone else 0 (a tie
    # for first shares the win), and a policy's round score is its win rate across its seats.
    policy_version_ids = [uuid4() for _ in range(3)]
    pool = PolicyPool(id=uuid4(), label="Round", pool_type="round", config={"num_episodes": 2})
    entries = [
        PolicyPoolEntry(pool_id=pool.id, policy_version_id=policy_version_id, seed_order=index)
        for index, policy_version_id in enumerate(policy_version_ids)
    ]
    commissioner = RulesetStrategyCommissioner(
        {
            "scoring": {"round_score": "win"},
            "divisions": {"competition": {"match": {"type": "competition"}, "entrants": "champions"}},
        }
    )

    complete = commissioner.complete_round(
        round_row=Round(id=uuid4(), division_id=uuid4(), round_number=1, commissioner_key="ruleset_strategy"),
        pool=pool,
        entries=entries,
        episode_results=[
            EpisodeResult(
                episode_request_id=uuid4(),
                scores=[
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=10.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=5.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[2], score=3.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=2.0),
                ],
            ),
            EpisodeResult(
                episode_request_id=uuid4(),
                scores=[
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=8.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=8.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[2], score=4.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=1.0),
                ],
            ),
        ],
    )

    rankings = complete.results[0].rankings
    by_policy = {ranking.policy_version_id: ranking for ranking in rankings}
    # Per-episode win points (1 for the episode's top score, ties shared), averaged across a policy's seats:
    #   p0: ep1 10->1, 2->0; ep2 1->0           => (1+0+0)/3 = 1/3
    #   p1: ep1 5->0;        ep2 8->1, 8->1      => (0+1+1)/3 = 2/3  (the tied-for-first seats both win)
    #   p2: ep1 3->0;        ep2 4->0           => (0+0)/2   = 0.0
    assert by_policy[policy_version_ids[0]].score == pytest.approx(1.0 / 3.0)
    assert by_policy[policy_version_ids[1]].score == pytest.approx(2.0 / 3.0)
    assert by_policy[policy_version_ids[2]].score == pytest.approx(0.0)
    assert [ranking.policy_version_id for ranking in rankings] == [
        policy_version_ids[1],
        policy_version_ids[0],
        policy_version_ids[2],
    ]
    assert by_policy[policy_version_ids[1]].result_metadata["score_kind"] == "win_episode_round_score"


def test_default_commissioner_ignores_neutral_zero_scores_only_when_episode_has_negative_score() -> None:
    policy_version_ids = [uuid4() for _ in range(3)]
    pool = PolicyPool(
        id=uuid4(),
        label="Round",
        pool_type="round",
        config={"num_episodes": 3},
    )
    entries = [
        PolicyPoolEntry(pool_id=pool.id, policy_version_id=policy_version_id, seed_order=index)
        for index, policy_version_id in enumerate(policy_version_ids)
    ]

    complete = BaselineCommissioner().complete_round(
        round_row=Round(
            id=uuid4(),
            division_id=uuid4(),
            round_number=1,
            commissioner_key="auto",
        ),
        pool=pool,
        entries=entries,
        episode_results=[
            EpisodeResult(
                episode_request_id=uuid4(),
                scores=[
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=0.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=-100.0),
                ],
            ),
            EpisodeResult(
                episode_request_id=uuid4(),
                scores=[
                    RoundPolicyScore(policy_version_id=policy_version_ids[0], score=10.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=5.0),
                ],
            ),
            EpisodeResult(
                episode_request_id=uuid4(),
                scores=[
                    RoundPolicyScore(policy_version_id=policy_version_ids[2], score=0.0),
                    RoundPolicyScore(policy_version_id=policy_version_ids[1], score=5.0),
                ],
            ),
        ],
    )

    rankings_by_policy = {ranking.policy_version_id: ranking for ranking in complete.results[0].rankings}

    assert rankings_by_policy[policy_version_ids[0]].score == pytest.approx(10.0)
    assert rankings_by_policy[policy_version_ids[0]].result_metadata[RANKED_SCORE_COUNT_METADATA_KEY] == 1
    assert rankings_by_policy[policy_version_ids[1]].score == pytest.approx(-30.0)
    assert rankings_by_policy[policy_version_ids[1]].result_metadata[RANKED_SCORE_COUNT_METADATA_KEY] == 3
    assert rankings_by_policy[policy_version_ids[2]].score == pytest.approx(0.0)
    assert rankings_by_policy[policy_version_ids[2]].result_metadata[RANKED_SCORE_COUNT_METADATA_KEY] == 1


def test_division_leaderboard_ignores_round_result_with_no_ranked_scores() -> None:
    division_id = uuid4()
    latest_round_id = uuid4()
    older_round_id = uuid4()
    policy_id = uuid4()
    response = rank_division_for_request(
        BaselineCommissioner(),
        RankDivisionRequest(
            league=LeagueInfo(id=uuid4(), commissioner_config={}),
            division=DivisionInfo(id=division_id, name="Bronze", level=0, type="competition"),
            completed_rounds=[
                RoundInfo(
                    id=latest_round_id,
                    division_id=division_id,
                    round_number=2,
                    status="completed",
                    completed_at="2026-06-07T02:00:00+00:00",
                ),
                RoundInfo(
                    id=older_round_id,
                    division_id=division_id,
                    round_number=1,
                    status="completed",
                    completed_at="2026-06-07T00:00:00+00:00",
                ),
            ],
            recent_rounds=[],
            round_results=[
                LeaderboardRoundResultInfo(
                    round_id=latest_round_id,
                    policy_version_id=policy_id,
                    player_id="player-1",
                    rank=1,
                    score=0.0,
                    result_metadata={RANKED_SCORE_COUNT_METADATA_KEY: 0},
                ),
                LeaderboardRoundResultInfo(
                    round_id=older_round_id,
                    policy_version_id=policy_id,
                    player_id="player-1",
                    rank=1,
                    score=25.0,
                    result_metadata={RANKED_SCORE_COUNT_METADATA_KEY: 1},
                ),
            ],
        ),
    )

    assert len(response.rankings) == 1
    assert response.rankings[0].score == pytest.approx(25.0)


def test_cogs_vs_clips_config_qualifier_round_uses_qualifier_stage() -> None:
    qualifier_id = uuid4()
    daily_id = uuid4()
    qualifier_policy_id = uuid4()
    daily_policy_ids = [uuid4(), uuid4()]

    response = schedule_rounds_for_request(
        _ruleset_commissioner("cogs_vs_clips"),
        ScheduleRoundsRequest(
            league=LeagueInfo(
                id=uuid4(),
                commissioner_config={
                    "minimum_champions": 2,
                    "qualifiers_division_name": "Qualifiers",
                    "qualifiers_minimum_champions": 1,
                    "stages": [{"label": "Slot-balanced round", "num_episodes": 1, "min_episodes_per_entrant": 8}],
                    "qualifier_stages": [
                        {"label": "Qualifier", "num_episodes": 2, "min_episodes_per_entrant": 2, "self_play": True}
                    ],
                },
            ),
            divisions=[
                DivisionInfo(id=qualifier_id, name="Qualifiers", level=-1, type="staging"),
                DivisionInfo(id=daily_id, name="Daily", level=1, type="competition"),
            ],
            active_memberships=[
                MembershipInfo(
                    id=uuid4(),
                    league_id=uuid4(),
                    division_id=qualifier_id,
                    policy_version_id=qualifier_policy_id,
                    status="qualifying",
                ),
                *[
                    MembershipInfo(
                        id=uuid4(),
                        league_id=uuid4(),
                        division_id=daily_id,
                        policy_version_id=policy_version_id,
                        status="competing",
                        substatus="champion",
                        is_champion=True,
                    )
                    for policy_version_id in daily_policy_ids
                ],
            ],
            recent_rounds=[],
        ),
    )

    rounds = {round_spec.division_id: round_spec.round_config.stages[0] for round_spec in response.rounds}
    assert rounds[qualifier_id].label == "Qualifier"
    assert rounds[qualifier_id].num_episodes == 2
    assert rounds[qualifier_id].min_episodes_per_entrant == 2
    assert "self_play" not in rounds[qualifier_id].model_dump()
    assert rounds[daily_id].label == "Slot-balanced round"


def test_ruleset_strategy_default_config_matches_default_schedule() -> None:
    policy_version_ids = [uuid4() for _ in range(3)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=4,
        commissioner_config={},
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("default"), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0], policy_version_ids[1], policy_version_ids[2], policy_version_ids[0]]
    ]
    assert schedule.episodes[0].game_config is None


def test_ruleset_strategy_default_config_schedules_one_appearance_per_competitor() -> None:
    daily_id = uuid4()
    policy_version_ids = [uuid4(), uuid4(), uuid4(), uuid4()]

    response = schedule_rounds_for_request(
        _ruleset_commissioner("default"),
        ScheduleRoundsRequest(
            league=LeagueInfo(id=uuid4(), commissioner_config={}),
            divisions=[DivisionInfo(id=daily_id, name="Daily", level=1, type="competition")],
            active_memberships=[
                MembershipInfo(
                    id=uuid4(),
                    league_id=uuid4(),
                    division_id=daily_id,
                    policy_version_id=policy_version_id,
                    status="competing",
                    substatus="champion",
                    is_champion=True,
                )
                for policy_version_id in policy_version_ids
            ],
            recent_rounds=[],
        ),
    )

    assert len(response.rounds) == 1
    stage = response.rounds[0].round_config.stages[0]
    assert stage.min_episodes_per_entrant == 1


def test_ruleset_strategy_default_config_qualifier_self_play_does_not_crash() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=4,
        commissioner_config={},
        division_name="Qualifiers",
        division_type="staging",
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("default"), round_start)

    _assert_episode_seeds(schedule.episodes)
    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0]] * 4,
        [policy_version_ids[0]] * 4,
        [policy_version_ids[1]] * 4,
        [policy_version_ids[1]] * 4,
    ]


def test_ruleset_strategy_ignores_legacy_wire_commissioner_config() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=4,
        commissioner_config={
            "stages": [{"label": "Legacy", "num_episodes": 999, "min_episodes_per_entrant": 999}],
            "minimum_champions": 2,
            "commissioner_runnable_id": "default-commissioner",
            "qualifiers_division_name": "Qualifiers",
            "default_execution_backend": "dispatch",
            "schedule_interval_minutes": 30,
        },
        division_name="Qualifiers",
        division_type="staging",
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("default"), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0]] * 4,
        [policy_version_ids[0]] * 4,
        [policy_version_ids[1]] * 4,
        [policy_version_ids[1]] * 4,
    ]


def test_ruleset_strategy_policy_membership_events_are_selected_by_division() -> None:
    qualifier_id = uuid4()
    competition_id = uuid4()
    qualifier_policy_id = uuid4()
    competition_policy_id = uuid4()
    qualifier_membership_id = uuid4()
    competition_membership_id = uuid4()
    config = {
        "defaults": {"min_entries_to_start": 1, "stage": {"label": "Round", "episodes": 1}},
        "divisions": {
            "qualifiers": {
                "match": {"name": "Qualifiers", "type": "staging"},
                "entrants": "qualifying",
                "policy_membership_events": [
                    {
                        "id": "qualifier_review",
                        "criteria": "otherwise",
                        "actions": [
                            {
                                "type": "update_membership",
                                "status": "qualifying",
                                "substatus": "qualifier_review",
                            }
                        ],
                    }
                ],
            },
            "competition": {
                "match": {"name": "Competition", "type": "competition"},
                "entrants": "champions",
                "policy_membership_events": [
                    {
                        "id": "competition_review",
                        "criteria": "otherwise",
                        "actions": [
                            {
                                "type": "update_membership",
                                "status": "competing",
                                "substatus": "competition_review",
                            }
                        ],
                    }
                ],
            },
        },
    }

    qualifier_start = _round_start(
        policy_version_ids=[],
        num_agents=1,
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        extra_divisions=[DivisionInfo(id=competition_id, name="Competition", level=1, type="competition")],
        state={"round_config": {"current_division_id": str(qualifier_id)}},
    )
    qualifier_start.memberships = [
        MembershipInfo(
            id=qualifier_membership_id,
            league_id=qualifier_start.league.id,
            division_id=qualifier_id,
            policy_version_id=qualifier_policy_id,
            status="qualifying",
        )
    ]

    qualifier_complete = complete_round_for_round_start(
        RulesetStrategyCommissioner(config),
        qualifier_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=qualifier_policy_id, score=1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[qualifier_policy_id],
            )
        ],
    )

    competition_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        division_name="Competition",
        division_id=competition_id,
        state={"round_config": {"current_division_id": str(competition_id)}},
    )
    competition_start.memberships = [
        MembershipInfo(
            id=competition_membership_id,
            league_id=competition_start.league.id,
            division_id=competition_id,
            policy_version_id=competition_policy_id,
            status="competing",
            substatus="active",
            is_champion=True,
        )
    ]

    competition_complete = complete_round_for_round_start(
        RulesetStrategyCommissioner(config),
        competition_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=competition_policy_id, score=1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[competition_policy_id] * 2,
            )
        ],
    )

    assert len(qualifier_complete.policy_membership_events) == 1
    qualifier_event = qualifier_complete.policy_membership_events[0]
    assert qualifier_event.league_policy_membership_id == qualifier_membership_id
    assert qualifier_event.status == "qualifying"
    assert qualifier_event.substatus == "qualifier_review"
    assert qualifier_event.evidence[0].metadata["transition_id"] == "qualifier_review"

    assert len(competition_complete.policy_membership_events) == 1
    competition_event = competition_complete.policy_membership_events[0]
    assert competition_event.league_policy_membership_id == competition_membership_id
    assert competition_event.status == "competing"
    assert competition_event.substatus == "competition_review"
    assert competition_event.evidence[0].metadata["transition_id"] == "competition_review"


def test_ruleset_strategy_game_config_is_selected_by_division() -> None:
    qualifier_id = uuid4()
    competition_id = uuid4()
    qualifier_policy_id = uuid4()
    competition_policy_ids = [uuid4(), uuid4(), uuid4(), uuid4()]
    config = {
        "defaults": {"min_entries_to_start": 1, "stage": {"label": "Round", "episodes": 1}},
        "divisions": {
            "qualifiers": {
                "match": {"name": "Qualifiers", "type": "staging"},
                "entrants": "qualifying",
                "game_config": {"num_agents": 1, "map": "qualifier"},
            },
            "competition": {
                "match": {"name": "Competition", "type": "competition"},
                "entrants": "champions",
                "game_config": {"num_agents": 3, "map": "competition"},
            },
        },
    }

    qualifier_start = _round_start(
        policy_version_ids=[qualifier_policy_id],
        num_agents=9,
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        state={"round_config": {"current_division_id": str(qualifier_id)}},
    )
    qualifier_start.variants[0].game_config["timeout_seconds"] = 30

    competition_start = _round_start(
        policy_version_ids=competition_policy_ids,
        num_agents=9,
        division_name="Competition",
        division_id=competition_id,
        extra_divisions=[DivisionInfo(id=qualifier_id, name="Qualifiers", level=-99, type="staging")],
        state={"round_config": {"current_division_id": str(competition_id)}},
    )
    competition_start.variants[0].game_config["timeout_seconds"] = 60

    qualifier_schedule = schedule_episodes_for_round_start(RulesetStrategyCommissioner(config), qualifier_start)
    competition_schedule = schedule_episodes_for_round_start(RulesetStrategyCommissioner(config), competition_start)

    assert qualifier_schedule.episodes[0].policy_version_ids == [qualifier_policy_id]
    assert qualifier_schedule.episodes[0].game_config == {
        "num_agents": 1,
        "timeout_seconds": 30,
        "map": "qualifier",
    }
    assert competition_schedule.episodes[0].policy_version_ids == competition_policy_ids[:3]
    assert competition_schedule.episodes[0].game_config == {
        "num_agents": 3,
        "timeout_seconds": 60,
        "map": "competition",
    }


@pytest.mark.parametrize("config_name", ["default", "cogs_vs_clips", "proxywar"])
def test_ruleset_strategy_transition_configs_advance_completed_qualifiers(config_name: str) -> None:
    qualifier_id = uuid4()
    competition_id = uuid4()
    policy_version_ids = [uuid4(), uuid4()]
    membership_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=4,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        extra_divisions=[DivisionInfo(id=competition_id, name="Bronze", level=0, type="competition")],
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=policy_version_id,
            player_id=f"qualifier-{index}",
            status="qualifying",
        )
        for index, (membership_id, policy_version_id) in enumerate(
            zip(membership_ids, policy_version_ids, strict=True)
        )
    ]

    complete = complete_round_for_round_start(
        _ruleset_commissioner(config_name),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=policy_version_ids[0], score=1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[policy_version_ids[0]] * 4,
            ),
            ProtocolEpisodeRequest(
                request_id="1",
                variant_id="default",
                policy_version_ids=[policy_version_ids[1]] * 4,
            ),
        ],
    )

    events = {event.league_policy_membership_id: event for event in complete.policy_membership_events}
    assert events[membership_ids[0]].to_division_id == competition_id
    assert events[membership_ids[0]].status == "competing"
    assert events[membership_ids[0]].substatus == "champion"
    assert events[membership_ids[1]].to_division_id is None
    assert events[membership_ids[1]].status == "disqualified"
    assert events[membership_ids[1]].substatus == "inactive"


def test_ruleset_strategy_cogs_vs_clips_config_matches_rolling_window_schedule() -> None:
    policy_version_ids = [uuid4() for _ in range(16)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=8,
        commissioner_config={},
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("cogs_vs_clips"), round_start)

    _assert_episode_seeds(schedule.episodes)
    assert len(schedule.episodes) == 16
    assert schedule.episodes[0].policy_version_ids == [policy_version_ids[i] for i in (0, 1, 2, 3, 4, 5, 6, 7)]
    assert schedule.episodes[1].policy_version_ids == [policy_version_ids[i] for i in (1, 2, 3, 4, 5, 6, 7, 8)]
    assert schedule.episodes[-1].policy_version_ids == [policy_version_ids[i] for i in (15, 0, 1, 2, 3, 4, 5, 6)]


def test_ruleset_strategy_proxywar_config_matches_two_player_rolling_window_schedule() -> None:
    policy_version_ids = [uuid4() for _ in range(5)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
        commissioner_config={},
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("proxywar"), round_start)

    _assert_episode_seeds(schedule.episodes)
    assert len(schedule.episodes) == 20
    assert [episode.policy_version_ids for episode in schedule.episodes[:5]] == [
        [policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[1], policy_version_ids[2]],
        [policy_version_ids[2], policy_version_ids[3]],
        [policy_version_ids[3], policy_version_ids[4]],
        [policy_version_ids[4], policy_version_ids[0]],
    ]


def test_ruleset_strategy_proxywar_config_matches_four_player_rolling_window_schedule() -> None:
    policy_version_ids = [uuid4() for _ in range(5)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=4,
        commissioner_config={},
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("proxywar"), round_start)

    _assert_episode_seeds(schedule.episodes)
    assert len(schedule.episodes) == 10
    assert [episode.policy_version_ids for episode in schedule.episodes[:5]] == [
        [policy_version_ids[0], policy_version_ids[1], policy_version_ids[2], policy_version_ids[3]],
        [policy_version_ids[1], policy_version_ids[2], policy_version_ids[3], policy_version_ids[4]],
        [policy_version_ids[2], policy_version_ids[3], policy_version_ids[4], policy_version_ids[0]],
        [policy_version_ids[3], policy_version_ids[4], policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[4], policy_version_ids[0], policy_version_ids[1], policy_version_ids[2]],
    ]


def test_ruleset_strategy_proxywar_config_duplicates_short_four_player_pool() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=4,
        commissioner_config={},
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("proxywar"), round_start)

    assert len(schedule.episodes) == 4
    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0], policy_version_ids[1], policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[0], policy_version_ids[1], policy_version_ids[1], policy_version_ids[0]],
        [policy_version_ids[0], policy_version_ids[1], policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[0], policy_version_ids[1], policy_version_ids[1], policy_version_ids[0]],
    ]


def test_ruleset_strategy_among_them_config_matches_rolling_window_schedule() -> None:
    policy_version_ids = [uuid4() for _ in range(16)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=8,
        commissioner_config={},
        division_name="Daily",
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("among_them"), round_start)

    assert len(schedule.episodes) == 200
    assert schedule.episodes[0].policy_version_ids == [policy_version_ids[i] for i in (0, 1, 2, 3, 4, 5, 6, 7)]
    assert schedule.episodes[1].policy_version_ids == [policy_version_ids[i] for i in (1, 2, 3, 4, 5, 6, 7, 8)]
    assert schedule.episodes[-1].policy_version_ids == [policy_version_ids[i] for i in (7, 8, 9, 10, 11, 12, 13, 14)]


def test_ruleset_strategy_four_score_config_schedules_four_repeated_teams() -> None:
    policy_version_ids = [uuid4() for _ in range(5)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=32,
        commissioner_config={},
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("four_score"), round_start)

    _assert_episode_seeds(schedule.episodes)
    assert len(schedule.episodes) == 25
    assert schedule.episodes[0].policy_version_ids == [
        *([policy_version_ids[0]] * 8),
        *([policy_version_ids[1]] * 8),
        *([policy_version_ids[2]] * 8),
        *([policy_version_ids[3]] * 8),
    ]
    assert all(len(episode.policy_version_ids) == 32 for episode in schedule.episodes)
    for episode in schedule.episodes:
        teams = [episode.policy_version_ids[start : start + 8] for start in range(0, 32, 8)]
        assert all(len(set(team)) == 1 for team in teams)
        assert len({team[0] for team in teams}) == 4
    appearances = {
        policy_version_id: sum(
            episode.policy_version_ids.count(policy_version_id) // 8 for episode in schedule.episodes
        )
        for policy_version_id in policy_version_ids
    }
    assert appearances == {policy_version_id: 20 for policy_version_id in policy_version_ids}


def test_ruleset_strategy_cue_n_woo_config_matches_leaderboard_neighbor_schedule() -> None:
    policy_version_ids = [uuid4() for _ in range(6)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
        commissioner_config={},
    )
    round_start.recent_results = [
        RecentResult(
            round_id=uuid4(),
            division_id=round_start.divisions[0].id,
            round_number=1,
            policy_version_id=policy_version_id,
            rank=index + 1,
            score=float(6 - index),
        )
        for index, policy_version_id in enumerate(policy_version_ids)
    ]

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("cue_n_woo"), round_start)

    _assert_episode_seeds(schedule.episodes)
    assert len(schedule.episodes) == 24
    assert [episode.policy_version_ids for episode in schedule.episodes[:4]] == [
        [policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[0], policy_version_ids[2]],
        [policy_version_ids[0], policy_version_ids[3]],
        [policy_version_ids[0], policy_version_ids[4]],
    ]
    assert [episode.policy_version_ids for episode in schedule.episodes[8:12]] == [
        [policy_version_ids[2], policy_version_ids[3]],
        [policy_version_ids[2], policy_version_ids[4]],
        [policy_version_ids[2], policy_version_ids[1]],
        [policy_version_ids[2], policy_version_ids[0]],
    ]
    assert [episode.policy_version_ids for episode in schedule.episodes[-4:]] == [
        [policy_version_ids[5], policy_version_ids[4]],
        [policy_version_ids[5], policy_version_ids[3]],
        [policy_version_ids[5], policy_version_ids[2]],
        [policy_version_ids[5], policy_version_ids[1]],
    ]


def test_ruleset_strategy_cue_n_woo_config_repeats_neighbors_to_preserve_minimum() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
        commissioner_config={},
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("cue_n_woo"), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[1], policy_version_ids[0]],
        [policy_version_ids[1], policy_version_ids[0]],
        [policy_version_ids[1], policy_version_ids[0]],
        [policy_version_ids[1], policy_version_ids[0]],
    ]


def test_ruleset_strategy_cue_n_woo_config_uses_round_complete_transitions() -> None:
    config = _ruleset_config("cue_n_woo")

    assert "on_round_complete" in config["divisions"]["competition"]
    assert "on_episode_complete" not in config["divisions"]["competition"]
    assert "on_round_complete" in config["divisions"]["qualifiers"]["stages"][0]
    assert "on_episode_complete" not in config["divisions"]["qualifiers"]["stages"][0]


@pytest.mark.parametrize("scores", [[0.0, 0.0], [-1.0, 0.5]])
def test_ruleset_strategy_cue_n_woo_competition_non_positive_average_disqualifies(
    scores: list[float],
) -> None:
    policy_version_ids = [uuid4(), uuid4()]
    membership_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        commissioner_config={},
        division_name="Competition",
        division_type="competition",
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=round_start.divisions[0].id,
            policy_version_id=policy_version_id,
            player_id=f"player-{index}",
            status="competing",
            substatus="active",
            is_champion=True,
        )
        for index, (membership_id, policy_version_id) in enumerate(
            zip(membership_ids, policy_version_ids, strict=True)
        )
    ]

    complete = complete_round_for_round_start(
        _ruleset_commissioner("cue_n_woo"),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id=str(index),
                scores=[
                    EpisodeScore(policy_version_id=policy_version_ids[0], score=score),
                    EpisodeScore(policy_version_id=policy_version_ids[1], score=2.0),
                ],
            )
            for index, score in enumerate(scores)
        ],
        [
            ProtocolEpisodeRequest(
                request_id=str(index),
                variant_id="default",
                policy_version_ids=policy_version_ids,
            )
            for index in range(len(scores))
        ],
    )

    assert len(complete.policy_membership_events) == 1
    event = complete.policy_membership_events[0]
    assert event.league_policy_membership_id == membership_ids[0]
    assert event.to_division_id is None
    assert event.status == "disqualified"
    assert event.substatus == "inactive"
    assert event.evidence[0].metadata["transition_id"] == "disqualified_non_positive_round_score"
    assert event.evidence[0].metadata["observed"]["score"] <= 0


def test_ruleset_strategy_cue_n_woo_competition_positive_average_stays_competing() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
        commissioner_config={},
        division_name="Competition",
        division_type="competition",
    )

    complete = complete_round_for_round_start(
        _ruleset_commissioner("cue_n_woo"),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[
                    EpisodeScore(policy_version_id=policy_version_ids[0], score=1.0),
                    EpisodeScore(policy_version_id=policy_version_ids[1], score=2.0),
                ],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=policy_version_ids,
            )
        ],
    )

    assert complete.policy_membership_events == []


def test_ruleset_strategy_cue_n_woo_config_schedules_crash_check_qualifiers() -> None:
    policy_version_ids = [uuid4() for _ in range(3)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
        commissioner_config={},
        division_name="Qualifiers",
        division_type="staging",
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("cue_n_woo"), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0]] * 2,
        [policy_version_ids[0]] * 2,
        [policy_version_ids[1]] * 2,
        [policy_version_ids[1]] * 2,
        [policy_version_ids[2]] * 2,
        [policy_version_ids[2]] * 2,
    ]


def test_ruleset_strategy_cue_n_woo_positive_crash_check_promotes_to_competition() -> None:
    qualifier_id = uuid4()
    competition_id = uuid4()
    membership_id = uuid4()
    policy_version_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        extra_divisions=[DivisionInfo(id=competition_id, name="Competition", level=0, type="competition")],
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=policy_version_id,
            player_id="qualifier",
            status="qualifying",
        )
    ]

    complete = complete_round_for_round_start(
        _ruleset_commissioner("cue_n_woo"),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=policy_version_id, score=1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[policy_version_id] * 2,
            )
        ],
    )

    assert len(complete.policy_membership_events) == 1
    event = complete.policy_membership_events[0]
    assert event.league_policy_membership_id == membership_id
    assert event.to_division_id == competition_id
    assert event.status == "competing"
    assert event.substatus == "champion"
    assert event.evidence[0].metadata["transition_id"] == "passed_crash_check"


@pytest.mark.parametrize("score", [0.0, -1.0])
def test_ruleset_strategy_cue_n_woo_non_positive_crash_check_disqualifies(score: float) -> None:
    qualifier_id = uuid4()
    membership_id = uuid4()
    policy_version_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=policy_version_id,
            player_id="qualifier",
            status="qualifying",
        )
    ]

    complete = complete_round_for_round_start(
        _ruleset_commissioner("cue_n_woo"),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=policy_version_id, score=score)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[policy_version_id] * 2,
            )
        ],
    )

    assert len(complete.policy_membership_events) == 1
    event = complete.policy_membership_events[0]
    assert event.league_policy_membership_id == membership_id
    assert event.to_division_id is None
    assert event.status == "disqualified"
    assert event.substatus == "inactive"
    assert event.evidence[0].metadata["transition_id"] == "failed_score_check"


def test_ruleset_strategy_cue_n_woo_uncompleted_crash_check_disqualifies() -> None:
    qualifier_id = uuid4()
    membership_id = uuid4()
    policy_version_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=policy_version_id,
            player_id="qualifier",
            status="qualifying",
        )
    ]

    complete = complete_round_for_round_start(
        _ruleset_commissioner("cue_n_woo"),
        round_start,
        [],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[policy_version_id] * 2,
            )
        ],
    )

    assert len(complete.policy_membership_events) == 1
    event = complete.policy_membership_events[0]
    assert event.league_policy_membership_id == membership_id
    assert event.to_division_id is None
    assert event.status == "disqualified"
    assert event.substatus == "inactive"
    assert event.evidence[0].metadata["transition_id"] == "failed_crash_check"


def test_ruleset_strategy_rejects_mixed_round_and_legacy_episode_complete_hooks() -> None:
    transition = {
        "criteria": {"score_lte": 0},
        "actions": [{"type": "update_membership", "status": "disqualified"}],
    }

    with pytest.raises(ValueError, match="on_round_complete"):
        RulesetStrategyCommissioner(
            {
                "divisions": {
                    "competition": {
                        "match": {"type": "competition"},
                        "on_round_complete": [transition],
                        "on_episode_complete": [transition],
                    }
                }
            }
        )


def test_ruleset_strategy_four_score_config_qualifier_self_play_fills_every_slot() -> None:
    policy_version_ids = [uuid4() for _ in range(3)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=32,
        commissioner_config={},
        division_name="Qualifiers",
        division_type="staging",
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("four_score"), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0]] * 32,
        [policy_version_ids[0]] * 32,
        [policy_version_ids[1]] * 32,
        [policy_version_ids[1]] * 32,
        [policy_version_ids[2]] * 32,
        [policy_version_ids[2]] * 32,
    ]


def test_ruleset_strategy_among_them_config_targets_first_competition_division_without_daily_name() -> None:
    qualifier_id = uuid4()
    competition_id = uuid4()
    policy_version_id = uuid4()
    membership_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=8,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        extra_divisions=[DivisionInfo(id=competition_id, name="Wood", level=0, type="competition")],
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=policy_version_id,
            player_id="qualifier-0",
            status="qualifying",
            substatus="score_gate",
        )
    ]

    complete = complete_round_for_round_start(
        _ruleset_commissioner("among_them"),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=policy_version_id, score=1.0)],
            )
        ],
    )

    event = complete.policy_membership_events[0]
    assert event.to_division_id == competition_id
    assert event.evidence[0].type == "ruleset_transition"
    assert event.evidence[0].metadata["transition_id"] == "passed_score_gate"
    assert event.evidence[0].metadata["criteria"] == {"score_gt": 0.0}
    assert event.evidence[0].metadata["observed"]["score"] == 1.0
    assert event.evidence[0].metadata["actions"] == [
        {
            "type": "update_membership",
            "to_division_match": {"type": "competition"},
            "status": "competing",
            "substatus": "champion",
        }
    ]


def test_ruleset_strategy_among_them_config_first_qualifier_stage_advances_to_score_gate() -> None:
    qualifier_id = uuid4()
    policy_version_ids = [uuid4(), uuid4()]
    membership_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=8,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=policy_version_id,
            player_id=f"qualifier-{index}",
            status="qualifying",
        )
        for index, (membership_id, policy_version_id) in enumerate(
            zip(membership_ids, policy_version_ids, strict=True)
        )
    ]

    complete = complete_round_for_round_start(
        _ruleset_commissioner("among_them"),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=policy_version_ids[0], score=-1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[policy_version_ids[0]] * 8,
            )
        ],
    )

    events = {event.league_policy_membership_id: event for event in complete.policy_membership_events}
    assert events[membership_ids[0]].to_division_id == qualifier_id
    assert events[membership_ids[0]].status == "qualifying"
    assert events[membership_ids[0]].substatus == "score_gate"
    assert events[membership_ids[0]].reason == "Passed crash test"
    assert events[membership_ids[0]].evidence[0].metadata["transition_id"] == "passed_crash_check"
    assert events[membership_ids[0]].evidence[0].metadata["criteria"] == {"otherwise": True}
    assert events[membership_ids[0]].evidence[0].metadata["observed"]["completed_episodes"] == 1
    assert membership_ids[1] not in events


def test_ruleset_strategy_among_them_config_scheduled_qualifier_without_scores_fails_crash_check() -> None:
    qualifier_id = uuid4()
    policy_version_id = uuid4()
    membership_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=8,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=policy_version_id,
            player_id="qualifier",
            status="qualifying",
        )
    ]

    complete = complete_round_for_round_start(
        _ruleset_commissioner("among_them"),
        round_start,
        [],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[policy_version_id] * 8,
            )
        ],
        failed_episodes=[ProtocolEpisodeFailed(request_id="0", error="container exited")],
    )

    assert len(complete.policy_membership_events) == 1
    event = complete.policy_membership_events[0]
    assert event.league_policy_membership_id == membership_id
    assert event.to_division_id is None
    assert event.status == "disqualified"
    assert event.substatus == "inactive"
    assert event.reason == "Failed crash test"
    assert event.evidence[0].metadata["transition_id"] == "failed_crash_check"
    assert event.evidence[0].metadata["criteria"] == {"completed_episodes_lte": 0}
    assert event.evidence[0].metadata["observed"] == {
        "completed_episodes": 0,
        "failed_episodes": 1,
        "scheduled_episodes": 1,
        "score": 0.0,
    }
    assert event.evidence[0].metadata["failed_request_ids"] == ["0"]
    assert event.evidence[0].metadata["failure_error_samples"] == ["container exited"]


def test_ruleset_strategy_among_them_score_gate_ignores_unscheduled_crash_check_member() -> None:
    qualifier_id = uuid4()
    competition_id = uuid4()
    crash_check_policy_id = uuid4()
    score_gate_policy_id = uuid4()
    crash_check_membership_id = uuid4()
    score_gate_membership_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=8,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        extra_divisions=[DivisionInfo(id=competition_id, name="Daily", level=0, type="competition")],
        state={
            "round_config": {
                "current_division_id": str(qualifier_id),
                "entrant_policy_version_ids": [str(score_gate_policy_id)],
            }
        },
    )
    round_start.memberships = [
        MembershipInfo(
            id=crash_check_membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=crash_check_policy_id,
            player_id="crash-check-player",
            status="qualifying",
        ),
        MembershipInfo(
            id=score_gate_membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=score_gate_policy_id,
            player_id="score-gate-player",
            status="qualifying",
            substatus="score_gate",
        ),
    ]

    complete = complete_round_for_round_start(
        _ruleset_commissioner("among_them"),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=score_gate_policy_id, score=1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[score_gate_policy_id] * 8,
            )
        ],
    )

    events = {event.league_policy_membership_id: event for event in complete.policy_membership_events}
    assert crash_check_membership_id not in events
    assert events[score_gate_membership_id].to_division_id == competition_id
    assert events[score_gate_membership_id].status == "competing"
    assert events[score_gate_membership_id].reason == "Passed score gate"


def test_ruleset_strategy_among_them_config_prioritizes_later_qualifier_stage_when_mixed() -> None:
    league_id = uuid4()
    qualifier_id = uuid4()
    crash_check_policy_id = uuid4()
    score_gate_policy_id = uuid4()

    response = schedule_rounds_for_request(
        _ruleset_commissioner("among_them"),
        ScheduleRoundsRequest(
            league=LeagueInfo(id=league_id, commissioner_config={}),
            divisions=[DivisionInfo(id=qualifier_id, name="Qualifiers", level=-1, type="staging")],
            active_memberships=[
                MembershipInfo(
                    id=uuid4(),
                    league_id=league_id,
                    division_id=qualifier_id,
                    policy_version_id=crash_check_policy_id,
                    player_id="crash-check-player",
                    status="qualifying",
                ),
                MembershipInfo(
                    id=uuid4(),
                    league_id=league_id,
                    division_id=qualifier_id,
                    policy_version_id=score_gate_policy_id,
                    player_id="score-gate-player",
                    status="qualifying",
                    substatus="score_gate",
                ),
            ],
            recent_rounds=[],
        ),
    )

    assert len(response.rounds) == 1
    assert response.rounds[0].round_config.stages is not None
    assert response.rounds[0].round_config.stages[0].label == "Score gate"
    assert response.rounds[0].round_config.entrant_policy_version_ids == [score_gate_policy_id]


def test_ruleset_strategy_among_them_config_preserves_scoring_mechanics_description() -> None:
    division_id = uuid4()
    league_id = uuid4()
    policy_version_ids = [uuid4() for _ in range(8)]

    response = describe_division_for_request(
        _ruleset_commissioner("among_them"),
        DescribeDivisionRequest(
            league=LeagueInfo(id=league_id, commissioner_config={}),
            division=DivisionInfo(id=division_id, name="Wood", level=0, type="competition"),
            active_memberships=[
                MembershipInfo(
                    id=uuid4(),
                    league_id=league_id,
                    division_id=division_id,
                    policy_version_id=policy_version_id,
                    status="competing",
                    substatus="champion",
                    is_champion=True,
                )
                for policy_version_id in policy_version_ids
            ],
            recent_rounds=[],
        ),
    )

    assert response.description.scoring_mechanics == MEAN_SCORE_EWMA_SCORING_MECHANICS


def test_ruleset_strategy_describe_empty_configured_division_uses_configured_minimum() -> None:
    division_id = uuid4()
    league_id = uuid4()

    response = describe_division_for_request(
        _ruleset_commissioner("among_them"),
        DescribeDivisionRequest(
            league=LeagueInfo(id=league_id, commissioner_config={}),
            division=DivisionInfo(id=division_id, name="Wood", level=0, type="competition"),
            active_memberships=[],
            recent_rounds=[],
        ),
    )

    assert response.description.next_round == "Add 8 more entrants before scheduling can continue."


def test_ruleset_strategy_among_them_scoring_config_does_not_add_version_metadata() -> None:
    policy_version_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[policy_version_id],
        num_agents=8,
        commissioner_config={},
        division_name="Wood",
    )

    complete = complete_round_for_round_start(
        _ruleset_commissioner("among_them"),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=policy_version_id, score=3.0)],
            )
        ],
    )

    metadata = complete.results[0].rankings[0].result_metadata
    assert metadata["score_kind"] == MEAN_ROUND_SCORE_KIND
    assert "version" not in metadata


def test_ruleset_strategy_competition_round_never_auto_disqualifies() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=8,
        commissioner_config={},
        division_name="Wood",
    )

    complete = complete_round_for_round_start(
        _ruleset_commissioner("among_them"),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[
                    EpisodeScore(policy_version_id=policy_version_ids[0], score=-2.0),
                    EpisodeScore(policy_version_id=policy_version_ids[1], score=1.0),
                ],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id=str(index),
                variant_id="default",
                policy_version_ids=[policy_version_ids[0], policy_version_ids[1]] * 4,
            )
            for index in range(3)
        ],
    )

    assert complete.policy_membership_events == []


def test_ruleset_strategy_scoring_configures_leaderboard_ewma_halflife() -> None:
    division_id = uuid4()
    latest_round_id = uuid4()
    older_round_id = uuid4()
    latest_policy_id = uuid4()
    older_policy_id = uuid4()
    score_metadata = {"score_kind": MEAN_ROUND_SCORE_KIND}

    config = {
        "scoring": {
            "round_score": "mean",
            "leaderboard": {"type": "ewma", "half_life_hours": 1},
        },
        "divisions": {"competition": {"match": {"type": "competition"}, "entrants": "champions"}},
    }
    response = rank_division_for_request(
        RulesetStrategyCommissioner(config),
        RankDivisionRequest(
            league=LeagueInfo(id=uuid4(), commissioner_config={}),
            division=DivisionInfo(id=division_id, name="Wood", level=0, type="competition"),
            completed_rounds=[
                RoundInfo(
                    id=latest_round_id,
                    division_id=division_id,
                    round_number=2,
                    status="completed",
                    completed_at="2026-06-07T02:00:00+00:00",
                ),
                RoundInfo(
                    id=older_round_id,
                    division_id=division_id,
                    round_number=1,
                    status="completed",
                    completed_at="2026-06-07T00:00:00+00:00",
                ),
            ],
            recent_rounds=[],
            round_results=[
                LeaderboardRoundResultInfo(
                    round_id=latest_round_id,
                    policy_version_id=latest_policy_id,
                    player_id="player-1",
                    rank=1,
                    score=10.0,
                    result_metadata=score_metadata,
                ),
                LeaderboardRoundResultInfo(
                    round_id=older_round_id,
                    policy_version_id=older_policy_id,
                    player_id="player-1",
                    rank=1,
                    score=0.0,
                    result_metadata=score_metadata,
                ),
            ],
        ),
    )

    assert response.rankings[0].score == pytest.approx(8.0)


def test_baseline_round_start_uses_is_champion_for_competition_entries() -> None:
    division_id = uuid4()
    boolean_champion_id = uuid4()
    explicit_non_champion_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        division_id=division_id,
        state={"round_config": {"current_division_id": str(division_id)}},
    )
    round_start.memberships = [
        MembershipInfo(
            id=uuid4(),
            league_id=round_start.league.id,
            division_id=division_id,
            policy_version_id=boolean_champion_id,
            status="competing",
            substatus=None,
            is_champion=True,
        ),
        MembershipInfo(
            id=uuid4(),
            league_id=round_start.league.id,
            division_id=division_id,
            policy_version_id=explicit_non_champion_id,
            status="competing",
            substatus="champion",
            is_champion=False,
        ),
    ]

    schedule = schedule_episodes_for_round_start(BaselineCommissioner(), round_start)

    scheduled_policy_ids = {policy_id for episode in schedule.episodes for policy_id in episode.policy_version_ids}
    assert scheduled_policy_ids == {boolean_champion_id}


def test_baseline_round_completion_marks_default_competing_substatuses() -> None:
    division_id = uuid4()
    champion_membership_id = uuid4()
    benched_membership_id = uuid4()
    champion_policy_id = uuid4()
    benched_policy_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        division_id=division_id,
        state={"round_config": {"current_division_id": str(division_id)}},
    )
    round_start.memberships = [
        MembershipInfo(
            id=champion_membership_id,
            league_id=round_start.league.id,
            division_id=division_id,
            policy_version_id=champion_policy_id,
            status="competing",
            substatus=None,
            is_champion=True,
        ),
        MembershipInfo(
            id=benched_membership_id,
            league_id=round_start.league.id,
            division_id=division_id,
            policy_version_id=benched_policy_id,
            status="competing",
            substatus=None,
            is_champion=False,
        ),
    ]

    complete = complete_round_for_round_start(
        BaselineCommissioner(),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=champion_policy_id, score=1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[champion_policy_id] * 2,
            )
        ],
    )

    events = {event.league_policy_membership_id: event for event in complete.policy_membership_events}
    assert events[champion_membership_id].status == "competing"
    assert events[champion_membership_id].substatus == "active"
    assert events[benched_membership_id].status == "competing"
    assert events[benched_membership_id].substatus == "benched"


def test_default_competing_substatus_marks_skip_existing_values() -> None:
    division_id = uuid4()
    champion_policy_id = uuid4()
    benched_policy_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        division_id=division_id,
        state={"round_config": {"current_division_id": str(division_id)}},
    )
    round_start.memberships = [
        MembershipInfo(
            id=uuid4(),
            league_id=round_start.league.id,
            division_id=division_id,
            policy_version_id=champion_policy_id,
            status="competing",
            substatus="active",
            is_champion=True,
        ),
        MembershipInfo(
            id=uuid4(),
            league_id=round_start.league.id,
            division_id=division_id,
            policy_version_id=benched_policy_id,
            status="competing",
            substatus="benched",
            is_champion=False,
        ),
    ]

    complete = complete_round_for_round_start(
        BaselineCommissioner(),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=champion_policy_id, score=1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[champion_policy_id] * 2,
            )
        ],
    )

    assert complete.policy_membership_events == []


def test_ruleset_membership_change_skips_noop_status_substatus_and_division() -> None:
    division_id = uuid4()
    policy_id = uuid4()
    config = {
        "defaults": {"min_entries_to_start": 1, "stage": {"label": "Round", "episodes": 1}},
        "divisions": {
            "competition": {
                "match": {"type": "competition"},
                "entrants": {"status": "competing", "substatus": "active", "match_substatus": True},
                "on_round_complete": [
                    {
                        "id": "already_active",
                        "criteria": "otherwise",
                        "actions": [
                            {
                                "type": "update_membership",
                                "status": "competing",
                                "substatus": "active",
                            }
                        ],
                    }
                ],
            }
        },
    }
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        division_id=division_id,
        state={"round_config": {"current_division_id": str(division_id)}},
    )
    round_start.memberships = [
        MembershipInfo(
            id=uuid4(),
            league_id=round_start.league.id,
            division_id=division_id,
            policy_version_id=policy_id,
            status="competing",
            substatus="active",
            is_champion=True,
        )
    ]

    complete = complete_round_for_round_start(
        RulesetStrategyCommissioner(config),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=policy_id, score=1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[policy_id] * 2,
            )
        ],
    )

    assert complete.policy_membership_events == []


def test_ruleset_champions_selector_uses_is_champion() -> None:
    division_id = uuid4()
    boolean_champion_id = uuid4()
    explicit_non_champion_id = uuid4()
    config = {
        "defaults": {"min_entries_to_start": 1, "stage": {"label": "Round", "episodes": 1}},
        "divisions": {"competition": {"match": {"type": "competition"}, "entrants": "champions"}},
    }
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        commissioner_config={},
        division_id=division_id,
        state={"round_config": {"current_division_id": str(division_id)}},
    )
    round_start.memberships = [
        MembershipInfo(
            id=uuid4(),
            league_id=round_start.league.id,
            division_id=division_id,
            policy_version_id=boolean_champion_id,
            status="competing",
            substatus=None,
            is_champion=True,
        ),
        MembershipInfo(
            id=uuid4(),
            league_id=round_start.league.id,
            division_id=division_id,
            policy_version_id=explicit_non_champion_id,
            status="competing",
            substatus="champion",
            is_champion=False,
        ),
    ]

    schedule = schedule_episodes_for_round_start(RulesetStrategyCommissioner(config), round_start)

    scheduled_policy_ids = {policy_id for episode in schedule.episodes for policy_id in episode.policy_version_ids}
    assert scheduled_policy_ids == {boolean_champion_id}


def test_ruleset_round_start_uses_persisted_stage_config() -> None:
    division_id = uuid4()
    champion_ids = [uuid4(), uuid4(), uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=champion_ids,
        num_agents=2,
        division_id=division_id,
        state={
            "round_config": {
                "current_division_id": str(division_id),
                "stages": [{"label": "Round", "num_episodes": 1, "min_episodes_per_entrant": 1}],
            }
        },
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("default"), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        champion_ids[:2],
        champion_ids[2:],
    ]


def test_ruleset_round_start_ignores_null_persisted_stage_fields() -> None:
    division_id = uuid4()
    champion_ids = [uuid4(), uuid4(), uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=champion_ids,
        num_agents=2,
        division_id=division_id,
        state={
            "round_config": {
                "current_division_id": str(division_id),
                "stages": [{"label": "Round", "num_episodes": 1, "min_episodes_per_entrant": None}],
            }
        },
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("default"), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        champion_ids[:2],
        champion_ids[2:],
    ]


def test_cogs_vs_clips_config_qualifier_round_start_restores_private_self_play() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=8,
        commissioner_config={
            "minimum_champions": 5,
            "qualifiers_division_name": "Qualifiers",
            "qualifier_stages": [
                {"label": "Qualifier", "num_episodes": 2, "min_episodes_per_entrant": 2, "self_play": True}
            ],
        },
        division_name="Qualifiers",
        division_type="staging",
        state={
            "round_config": {
                "stages": [
                    {
                        "label": "Qualifier",
                        "num_episodes": 2,
                        "min_episodes_per_entrant": 2,
                    }
                ]
            }
        },
    )

    schedule = schedule_episodes_for_round_start(_ruleset_commissioner("cogs_vs_clips"), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0]] * 8,
        [policy_version_ids[0]] * 8,
        [policy_version_ids[1]] * 8,
        [policy_version_ids[1]] * 8,
    ]


def test_ruleset_strategy_commissioner_fills_short_round_from_configured_division() -> None:
    primary_policy_id = uuid4()
    filler_policy_ids = [uuid4(), uuid4()]
    daily_id = uuid4()
    filler_id = uuid4()
    config = {
        "defaults": {
            "seating": "rolling_window",
            "fill_seats": "fill_from_divisions",
            "fill_from": [
                {
                    "match": {"name": "Fillers"},
                    "entrants": {"status": "competing", "substatus": "champion", "match_substatus": True},
                }
            ],
        },
        "divisions": {
            "daily": {
                "match": {"name": "Daily"},
                "min_entries_to_start": 1,
                "stage": {"label": "Daily", "episodes": 1},
            },
        },
    }
    round_start = _round_start(
        policy_version_ids=[primary_policy_id],
        num_agents=3,
        commissioner_config={},
        division_name="Daily",
        division_id=daily_id,
        extra_divisions=[DivisionInfo(id=filler_id, name="Fillers", level=1, type="competition")],
        state={"round_config": {"current_division_id": str(daily_id)}},
    )
    round_start.memberships.extend(
        [
            MembershipInfo(
                id=uuid4(),
                league_id=round_start.league.id,
                division_id=filler_id,
                policy_version_id=policy_version_id,
                player_id=f"filler-{index}",
                status="competing",
                substatus="champion",
                is_champion=True,
            )
            for index, policy_version_id in enumerate(filler_policy_ids)
        ]
    )

    schedule = schedule_episodes_for_round_start(RulesetStrategyCommissioner(config), round_start)

    assert len(schedule.episodes) == 1
    assert schedule.episodes[0].policy_version_ids == [primary_policy_id, *filler_policy_ids]


def test_ruleset_strategy_commissioner_advances_qualifier_substatus_after_completed_stage() -> None:
    qualifier_id = uuid4()
    policy_version_ids = [uuid4(), uuid4()]
    membership_ids = [uuid4(), uuid4()]
    config = {
        "divisions": {
            "qualifiers": {
                "match": {"name": "Qualifiers", "type": "staging"},
                "entrants": {"status": "qualifying", "substatus": None, "match_substatus": True},
                "min_entries_to_start": 1,
                "stages": [
                    {
                        "id": "qualifier_stage_1",
                        "schedule": {
                            "label": "Qualifier stage 1",
                            "attempts": 1,
                            "min_episodes_per_entrant": 1,
                            "self_play": True,
                        },
                        "on_episode_complete": [
                            {
                                "id": "completed",
                                "criteria": {"completed_episodes_gt": 0},
                                "actions": [
                                    {
                                        "type": "update_membership",
                                        "status": "qualifying",
                                        "substatus": "qualifier_stage_2",
                                    }
                                ],
                            },
                            {
                                "id": "failed",
                                "criteria": "otherwise",
                                "actions": [
                                    {
                                        "type": "update_membership",
                                        "status": "disqualified",
                                        "substatus": "inactive",
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        },
    }
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        state={"round_config": {"current_division_id": str(qualifier_id)}},
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=policy_version_id,
            player_id=f"qualifier-{index}",
            status="qualifying",
            substatus=None,
        )
        for index, (membership_id, policy_version_id) in enumerate(
            zip(membership_ids, policy_version_ids, strict=True)
        )
    ]

    complete = complete_round_for_round_start(
        RulesetStrategyCommissioner(config),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[EpisodeScore(policy_version_id=policy_version_ids[0], score=1.0)],
            )
        ],
        [
            ProtocolEpisodeRequest(
                request_id="0",
                variant_id="default",
                policy_version_ids=[policy_version_ids[0]] * 2,
            ),
            ProtocolEpisodeRequest(
                request_id="1",
                variant_id="default",
                policy_version_ids=[policy_version_ids[1]] * 2,
            ),
        ],
    )

    events = {event.league_policy_membership_id: event for event in complete.policy_membership_events}
    assert events[membership_ids[0]].status == "qualifying"
    assert events[membership_ids[0]].substatus == "qualifier_stage_2"
    assert events[membership_ids[0]].to_division_id == qualifier_id
    assert events[membership_ids[1]].status == "disqualified"
    assert events[membership_ids[1]].substatus == "inactive"
    assert events[membership_ids[1]].to_division_id is None


def test_ruleset_strategy_commissioner_stage_two_score_gate_enters_competition() -> None:
    qualifier_id = uuid4()
    competition_id = uuid4()
    policy_version_ids = [uuid4(), uuid4()]
    membership_ids = [uuid4(), uuid4()]
    config = {
        "divisions": {
            "qualifiers": {
                "match": {"name": "Qualifiers", "type": "staging"},
                "entrants": {
                    "status": "qualifying",
                    "substatus": "qualifier_stage_2",
                    "match_substatus": True,
                },
                "min_entries_to_start": 1,
                "stages": [
                    {
                        "id": "qualifier_stage_2",
                        "schedule": {"label": "Qualifier stage 2", "episodes": 1},
                        "on_episode_complete": [
                            {
                                "id": "passed_score_gate",
                                "criteria": {"score_gt": 0},
                                "actions": [
                                    {
                                        "type": "update_membership",
                                        "division": "competition",
                                        "status": "competing",
                                        "substatus": "champion",
                                    }
                                ],
                            },
                            {
                                "id": "failed_score_gate",
                                "criteria": "otherwise",
                                "actions": [
                                    {
                                        "type": "update_membership",
                                        "status": "disqualified",
                                        "substatus": "inactive",
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
            "competition": {
                "match": {"name": "Daily", "type": "competition"},
                "entrants": "champions",
            },
        },
    }
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        commissioner_config={},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        extra_divisions=[DivisionInfo(id=competition_id, name="Daily", level=0, type="competition")],
        state={"round_config": {"current_division_id": str(qualifier_id)}},
    )
    round_start.memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=round_start.league.id,
            division_id=qualifier_id,
            policy_version_id=policy_version_id,
            player_id=f"qualifier-{index}",
            status="qualifying",
            substatus="qualifier_stage_2",
        )
        for index, (membership_id, policy_version_id) in enumerate(
            zip(membership_ids, policy_version_ids, strict=True)
        )
    ]

    complete = complete_round_for_round_start(
        RulesetStrategyCommissioner(config),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[
                    EpisodeScore(policy_version_id=policy_version_ids[0], score=1.0),
                    EpisodeScore(policy_version_id=policy_version_ids[1], score=0.0),
                ],
            )
        ],
    )

    events = {event.league_policy_membership_id: event for event in complete.policy_membership_events}
    assert events[membership_ids[0]].to_division_id == competition_id
    assert events[membership_ids[0]].status == "competing"
    assert events[membership_ids[0]].substatus == "champion"
    assert events[membership_ids[1]].to_division_id is None
    assert events[membership_ids[1]].status == "disqualified"
    assert events[membership_ids[1]].substatus == "inactive"


def test_round_start_adapter_uses_extracted_commissioner_api() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
        commissioner_config={"num_episodes": 1},
    )

    schedule = schedule_episodes_for_round_start(BaselineCommissioner(), round_start)

    assert schedule.episodes[0].policy_version_ids == policy_version_ids


def test_default_round_start_schedules_every_active_membership() -> None:
    policy_version_ids = [uuid4() for _ in range(5)]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
    )

    schedule = schedule_episodes_for_round_start(BaselineCommissioner(), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0], policy_version_ids[1]],
        [policy_version_ids[2], policy_version_ids[3]],
        [policy_version_ids[4], policy_version_ids[0]],
    ]
    scheduled_policy_ids = {policy_id for episode in schedule.episodes for policy_id in episode.policy_version_ids}
    assert scheduled_policy_ids == set(policy_version_ids)


def test_round_start_adapter_uses_configured_competition_division_entries() -> None:
    qualifier_id = uuid4()
    competition_id = uuid4()
    qualifier_policy_id = uuid4()
    champion_policy_ids = [uuid4(), uuid4()]
    non_champion_policy_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[qualifier_policy_id],
        num_agents=2,
        commissioner_config={"qualifiers_division_name": "Qualifiers", "minimum_champions": 2},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        extra_divisions=[DivisionInfo(id=competition_id, name="Wood", level=1, type="competition")],
        state={"round_config": {"current_division_id": str(competition_id)}},
    )
    round_start.memberships.extend(
        [
            MembershipInfo(
                id=uuid4(),
                league_id=round_start.league.id,
                division_id=competition_id,
                policy_version_id=policy_version_id,
                player_id=f"competition-player-{index}",
                status="competing",
                substatus="champion",
                is_champion=True,
            )
            for index, policy_version_id in enumerate(champion_policy_ids)
        ]
    )
    round_start.memberships.append(
        MembershipInfo(
            id=uuid4(),
            league_id=round_start.league.id,
            division_id=competition_id,
            policy_version_id=non_champion_policy_id,
            player_id="non-champion-player",
            status="competing",
        )
    )

    schedule = schedule_episodes_for_round_start(BaselineCommissioner(), round_start)

    assert schedule.episodes
    scheduled_policy_ids = {policy_id for episode in schedule.episodes for policy_id in episode.policy_version_ids}
    assert scheduled_policy_ids == set(champion_policy_ids)


def test_round_start_adapter_allows_non_champion_qualifier_entries() -> None:
    qualifier_id = uuid4()
    competition_id = uuid4()
    qualifier_policy_ids = [uuid4(), uuid4()]
    competition_policy_id = uuid4()
    round_start = _round_start(
        policy_version_ids=[],
        num_agents=2,
        commissioner_config={"qualifiers_division_name": "Qualifiers", "minimum_champions": 2},
        division_name="Qualifiers",
        division_id=qualifier_id,
        division_type="staging",
        extra_divisions=[DivisionInfo(id=competition_id, name="Wood", level=1, type="competition")],
        state={"round_config": {"current_division_id": str(qualifier_id)}},
    )
    round_start.memberships.extend(
        [
            MembershipInfo(
                id=uuid4(),
                league_id=round_start.league.id,
                division_id=qualifier_id,
                policy_version_id=policy_version_id,
                player_id=f"qualifier-player-{index}",
                status="qualifying",
            )
            for index, policy_version_id in enumerate(qualifier_policy_ids)
        ]
    )
    round_start.memberships.append(
        MembershipInfo(
            id=uuid4(),
            league_id=round_start.league.id,
            division_id=competition_id,
            policy_version_id=competition_policy_id,
            player_id="competition-player",
            status="competing",
            substatus="champion",
            is_champion=True,
        )
    )

    schedule = schedule_episodes_for_round_start(BaselineCommissioner(), round_start)

    assert schedule.episodes
    scheduled_policy_ids = {policy_id for episode in schedule.episodes for policy_id in episode.policy_version_ids}
    assert scheduled_policy_ids == set(qualifier_policy_ids)


def test_round_start_adapter_requires_division_id_to_target_the_round_division() -> None:
    """Regression for the deployed bug, framed as a parity requirement.

    The container commissioner must schedule episodes for the SAME entrants the
    backend's non-container path would pick for the round's division. When the
    backend sends memberships spanning multiple divisions, the only reliable way to
    identify the round's division is ``current_division_id``. Without it,
    ``_current_division`` falls back to a level/name heuristic and resolves to the
    WRONG division (the production failure: Wood/Dirt rounds ran the wrong entrants
    or none at all). With it, the adapter targets the intended division exactly.
    """
    qualifier_id = uuid4()
    dirt_id = uuid4()
    wood_id = uuid4()
    dirt_champion_ids = [uuid4(), uuid4()]
    wood_champion_ids = [uuid4(), uuid4()]

    def _wood_round_start(state: dict | None) -> RoundStart:
        round_start = _round_start(
            policy_version_ids=[],
            num_agents=2,
            commissioner_config={"qualifiers_division_name": "Qualifiers", "minimum_champions": 2},
            division_name="Qualifiers",
            division_id=qualifier_id,
            division_type="staging",
            extra_divisions=[
                DivisionInfo(id=dirt_id, name="Dirt", level=0, type="competition"),
                DivisionInfo(id=wood_id, name="Wood", level=1, type="competition"),
            ],
            state=state,
        )
        round_start.memberships.extend(
            MembershipInfo(
                id=uuid4(),
                league_id=round_start.league.id,
                division_id=division_id,
                policy_version_id=policy_version_id,
                player_id=f"champion-{index}",
                status="competing",
                substatus="champion",
                is_champion=True,
            )
            for division_id, champion_ids in ((dirt_id, dirt_champion_ids), (wood_id, wood_champion_ids))
            for index, policy_version_id in enumerate(champion_ids)
        )
        return round_start

    # With current_division_id: the Wood round runs exactly the Wood champions.
    targeted = schedule_episodes_for_round_start(
        BaselineCommissioner(), _wood_round_start({"round_config": {"current_division_id": str(wood_id)}})
    )
    targeted_policy_ids = {policy_id for episode in targeted.episodes for policy_id in episode.policy_version_ids}
    assert targeted_policy_ids == set(wood_champion_ids)
    assert targeted_policy_ids.isdisjoint(dirt_champion_ids)

    # Without current_division_id: the adapter cannot identify the Wood division and
    # picks the wrong entrants — never the intended Wood champions in full.
    misrouted = schedule_episodes_for_round_start(BaselineCommissioner(), _wood_round_start(None))
    misrouted_policy_ids = {policy_id for episode in misrouted.episodes for policy_id in episode.policy_version_ids}
    assert misrouted_policy_ids != set(wood_champion_ids)


def test_round_start_adapter_separates_qualifier_and_competition_entrants_in_one_league() -> None:
    """The production shape: a single league whose membership set spans an active
    self-play qualifier division and a competition division with champions. Each
    round must only run its own division's entrants.
    """
    qualifier_id = uuid4()
    competition_id = uuid4()
    qualifier_policy_ids = [uuid4(), uuid4()]
    champion_policy_ids = [uuid4(), uuid4(), uuid4()]
    non_champion_competition_id = uuid4()
    commissioner_config = {
        "qualifiers_division_name": "Qualifiers",
        "minimum_champions": 2,
        "stages": [{"label": "Round", "num_episodes": 1, "min_episodes_per_entrant": 8}],
        "qualifier_stages": [
            {"label": "Qualifier", "num_episodes": 2, "min_episodes_per_entrant": 2, "self_play": True}
        ],
    }
    # The backend persists the division-appropriate stage list onto the round and
    # threads it back through round_config.stages, exactly as schedule_rounds emits it.
    qualifier_stages = commissioner_config["qualifier_stages"]
    competition_stages = commissioner_config["stages"]

    def _mixed_round_start(current_division_id: UUID, stages: list[dict]) -> RoundStart:
        round_start = _round_start(
            policy_version_ids=[],
            num_agents=2,
            commissioner_config=commissioner_config,
            division_name="Qualifiers",
            division_id=qualifier_id,
            division_type="staging",
            extra_divisions=[DivisionInfo(id=competition_id, name="Daily", level=1, type="competition")],
            state={"round_config": {"current_division_id": str(current_division_id), "stages": stages}},
        )
        round_start.memberships.extend(
            MembershipInfo(
                id=uuid4(),
                league_id=round_start.league.id,
                division_id=qualifier_id,
                policy_version_id=policy_version_id,
                player_id=f"qualifier-player-{index}",
                status="qualifying",
            )
            for index, policy_version_id in enumerate(qualifier_policy_ids)
        )
        round_start.memberships.extend(
            MembershipInfo(
                id=uuid4(),
                league_id=round_start.league.id,
                division_id=competition_id,
                policy_version_id=policy_version_id,
                player_id=f"champion-player-{index}",
                status="competing",
                substatus="champion",
                is_champion=True,
            )
            for index, policy_version_id in enumerate(champion_policy_ids)
        )
        round_start.memberships.append(
            MembershipInfo(
                id=uuid4(),
                league_id=round_start.league.id,
                division_id=competition_id,
                policy_version_id=non_champion_competition_id,
                player_id="non-champion-player",
                status="competing",
            )
        )
        return round_start

    qualifier_schedule = schedule_episodes_for_round_start(
        _ruleset_commissioner("cogs_vs_clips"), _mixed_round_start(qualifier_id, qualifier_stages)
    )
    qualifier_scheduled = {
        policy_id for episode in qualifier_schedule.episodes for policy_id in episode.policy_version_ids
    }
    # Qualifier round: self-play over the qualifier members only; no champions leak in.
    assert qualifier_scheduled == set(qualifier_policy_ids)
    for episode in qualifier_schedule.episodes:
        assert len(set(episode.policy_version_ids)) == 1, "qualifier stage must be self-play"

    competition_schedule = schedule_episodes_for_round_start(
        _ruleset_commissioner("cogs_vs_clips"), _mixed_round_start(competition_id, competition_stages)
    )
    competition_scheduled = {
        policy_id for episode in competition_schedule.episodes for policy_id in episode.policy_version_ids
    }
    # Competition round: champions only; the non-champion and all qualifier members excluded.
    assert competition_scheduled == set(champion_policy_ids)
    assert non_champion_competition_id not in competition_scheduled
    assert competition_scheduled.isdisjoint(qualifier_policy_ids)


class HookResponseCommissioner(BaselineCommissioner):
    def on_round_completed(self, ctx: OnRoundCompletedContext) -> OnRoundCompletedResult:
        membership = ctx.division_memberships[0]
        return OnRoundCompletedResult(
            policy_membership_events=[
                PolicyMembershipEventChange(
                    league_policy_membership_id=membership.id,
                    from_division_id=membership.division_id,
                    to_division_id=ctx.division.id,
                    status="competing",
                    substatus="champion",
                    reason="new event path is config-driven only",
                )
            ],
            membership_changes=[
                MembershipChange(
                    membership_id=membership.id,
                    from_division_id=membership.division_id,
                    to_division_id=ctx.division.id,
                    reason="mapped",
                )
            ],
            follow_up_rounds=[
                RoundSpec(
                    division_id=ctx.division.id,
                    round_config=V2RoundConfig(),
                    execution_backend="mock",
                )
            ],
        )


def test_extended_hook_adapters_map_internal_models_to_protocol_models() -> None:
    division_id = uuid4()
    league_id = uuid4()
    membership_id = uuid4()
    policy_version_id = uuid4()
    round_id = uuid4()
    commissioner = HookResponseCommissioner()

    schedule_response = schedule_rounds_for_request(
        commissioner,
        ScheduleRoundsRequest(
            league=LeagueInfo(id=league_id, commissioner_config={"minimum_champions": 1}),
            divisions=[DivisionInfo(id=division_id, name="Bronze", level=0)],
            active_memberships=[
                MembershipInfo(
                    id=membership_id,
                    league_id=league_id,
                    division_id=division_id,
                    policy_version_id=policy_version_id,
                    status="competing",
                    substatus="champion",
                    is_champion=True,
                )
            ],
            recent_rounds=[],
        ),
    )
    assert schedule_response.to_json()["type"] == "schedule_rounds_response"
    assert schedule_response.rounds[0].division_id == division_id

    rank_response = rank_division_for_request(
        commissioner,
        RankDivisionRequest(
            league=LeagueInfo(id=league_id),
            division=DivisionInfo(id=division_id, name="Bronze", level=0),
            completed_rounds=[
                RoundInfo(
                    id=round_id,
                    public_id="round_test",
                    division_id=division_id,
                    round_number=1,
                    status="completed",
                    completed_at="2026-05-29T00:00:00+00:00",
                )
            ],
            recent_rounds=[],
            round_results=[
                LeaderboardRoundResultInfo(
                    round_id=round_id,
                    policy_version_id=policy_version_id,
                    player_id="player-1",
                    rank=1,
                    score=4.0,
                )
            ],
        ),
    )
    assert rank_response.to_json()["type"] == "rank_division_response"
    assert rank_response.rankings[0].player_id == "player-1"

    describe_response = describe_division_for_request(
        commissioner,
        DescribeDivisionRequest(
            league=LeagueInfo(id=league_id, commissioner_config={"minimum_champions": 1}),
            division=DivisionInfo(id=division_id, name="Bronze", level=0),
            active_memberships=[
                MembershipInfo(
                    id=membership_id,
                    league_id=league_id,
                    division_id=division_id,
                    policy_version_id=policy_version_id,
                    status="competing",
                    substatus="champion",
                    is_champion=True,
                )
            ],
            recent_rounds=[],
        ),
    )
    assert describe_response.to_json()["type"] == "describe_division_response"
    assert describe_response.description.round_schedule is not None

    completed_response = round_completed_for_request(
        commissioner,
        RoundCompletedRequest(
            league=LeagueInfo(id=league_id),
            division=DivisionInfo(id=division_id, name="Bronze", level=0),
            all_divisions=[DivisionInfo(id=division_id, name="Bronze", level=0)],
            round_config=RoundConfig(),
            round_results=[
                RoundResultInfo(
                    round_id=round_id,
                    policy_version_id=policy_version_id,
                    rank=1,
                    score=4.0,
                )
            ],
            division_memberships=[
                MembershipInfo(
                    id=membership_id,
                    league_id=league_id,
                    division_id=division_id,
                    policy_version_id=policy_version_id,
                    status="competing",
                    substatus="champion",
                    is_champion=True,
                )
            ],
            recent_results=[],
        ),
    )
    assert completed_response.to_json()["type"] == "round_completed_response"
    assert completed_response.follow_up_rounds[0].division_id == division_id
    assert len(completed_response.policy_membership_events) == 1
    assert completed_response.policy_membership_events[0].league_policy_membership_id == membership_id
    assert completed_response.policy_membership_events[0].status == "competing"
    assert completed_response.membership_changes == [
        ProtocolMembershipChange(
            membership_id=membership_id,
            from_division_id=division_id,
            to_division_id=division_id,
            reason="mapped",
        )
    ]
