from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from commissioners.common.protocol import (
    DivisionInfo,
    EpisodeResult as ProtocolEpisodeResult,
    EpisodeScore,
    LeagueInfo,
    MembershipInfo,
    RoundStart,
    VariantInfo,
)
from commissioners.common.commissioners import (
    AMONG_THEM_RESULT_METADATA_VERSION,
    AMONG_THEM_SCORE_KIND,
    AmongThemCommissioner,
    BaselineCommissioner,
    EpisodeResult,
    PolicyPool,
    PolicyPoolEntry,
    Round,
    RoundPolicyScore,
    complete_round_for_round_start,
    schedule_episodes_for_round_start,
)


def _round_start(
    *,
    policy_version_ids: list[UUID],
    num_agents: int,
    commissioner_config: dict | None = None,
    division_name: str = "Bronze",
    division_id: UUID | None = None,
    extra_divisions: list[DivisionInfo] | None = None,
) -> RoundStart:
    active_division_id = division_id or uuid4()
    divisions = [
        DivisionInfo(id=active_division_id, name=division_name, level=0),
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
