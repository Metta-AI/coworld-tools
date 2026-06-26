"""Per-policy OpenSkill MMR ranking, including the inherited-champion placement rule."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from commissioners.common.models import (
    DivisionLeaderboardContext,
    DivisionSnapshot,
    LeaderboardRoundResultSnapshot,
    LeagueSnapshot,
    RoundSnapshot,
)
from commissioners.common.ruleset_strategy.mmr import rank_division_by_mmr

_DIV = uuid.UUID(int=999)


def _player(n: int) -> str:
    return f"ply_{uuid.UUID(int=500 + n)}"


def _context(rounds_orders: list[tuple[int, list[tuple[uuid.UUID, str, str]]]]) -> DivisionLeaderboardContext:
    rounds: list[RoundSnapshot] = []
    results: list[LeaderboardRoundResultSnapshot] = []
    for round_number, order in rounds_orders:
        round_id = uuid.UUID(int=100 + round_number)
        rounds.append(
            RoundSnapshot(
                id=round_id,
                public_id=str(round_number),
                division_id=_DIV,
                round_number=round_number,
                status="completed",
                round_config={},
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        for place, (policy, player_id, name) in enumerate(order):
            results.append(
                LeaderboardRoundResultSnapshot(
                    round_id=round_id,
                    policy_version_id=policy,
                    rank=place + 1,
                    score=float(len(order) - place),
                    player_id=player_id,
                    player_name=name,
                    result_metadata={},
                )
            )
    return DivisionLeaderboardContext(
        league=LeagueSnapshot(id=uuid.UUID(int=1), commissioner_key="x", commissioner_config={}),
        division=DivisionSnapshot(id=_DIV, name="D", level=1, league_id=uuid.UUID(int=1)),
        completed_rounds=list(reversed(rounds)),  # rank_division_by_mmr expects newest-first
        recent_rounds=[],
        round_results=results,
    )


def test_inherited_new_champion_skips_placement_but_new_player_does_not() -> None:
    a_old, b, c, d = (uuid.UUID(int=i) for i in (1, 2, 3, 4))
    a_new, eve = uuid.UUID(int=10), uuid.UUID(int=20)
    alice, eve_player = _player(1), _player(9)
    entry = {
        a_old: (a_old, alice, "Alice"),
        b: (b, _player(2), "Bob"),
        c: (c, _player(3), "Carol"),
        d: (d, _player(4), "Dave"),
        a_new: (a_new, alice, "Alice"),  # Alice's newly-uploaded champion (same player as a_old)
        eve: (eve, eve_player, "Eve"),  # a brand-new player's first policy
    }
    orders = [(r, [entry[a_old], entry[b], entry[c], entry[d]]) for r in range(1, 7)]
    orders += [(r, [entry[a_new], entry[b], entry[c], entry[d], entry[eve]]) for r in range(7, 9)]

    board = rank_division_by_mmr(_context(orders))
    by_policy = {tuple(s.policy_version_ids)[0]: s for s in board}

    alice_new = by_policy[a_new]
    eve_row = by_policy[eve]
    # both are young (2 rounds), but Alice's new champ inherited an established rating
    assert alice_new.rounds_played < 5 and eve_row.rounds_played < 5
    # Alice's inherited new champion is placed and ranked by MMR near the top
    assert alice_new.rank <= 3
    # the brand-new player's first policy is still held in placement at the bottom
    assert eve_row.rank == len(board)
    assert alice_new.rank < eve_row.rank


def test_one_policy_rounds_are_not_matches() -> None:
    a = uuid.UUID(int=1)
    board = rank_division_by_mmr(_context([(1, [(a, _player(1), "Alice")])]))
    assert board == []
