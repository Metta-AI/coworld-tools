"""Commissioner-owned MMR division standings.

The commissioner advances per-policy OpenSkill (Plackett-Luce) MMR incrementally from rating state
carried across rounds in ``commissioner_state`` -- never recomputing from scratch -- and publishes the
ranked standings in ``RoundComplete.leaderboards`` for the platform to store and display verbatim.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from commissioners.common.models import (
    DivisionLeaderboardContext,
    DivisionSnapshot,
    LeaderboardRoundResultSnapshot,
    LeagueSnapshot,
    RoundSnapshot,
)
from commissioners.common.protocol import (
    DivisionInfo,
    EpisodeResult,
    EpisodeScore,
    LeagueInfo,
    MembershipInfo,
    RecentResult,
    RoundStart,
    VariantInfo,
)
from commissioners.common.commissioners import RulesetStrategyCommissioner
from commissioners.common.ruleset_strategy.mmr import (
    MmrRoundFinish,
    MmrState,
    advance_mmr_state,
    rank_division_by_mmr,
)

_NAMES = {1: "alice", 2: "bob", 3: "carol", 4: "dave"}
_POLICY = {n: uuid.UUID(int=n) for n in range(1, 5)}
_PLAYER = {n: f"ply_{uuid.UUID(int=500 + n)}" for n in range(1, 5)}
# alice consistently beats dave; the middle two swap around.
_ROUNDS = [[1, 2, 3, 4], [1, 3, 2, 4], [1, 2, 4, 3], [2, 1, 3, 4], [1, 2, 3, 4], [1, 3, 2, 4]]


def _finishes(order: list[int]) -> list[MmrRoundFinish]:
    return [
        MmrRoundFinish(
            policy_version_id=_POLICY[n],
            player_id=_PLAYER[n],
            player_name=_NAMES[n].title(),
            rank=i + 1,
        )
        for i, n in enumerate(order)
    ]


def test_incremental_advance_matches_replay_to_the_float() -> None:
    """Advancing one round at a time from carried state equals replaying all rounds from scratch."""
    state = MmrState()
    snapshots: list = []
    for order in _ROUNDS:
        state, snapshots = advance_mmr_state(state, _finishes(order))
        # round-trip the state through JSON exactly as the platform persists commissioner_state.
        state = MmrState.model_validate(json.loads(json.dumps(state.model_dump(mode="json"))))

    division_id = uuid.UUID(int=999)
    round_results: list[LeaderboardRoundResultSnapshot] = []
    rounds: list[RoundSnapshot] = []
    for ridx, order in enumerate(_ROUNDS):
        round_id = uuid.UUID(int=100 + ridx)
        rounds.append(
            RoundSnapshot(
                id=round_id,
                public_id=str(round_id),
                division_id=division_id,
                round_number=ridx + 1,
                status="completed",
                round_config={},
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        for i, n in enumerate(order):
            round_results.append(
                LeaderboardRoundResultSnapshot(
                    round_id=round_id,
                    policy_version_id=_POLICY[n],
                    rank=i + 1,
                    score=float(len(order) - i),
                    player_id=_PLAYER[n],
                    player_name=_NAMES[n].title(),
                    result_metadata={},
                )
            )
    replay = rank_division_by_mmr(
        DivisionLeaderboardContext(
            league=LeagueSnapshot(id=uuid.UUID(int=1), commissioner_key="x", commissioner_config={}),
            division=DivisionSnapshot(id=division_id, name="D", level=1, league_id=uuid.UUID(int=1)),
            completed_rounds=list(reversed(rounds)),  # replay expects newest-first
            recent_rounds=[],
            round_results=round_results,
        )
    )

    incremental_scores = {s.player_name: round(s.score, 6) for s in snapshots}
    replay_scores = {s.player_name: round(s.score, 6) for s in replay}
    assert incremental_scores == replay_scores


def test_advance_ranks_consistent_winner_first_and_loser_last() -> None:
    state = MmrState()
    snapshots: list = []
    for order in _ROUNDS:
        state, snapshots = advance_mmr_state(state, _finishes(order))
    order = [s.player_name for s in snapshots]
    assert order[0] == "Alice"
    assert order[-1] == "Dave"
    assert snapshots[0].score > snapshots[-1].score


def test_one_policy_round_is_not_a_match() -> None:
    state, snapshots = advance_mmr_state(MmrState(), _finishes([1]))
    # A lone entrant is not a match: nothing to learn, no standings emitted.
    assert snapshots == []
    assert state.policies == {}


_CONFIG_DIR = Path(__file__).parents[1] / "commissioners" / "ruleset_strategy_commissioner" / "configs"


def _competition_commissioner() -> RulesetStrategyCommissioner:
    # Pass the config explicitly: the image config loader is lru_cached, so relying on the
    # RULESET_STRATEGY_CONFIG_NAME env var is order-dependent under the shared test session.
    return RulesetStrategyCommissioner(yaml.safe_load((_CONFIG_DIR / "agricogla.yaml").read_text()))


def _competition_round_start(round_no: int, state, recent: list[RecentResult], comp: uuid.UUID) -> RoundStart:
    league_id = uuid.UUID(int=1)
    memberships = [
        MembershipInfo(
            id=uuid.UUID(int=50 + n),
            league_id=league_id,
            division_id=comp,
            policy_version_id=_POLICY[n],
            player_id=_PLAYER[n],
            status="competing",
            substatus="active",
            is_champion=True,
        )
        for n in range(1, 5)
    ]
    return RoundStart(
        round_id=uuid.UUID(int=1000 + round_no),
        round_number=round_no,
        league=LeagueInfo(id=league_id, commissioner_key="config_driven", commissioner_config={}),
        divisions=[DivisionInfo(id=comp, name="Competition", level=1, type="competition")],
        memberships=memberships,
        recent_results=recent,
        variants=[VariantInfo(id="default", name="default", game_config={"num_agents": 4}, num_agents=4)],
        state=state,
    )


def _episodes(order: list[int]) -> list[EpisodeResult]:
    # round_score=win: three episodes in the same finishing order give a clear round winner.
    return [
        EpisodeResult(
            request_id=f"e{k}",
            scores=[
                EpisodeScore(policy_version_id=_POLICY[n], player_id=_PLAYER[n], score=float(len(order) - i))
                for i, n in enumerate(order)
            ],
        )
        for k in range(3)
    ]


def test_commissioner_publishes_mmr_standings_and_carries_per_division_state() -> None:
    comm = _competition_commissioner()
    assert comm._config().scoring.leaderboard.type == "mmr"
    comp = uuid.UUID(int=10)

    state = None
    recent: list[RecentResult] = []
    complete = None
    for ridx, order in enumerate(_ROUNDS, start=1):
        rs = _competition_round_start(ridx, state, recent, comp)
        complete = comm.complete_round_for_round_start(rs, _episodes(order))
        state = json.loads(json.dumps(complete.state))  # platform persists commissioner_state as JSON
        recent = [
            RecentResult(
                round_id=rs.round_id,
                division_id=comp,
                round_number=ridx,
                policy_version_id=_POLICY[n],
                rank=i + 1,
                score=float(len(order) - i),
                player_id=_PLAYER[n],
                player_name=_NAMES[n].title(),
            )
            for i, n in enumerate(order)
        ]

    assert complete is not None
    assert len(complete.leaderboards) == 1
    view = complete.leaderboards[0].views[0]
    rows = view.rows
    assert rows[0].subject_name == "Alice"
    assert rows[-1].subject_name == "Dave"
    assert float(rows[0].values["score"]) > float(rows[-1].values["score"])
    # rating state is carried per division under the division id.
    assert str(comp) in complete.state["mmr"]
    assert len(complete.state["mmr"][str(comp)]["policies"]) == 4


def test_staging_round_publishes_no_standings_and_preserves_competition_state() -> None:
    comm = _competition_commissioner()
    comp = uuid.UUID(int=10)

    # Seed one competition round so there is competition state to protect.
    rs = _competition_round_start(1, None, [], comp)
    seeded = comm.complete_round_for_round_start(rs, _episodes([1, 2, 3, 4]))
    state = json.loads(json.dumps(seeded.state))
    competition_before = json.dumps(state["mmr"][str(comp)], sort_keys=True)

    # A staging (qualifier) round must publish nothing and leave the competition pool untouched.
    qual = uuid.UUID(int=20)
    qual_player = f"ply_{uuid.UUID(int=88)}"
    qstate = dict(state)
    qstate["round_config"] = {"current_division_id": str(qual)}
    qrs = RoundStart(
        round_id=uuid.UUID(int=2000),
        round_number=99,
        league=LeagueInfo(id=uuid.UUID(int=1), commissioner_key="config_driven", commissioner_config={}),
        divisions=[
            DivisionInfo(id=comp, name="Competition", level=1, type="competition"),
            DivisionInfo(id=qual, name="Qualifiers", level=-99, type="staging"),
        ],
        memberships=[
            MembershipInfo(
                id=uuid.UUID(int=77),
                league_id=uuid.UUID(int=1),
                division_id=qual,
                policy_version_id=uuid.UUID(int=88),
                player_id=qual_player,
                status="qualifying",
                substatus="active",
                is_champion=False,
            )
        ],
        recent_results=[],
        variants=[VariantInfo(id="default", name="default", game_config={"num_agents": 4}, num_agents=4)],
        state=qstate,
    )
    qcomplete = comm.complete_round_for_round_start(
        qrs,
        [EpisodeResult(request_id="q0", scores=[EpisodeScore(policy_version_id=uuid.UUID(int=88), player_id=qual_player, score=1.0)])],
    )
    assert qcomplete.leaderboards == []
    competition_after = json.dumps(qcomplete.state["mmr"][str(comp)], sort_keys=True)
    assert competition_after == competition_before
