"""Per-policy OpenSkill (Plackett-Luce) MMR ranking for a division leaderboard.

Each completed round is treated as one free-for-all match: the participating policy versions are
fed to the Bayesian rater ordered by their finishing rank (lower is better; ties allowed), so a
policy's rating reflects the strength of the opponents it actually beat, not a raw score. Rounds
are replayed oldest-first so ratings evolve causally. The displayed MMR is the conservative ordinal
mu - 3*sigma; a brand-new policy from a player who already has a rated policy starts at that
player's best established mu (with the default wide sigma) so its first ranks aren't insane.

Mirrors the platform-side ranker in app_backend `v2/commissioners.rank_division_by_mmr`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from openskill.models import PlackettLuce
from pydantic import BaseModel, Field

from commissioners.common.models import (
    DivisionLeaderboardContext,
    DivisionLeaderboardSnapshot,
    LeaderboardRoundResultSnapshot,
)

# A policy must complete at least this many rated games before it earns a numeric rank. Until then
# it is rated (its games still shift others' ratings) but sorts after ranked policies, so a single
# lucky win can't rocket a brand-new policy to the top.
MMR_PLACEMENT_MIN_GAMES = 5


class _MmrPolicy:
    """Mutable per-policy rating state accumulated while replaying a division's rounds."""

    def __init__(self, result: LeaderboardRoundResultSnapshot, rating: Any) -> None:
        self.policy_version_id = result.policy_version_id
        self.player_id = result.player_id
        self.player_name = result.player_name
        self.rating = rating
        self.wins = 0
        self.losses = 0
        self.games_played = 0


def rank_division_by_mmr(
    ctx: DivisionLeaderboardContext,
    *,
    placement_min_games: int = MMR_PLACEMENT_MIN_GAMES,
) -> list[DivisionLeaderboardSnapshot]:
    if not ctx.round_results or not ctx.completed_rounds:
        return []

    # Keep each policy's best result per round (highest score, ties broken by lower rank), so a round
    # contributes one finishing position per policy even if it posted multiple episodes.
    best_result: dict[tuple[UUID, UUID], LeaderboardRoundResultSnapshot] = {}
    for result in ctx.round_results:
        key = (result.policy_version_id, result.round_id)
        current = best_result.get(key)
        if current is None or (result.score, -result.rank) > (current.score, -current.rank):
            best_result[key] = result

    results_by_round: dict[UUID, list[LeaderboardRoundResultSnapshot]] = defaultdict(list)
    for result in best_result.values():
        results_by_round[result.round_id].append(result)

    model = PlackettLuce()
    player_prior_mu: dict[Any, float] = {}
    policies: dict[UUID, _MmrPolicy] = {}

    # ctx.completed_rounds is newest-first; replay oldest-first so ratings evolve causally.
    for round_row in reversed(ctx.completed_rounds):
        round_results = results_by_round.get(round_row.id)
        if not round_results or len(round_results) < 2:
            continue  # a one-policy round is not a match — nothing to learn from it
        for result in round_results:
            if result.policy_version_id not in policies:
                prior_mu = player_prior_mu.get(result.player_id)
                rating = model.rating(mu=prior_mu) if prior_mu is not None else model.rating()
                policies[result.policy_version_id] = _MmrPolicy(result, rating)

        ordered = sorted(round_results, key=lambda r: r.rank)
        rated = model.rate(
            [[policies[r.policy_version_id].rating] for r in ordered],
            ranks=[r.rank for r in ordered],
        )
        for result, team in zip(ordered, rated, strict=True):
            policy = policies[result.policy_version_id]
            policy.rating = team[0]
            policy.games_played += 1
            if result.rank == 1:
                policy.wins += 1
            else:
                policy.losses += 1
            if policy.games_played >= placement_min_games and policy.player_id is not None:
                best = player_prior_mu.get(policy.player_id)
                if best is None or policy.rating.mu > best:
                    player_prior_mu[policy.player_id] = policy.rating.mu

    # Out-of-placement policies first (by descending MMR), then in-placement, also by MMR.
    ordered_policies = sorted(
        policies.values(),
        key=lambda p: (
            p.games_played < placement_min_games,
            -p.rating.ordinal(),
            str(p.policy_version_id),
        ),
    )
    return [
        DivisionLeaderboardSnapshot(
            player_id=policy.player_id,
            player_name=policy.player_name,
            rank=rank,
            score=policy.rating.ordinal(),
            rounds_played=policy.games_played,
            policy_version_ids={policy.policy_version_id},
        )
        for rank, policy in enumerate(ordered_policies, start=1)
        if policy.player_id is not None
    ]


# ---------------------------------------------------------------------------
# Incremental MMR
#
# The platform only hands the commissioner a small recent-results window at round start, far too
# little to replay the whole division each round. Instead the commissioner carries its compact
# rating state forward across rounds (persisted by the platform as commissioner_state) and advances
# it with only the just-completed round -- never recomputing from scratch. The math is identical to
# the replay ranker above: each round is one Plackett-Luce update applied in chronological order.
# ---------------------------------------------------------------------------


class MmrRating(BaseModel):
    """Serializable per-policy rating carried across rounds in commissioner_state."""

    mu: float
    sigma: float
    games_played: int = 0
    wins: int = 0
    player_id: str | None = None
    player_name: str | None = None


class MmrState(BaseModel):
    """The full division rating state the commissioner persists and advances each round."""

    policies: dict[str, MmrRating] = Field(default_factory=dict)
    player_prior_mu: dict[str, float] = Field(default_factory=dict)


class MmrRoundFinish(BaseModel):
    """One policy's finishing position in a single completed round."""

    policy_version_id: UUID
    player_id: str | None = None
    player_name: str | None = None
    rank: int


def _ordinal(model: PlackettLuce, rating: MmrRating) -> float:
    return model.rating(mu=rating.mu, sigma=rating.sigma).ordinal()


def _snapshots_from_state(
    state: MmrState,
    model: PlackettLuce,
    placement_min_games: int,
) -> list[DivisionLeaderboardSnapshot]:
    # Out-of-placement policies first (by descending MMR), then in-placement, also by MMR.
    ordered = sorted(
        state.policies.items(),
        key=lambda item: (
            item[1].games_played < placement_min_games,
            -_ordinal(model, item[1]),
            item[0],
        ),
    )
    return [
        DivisionLeaderboardSnapshot(
            player_id=rating.player_id,
            player_name=rating.player_name,
            rank=rank,
            score=_ordinal(model, rating),
            rounds_played=rating.games_played,
            policy_version_ids={UUID(policy_version_id)},
        )
        for rank, (policy_version_id, rating) in enumerate(ordered, start=1)
        if rating.player_id is not None
    ]


def advance_mmr_state(
    prior: MmrState,
    finishes: list[MmrRoundFinish],
    *,
    active_policy_version_ids: set[str] | None = None,
    placement_min_games: int = MMR_PLACEMENT_MIN_GAMES,
) -> tuple[MmrState, list[DivisionLeaderboardSnapshot]]:
    """Advance the carried rating state by one completed round and return the new standings.

    ``finishes`` is the round's final per-policy ranking (one entry per policy). A round with fewer
    than two policies is not a match and leaves ratings untouched (but still re-emits standings, so
    a freshly-deployed division surfaces its existing rated policies immediately).

    ``active_policy_version_ids`` (when given) is the set of policies still competing in the division:
    any carried policy no longer among them -- a demoted, disqualified, or relegated champion -- is
    dropped from the state and the standings so stale policies don't occupy ranks forever. Other
    policies keep the rating they earned beating it.
    """
    model = PlackettLuce()
    state = prior.model_copy(deep=True)

    # One finish per policy; if a policy somehow appears twice, keep its best (lowest-rank) finish.
    best_finish: dict[str, MmrRoundFinish] = {}
    for finish in finishes:
        policy_version_id = str(finish.policy_version_id)
        current = best_finish.get(policy_version_id)
        if current is None or finish.rank < current.rank:
            best_finish[policy_version_id] = finish
    round_finishes = list(best_finish.values())

    if len(round_finishes) >= 2:
        for finish in round_finishes:
            policy_version_id = str(finish.policy_version_id)
            existing = state.policies.get(policy_version_id)
            if existing is None:
                prior_mu = state.player_prior_mu.get(finish.player_id) if finish.player_id else None
                rating = model.rating(mu=prior_mu) if prior_mu is not None else model.rating()
                state.policies[policy_version_id] = MmrRating(
                    mu=rating.mu,
                    sigma=rating.sigma,
                    player_id=finish.player_id,
                    player_name=finish.player_name,
                )
            elif finish.player_name and not existing.player_name:
                existing.player_name = finish.player_name

        ordered = sorted(round_finishes, key=lambda finish: finish.rank)
        teams = [
            [model.rating(mu=(rating := state.policies[str(finish.policy_version_id)]).mu, sigma=rating.sigma)]
            for finish in ordered
        ]
        rated = model.rate(teams, ranks=[finish.rank for finish in ordered])
        for finish, team in zip(ordered, rated, strict=True):
            rating = state.policies[str(finish.policy_version_id)]
            rating.mu = team[0].mu
            rating.sigma = team[0].sigma
            rating.games_played += 1
            if finish.rank == 1:
                rating.wins += 1
            if rating.games_played >= placement_min_games and rating.player_id is not None:
                best = state.player_prior_mu.get(rating.player_id)
                if best is None or rating.mu > best:
                    state.player_prior_mu[rating.player_id] = rating.mu

    if active_policy_version_ids is not None:
        state.policies = {
            policy_version_id: rating
            for policy_version_id, rating in state.policies.items()
            if policy_version_id in active_policy_version_ids
        }

    return state, _snapshots_from_state(state, model, placement_min_games)
