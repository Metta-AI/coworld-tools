from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from commissioners.common.protocol import (
    DescribeDivisionRequest,
    DivisionInfo,
    EpisodeResult as ProtocolEpisodeResult,
    EpisodeScore,
    LeaderboardRoundResultInfo,
    LeagueInfo,
    MembershipChange as ProtocolMembershipChange,
    MembershipInfo,
    RankDivisionRequest,
    RoundCompletedRequest,
    RoundConfig,
    RoundInfo,
    RoundResultInfo,
    ScheduleRoundsRequest,
    RoundStart,
    VariantInfo,
)
from commissioners.common.commissioners import (
    AMONG_THEM_RESULT_METADATA_VERSION,
    AMONG_THEM_SCORE_KIND,
    AmongThemCommissioner,
    BaselineCommissioner,
    CogsVsClipsCommissioner,
    EpisodeResult,
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
    rank_division_for_request,
    round_completed_for_request,
    schedule_episodes_for_round_start,
    schedule_rounds_for_request,
)


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
    divisions = [
        DivisionInfo(id=active_division_id, name=division_name, level=0, type=division_type),
        *(extra_divisions or []),
    ]
    return RoundStart(
        round_id=uuid4(),
        round_number=1,
        league=LeagueInfo(id=uuid4(), commissioner_config=commissioner_config or {}),
        divisions=divisions,
        memberships=[
            MembershipInfo(
                id=uuid4(),
                division_id=active_division_id,
                policy_version_id=policy_version_id,
                player_id=f"player-{index}",
                is_champion=True,
            )
            for index, policy_version_id in enumerate(policy_version_ids)
        ],
        recent_results=[],
        variants=[
            VariantInfo(
                id="default",
                name="Default",
                game_config={"num_agents": num_agents},
                num_agents=num_agents,
            )
        ],
        state=state,
    )


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


def test_among_them_schedule_matches_current_wide_pool_examples() -> None:
    policy_version_ids = [uuid4() for _ in range(16)]
    pool = PolicyPool(
        id=uuid4(),
        label="Round",
        pool_type="round",
        config={"num_episodes": 1, "min_episodes_per_entrant": 8},
    )
    entries = [
        PolicyPoolEntry(pool_id=pool.id, policy_version_id=policy_version_id, seed_order=index)
        for index, policy_version_id in enumerate(policy_version_ids)
    ]

    schedule = AmongThemCommissioner().schedule_episodes(pool=pool, entries=entries, num_agents=8, variant_id="default")

    assert len(schedule.episodes) == 16
    assert schedule.episodes[0].policy_version_ids == [policy_version_ids[i] for i in (0, 1, 2, 3, 4, 5, 6, 7)]
    assert schedule.episodes[1].policy_version_ids == [policy_version_ids[i] for i in (1, 2, 3, 4, 5, 6, 7, 8)]
    assert schedule.episodes[-1].policy_version_ids == [policy_version_ids[i] for i in (15, 0, 1, 2, 3, 4, 5, 6)]


def test_cogs_vs_clips_schedule_uses_slot_balanced_rotation() -> None:
    policy_version_ids = [uuid4() for _ in range(16)]
    pool = PolicyPool(
        id=uuid4(),
        label="Slot-balanced round",
        pool_type="round",
        config={"num_episodes": 1, "min_episodes_per_entrant": 8},
    )
    entries = [
        PolicyPoolEntry(pool_id=pool.id, policy_version_id=policy_version_id, seed_order=index)
        for index, policy_version_id in enumerate(policy_version_ids)
    ]

    schedule = CogsVsClipsCommissioner().schedule_episodes(
        pool=pool,
        entries=entries,
        num_agents=8,
        variant_id="default",
    )

    assert len(schedule.episodes) == 16
    assert schedule.episodes[0].policy_version_ids == [policy_version_ids[i] for i in (0, 1, 2, 3, 4, 5, 6, 7)]
    assert schedule.episodes[1].policy_version_ids == [policy_version_ids[i] for i in (1, 2, 3, 4, 5, 6, 7, 8)]
    assert schedule.episodes[-1].policy_version_ids == [policy_version_ids[i] for i in (15, 0, 1, 2, 3, 4, 5, 6)]


def test_self_play_pool_fills_each_episode_with_one_entrant() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    pool = PolicyPool(
        id=uuid4(),
        label="Round",
        pool_type="round",
        config={"num_episodes": 1, "min_episodes_per_entrant": 2, "self_play": True},
    )
    entries = [
        PolicyPoolEntry(pool_id=pool.id, policy_version_id=policy_version_id, seed_order=index)
        for index, policy_version_id in enumerate(policy_version_ids)
    ]

    schedule = AmongThemCommissioner().schedule_episodes(pool=pool, entries=entries, num_agents=3, variant_id="default")

    assert [episode.request_id for episode in schedule.episodes] == ["0", "1", "2", "3"]
    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0], policy_version_ids[0], policy_version_ids[0]],
        [policy_version_ids[0], policy_version_ids[0], policy_version_ids[0]],
        [policy_version_ids[1], policy_version_ids[1], policy_version_ids[1]],
        [policy_version_ids[1], policy_version_ids[1], policy_version_ids[1]],
    ]


def test_among_them_qualifier_schedule_does_not_expose_self_play_stage() -> None:
    qualifier_id = uuid4()
    response = schedule_rounds_for_request(
        AmongThemCommissioner(),
        ScheduleRoundsRequest(
            league=LeagueInfo(
                id=uuid4(),
                commissioner_config={
                    "minimum_champions": 4,
                    "qualifiers_division_name": "Qualifiers",
                    "qualifiers_minimum_champions": 1,
                },
            ),
            divisions=[DivisionInfo(id=qualifier_id, name="Qualifiers", level=-1, type="staging")],
            active_memberships=[
                MembershipInfo(
                    id=uuid4(),
                    division_id=qualifier_id,
                    policy_version_id=uuid4(),
                    is_champion=False,
                )
            ],
            recent_rounds=[],
        ),
    )

    assert len(response.rounds) == 1
    assert response.rounds[0].division_id == qualifier_id
    assert response.rounds[0].round_config.stages is not None
    assert "self_play" not in response.rounds[0].round_config.stages[0].model_dump()


def test_among_them_qualifier_round_start_restores_private_self_play() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=3,
        commissioner_config={
            "minimum_champions": 3,
            "qualifiers_division_name": "Qualifiers",
            "qualifiers_minimum_champions": 1,
        },
        division_name="Qualifiers",
        division_type="staging",
        state={
            "round_config": {
                "stages": [
                    {
                        "label": "Round",
                        "num_episodes": 2,
                        "min_episodes_per_entrant": 2,
                    }
                ]
            }
        },
    )

    schedule = schedule_episodes_for_round_start(AmongThemCommissioner(), round_start)

    assert [episode.policy_version_ids for episode in schedule.episodes] == [
        [policy_version_ids[0], policy_version_ids[0], policy_version_ids[0]],
        [policy_version_ids[0], policy_version_ids[0], policy_version_ids[0]],
        [policy_version_ids[1], policy_version_ids[1], policy_version_ids[1]],
        [policy_version_ids[1], policy_version_ids[1], policy_version_ids[1]],
    ]


def test_among_them_scoring_metadata_and_dirt_wood_changes() -> None:
    dirt_id = uuid4()
    wood_id = uuid4()
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
        division_name="Dirt",
        division_id=dirt_id,
        extra_divisions=[DivisionInfo(id=wood_id, name="Wood", level=1)],
        commissioner_config={"num_episodes": 1},
    )

    complete = complete_round_for_round_start(
        AmongThemCommissioner(),
        round_start,
        [
            ProtocolEpisodeResult(
                request_id="0",
                scores=[
                    EpisodeScore(policy_version_id=policy_version_ids[0], score=50.0),
                    EpisodeScore(policy_version_id=policy_version_ids[1], score=0.0),
                ],
            )
        ],
    )

    rankings = complete.results[0].rankings
    assert rankings[0].result_metadata == {
        "seed_order": 0,
        "score_kind": AMONG_THEM_SCORE_KIND,
        "version": AMONG_THEM_RESULT_METADATA_VERSION,
    }
    assert len(complete.graduation_changes) == 1
    assert complete.graduation_changes[0].to_division_id == wood_id
    assert complete.graduation_changes[0].reason == "average score > 0: promoted to Wood"


def test_among_them_relegates_from_wood_to_dirt_when_average_score_is_zero() -> None:
    dirt_id = uuid4()
    wood_id = uuid4()
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
        division_name="Wood",
        division_id=wood_id,
        extra_divisions=[DivisionInfo(id=dirt_id, name="Dirt", level=0)],
        commissioner_config={"num_episodes": 1},
    )

    complete = complete_round_for_round_start(
        AmongThemCommissioner(),
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

    assert len(complete.graduation_changes) == 1
    assert complete.graduation_changes[0].to_division_id == dirt_id
    assert complete.graduation_changes[0].reason == "average score <= 0: relegated to Dirt"


def test_round_start_adapter_uses_extracted_commissioner_api() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    round_start = _round_start(
        policy_version_ids=policy_version_ids,
        num_agents=2,
        commissioner_config={"num_episodes": 1},
    )

    schedule = schedule_episodes_for_round_start(BaselineCommissioner(), round_start)

    assert schedule.episodes[0].policy_version_ids == policy_version_ids


class HookResponseCommissioner(BaselineCommissioner):
    def on_round_completed(self, ctx: OnRoundCompletedContext) -> OnRoundCompletedResult:
        membership = ctx.division_memberships[0]
        return OnRoundCompletedResult(
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
                    division_id=division_id,
                    policy_version_id=policy_version_id,
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
                    division_id=division_id,
                    policy_version_id=policy_version_id,
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
                    division_id=division_id,
                    policy_version_id=policy_version_id,
                )
            ],
            recent_results=[],
        ),
    )
    assert completed_response.to_json()["type"] == "round_completed_response"
    assert completed_response.follow_up_rounds[0].division_id == division_id
    assert completed_response.membership_changes == [
        ProtocolMembershipChange(
            membership_id=membership_id,
            from_division_id=division_id,
            to_division_id=division_id,
            reason="mapped",
        )
    ]
