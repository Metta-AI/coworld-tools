from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from commissioners.common.protocol import (
    EpisodeRequest as CommissionerEpisodeRequest,
)
from commissioners.common.protocol import (
    RoundComplete as CommissionerRoundComplete,
)
from commissioners.common.protocol import (
    ScheduleEpisodes as CommissionerScheduleEpisodes,
)
from commissioners.common.protocol import (
    DivisionRanking as CommissionerDivisionRanking,
)
from commissioners.common.protocol import (
    RankingEntry as CommissionerRankingEntry,
)

# Re-export models for backwards compatibility
from commissioners.common.models import (
    PlayerId,
    RoundId,
    SubmissionId,
    DIVISION_TYPE_COMPETITION,
    DIVISION_TYPE_STAGING,
    RoundExecutionBackend,
    DivisionCommissionerDescriptionPublic,
    LeaderboardRecentRoundPublic,
    League,
    Division,
    LeaguePolicyMembership,
    PolicyPool,
    PolicyPoolEntry,
    Round,
    RoundResult,
    PLACEMENT_DRY_RUN_POOL_TYPE,
    DIVISION_LEADERBOARD_SCORE_EWMA_HALFLIFE_HOURS,
    DIVISION_LEADERBOARD_SCORE_EWMA_HALFLIFE,
    PoolPlan,
    PoolEntryPlan,
    RoundPolicyScore,
    EpisodeResult,
    MembershipChange,
    V2StageConfig,
    V2RoundConfig,
    PoolConfig,
    RoundSchedulingConfig,
    DEFAULT_STAGES,
    AMONG_THEM_DEFAULT_STAGE,
    AMONG_THEM_DIRT_STAGE,
    AMONG_THEM_QUALIFIER_STAGE,
    AmongThemSchedulingConfig,
    LeagueSnapshot,
    DivisionSnapshot,
    MembershipSnapshot,
    RoundSnapshot,
    RoundResultSnapshot,
    DivisionLeaderboardSnapshot,
    _LeaderboardAgg,
    LeaderboardRoundResultSnapshot,
    RoundSpec,
    ScheduleContext,
    DivisionLeaderboardContext,
    SubmissionPlacementContext,
    OnRoundCompletedContext,
    OnRoundCompletedResult,
    DivisionDescriptionContext,
)

# Re-export utils for backwards compatibility
from commissioners.common.utils import (
    select_division,
    select_qualifier_division,
    select_competition_entry_division,
    division_entrants,
    _count_text,
    _plural_word,
    _leaderboard_rules_description,
    AMONG_THEM_SCORING_MECHANICS,
    AMONG_THEM_RESULT_METADATA_VERSION,
    AMONG_THEM_SCORE_KIND,
    _duration_text,
    _join_text,
    _schedule_slot_description,
    _current_schedule_slot,
    _round_structure_description,
    _build_entry_indices,
    _entry_index_offset,
    _build_slot_balanced_entry_indices,
    _pool_episode_count,
    _score_lists_by_policy,
    _qualification_round_membership_changes,
)

# Re-export adapters for backwards compatibility
from commissioners.common.adapters import (
    schedule_episodes_for_round_start,
    complete_round_for_round_start,
    schedule_rounds_for_request,
    rank_division_for_request,
    describe_division_for_request,
    round_completed_for_request,
)


# ---------------------------------------------------------------------------
# Commissioner contract
# ---------------------------------------------------------------------------


class Commissioner(ABC):
    """Protocol-shaped commissioner contract.

    Each round runs a single pool. The commissioner observes a round through three hooks:

    - ``schedule_rounds`` proposes new rounds on a cadence.
    - ``schedule_episodes`` lays out the episodes that compose a round's pool.
    - ``complete_round`` aggregates the pool's episode results into rankings.

    The ``schedule_episodes`` and ``complete_round`` signatures return the shared
    ``coworld.commissioner.protocol`` shape so the same logic can move behind a
    WebSocket-driven container runtime later without changing observable behavior.
    """

    def schedule_rounds(self, ctx: ScheduleContext) -> list[RoundSpec]:
        return []

    @abstractmethod
    def rank_division(self, ctx: DivisionLeaderboardContext) -> list[DivisionLeaderboardSnapshot]: ...

    @abstractmethod
    def describe_division(self, ctx: DivisionDescriptionContext) -> DivisionCommissionerDescriptionPublic: ...

    def on_round_completed(self, ctx: OnRoundCompletedContext) -> OnRoundCompletedResult:
        return OnRoundCompletedResult()

    @abstractmethod
    def schedule_episodes(
        self,
        *,
        pool: PolicyPool,
        entries: list[PolicyPoolEntry],
        num_agents: int,
        variant_id: str,
    ) -> CommissionerScheduleEpisodes: ...

    @abstractmethod
    def complete_round(
        self,
        *,
        round_row: Round,
        pool: PolicyPool,
        entries: list[PolicyPoolEntry],
        episode_results: list[EpisodeResult],
    ) -> CommissionerRoundComplete: ...


# ---------------------------------------------------------------------------
# Concrete commissioners
# ---------------------------------------------------------------------------


def _phase_summary(pool: PolicyPool, num_entries: int) -> dict[str, object]:
    config = PoolConfig.model_validate(pool.config)
    summary = f"{num_entries} entrants"
    if config.min_episodes_per_entrant:
        summary += f", at least {config.min_episodes_per_entrant} appearances each"
    return {
        "label": pool.label,
        "summary": summary,
        "pool_id": str(pool.id),
        "display": "leaderboard",
    }


class BaselineCommissioner(Commissioner):
    """Cadence-scheduled commissioner with mean-score ranking and no graduation."""

    def _scheduling_config(self, commissioner_config: dict[str, Any] | None) -> RoundSchedulingConfig:
        return RoundSchedulingConfig.model_validate(commissioner_config or {})

    def rank_division(self, ctx: DivisionLeaderboardContext) -> list[DivisionLeaderboardSnapshot]:
        if not ctx.completed_rounds or not ctx.round_results:
            return []

        completed_rounds_by_id = {round_row.id: round_row for round_row in ctx.completed_rounds}
        latest_completed_at = ctx.completed_rounds[0].completed_at
        assert latest_completed_at is not None, f"Completed round {ctx.completed_rounds[0].id} is missing completed_at"

        player_rounds: dict[tuple[PlayerId, UUID], LeaderboardRoundResultSnapshot] = {}
        for result in ctx.round_results:
            key = (result.player_id, result.round_id)
            current = player_rounds.get(key)
            if current is None or (result.score, -result.rank) > (current.score, -current.rank):
                player_rounds[key] = result

        rounds_played_by_player: dict[PlayerId, int] = {}
        aggs: dict[PlayerId, _LeaderboardAgg] = {}
        for player_round in player_rounds.values():
            round_row = completed_rounds_by_id.get(player_round.round_id)
            if round_row is None:
                continue
            rounds_played_by_player[player_round.player_id] = rounds_played_by_player.get(player_round.player_id, 0) + 1
            if player_round.player_id not in aggs:
                aggs[player_round.player_id] = _LeaderboardAgg(
                    player_id=player_round.player_id,
                    player_name=player_round.player_name,
                )
            assert round_row.completed_at is not None, f"Completed round {round_row.id} is missing completed_at"
            weight = 0.5 ** (
                (latest_completed_at - round_row.completed_at).total_seconds()
                / DIVISION_LEADERBOARD_SCORE_EWMA_HALFLIFE.total_seconds()
            )
            aggs[player_round.player_id].policy_version_ids.add(player_round.policy_version_id)
            aggs[player_round.player_id].weighted_score_sum += player_round.score * weight
            aggs[player_round.player_id].weight_sum += weight

        ranks_by_round_and_player = {
            (player_round.round_id, player_round.player_id): player_round.rank
            for player_round in player_rounds.values()
        }
        scores_by_round_and_player = {
            (player_round.round_id, player_round.player_id): player_round.score
            for player_round in player_rounds.values()
        }

        def build_recent_rounds(player_id: PlayerId) -> list[LeaderboardRecentRoundPublic] | None:
            if not ctx.recent_rounds:
                return None
            return [
                LeaderboardRecentRoundPublic(
                    id=round_row.public_id,
                    round_number=round_row.round_number,
                    status=round_row.status,
                    rank=ranks_by_round_and_player.get((round_row.id, player_id)),
                    score=scores_by_round_and_player.get((round_row.id, player_id)),
                    started_at=round_row.started_at,
                    completed_at=round_row.completed_at,
                )
                for round_row in ctx.recent_rounds
            ]

        ranked_aggs = sorted(
            aggs.values(),
            key=lambda agg: (
                -agg.score(),
                agg.player_name or "",
                str(agg.player_id),
            ),
        )
        return [
            DivisionLeaderboardSnapshot(
                player_id=agg.player_id,
                player_name=agg.player_name,
                rank=rank,
                score=agg.score(),
                rounds_played=rounds_played_by_player[agg.player_id],
                policy_version_ids=agg.policy_version_ids,
                recent_rounds=build_recent_rounds(agg.player_id),
            )
            for rank, agg in enumerate(ranked_aggs, start=1)
        ]

    def on_round_completed(self, ctx: OnRoundCompletedContext) -> OnRoundCompletedResult:
        return OnRoundCompletedResult(
            membership_changes=_qualification_round_membership_changes(
                ctx,
                qualifier_division=select_qualifier_division(ctx.commissioner_config, ctx.all_divisions),
                competition_entry_division=select_competition_entry_division(
                    ctx.commissioner_config, ctx.all_divisions
                ),
            )
        )

    def describe_division(self, ctx: DivisionDescriptionContext) -> DivisionCommissionerDescriptionPublic:
        config = self._scheduling_config(ctx.league.commissioner_config)
        active_round = next((r for r in ctx.recent_rounds if r.status in ("pending", "claimed", "running")), None)
        champion_count = sum(1 for m in ctx.active_memberships if m.is_champion)
        next_round = None
        if champion_count < config.minimum_champions:
            needed = config.minimum_champions - champion_count
            next_round = f"Add {needed} more champion {_plural_word(needed, 'entrant')} before scheduling can continue."
        elif active_round is not None:
            next_round = f"The next round waits for round #{active_round.round_number} to finish."

        return DivisionCommissionerDescriptionPublic(
            round_schedule=(
                f"Rounds start every {_duration_text(config.schedule_interval_minutes)}"
                f"{_schedule_slot_description(config)} if there are at least "
                f"{_count_text(config.minimum_champions)} champions in the division."
            ),
            next_round=next_round,
            round_structure=_round_structure_description(config.stages),
            leaderboard_rules=_leaderboard_rules_description(),
        )

    def schedule_rounds(self, ctx: ScheduleContext) -> list[RoundSpec]:
        config = self._scheduling_config(ctx.league.commissioner_config)
        qualifier_division = select_qualifier_division(ctx.league.commissioner_config, ctx.divisions)

        now = datetime.now(UTC)
        current_slot = _current_schedule_slot(now, config)
        specs: list[RoundSpec] = []
        for division in ctx.divisions:
            division_rounds = [r for r in ctx.recent_rounds if r.division_id == division.id]
            pending_or_running = [r for r in division_rounds if r.status in ("pending", "claimed", "running")]

            if pending_or_running:
                continue

            latest_round = max(division_rounds, key=lambda r: r.created_at, default=None)
            if latest_round is not None and latest_round.created_at >= current_slot:
                continue

            is_qualifier = qualifier_division is not None and division.id == qualifier_division.id
            entrants = division_entrants(ctx.active_memberships, division, is_qualifier=is_qualifier)
            min_champs = config.qualifiers_minimum_champions if is_qualifier else config.minimum_champions
            if len(entrants) < min_champs:
                continue

            specs.append(
                RoundSpec(
                    division_id=division.id,
                    round_config=V2RoundConfig(
                        stages=config.stages,
                    ),
                    execution_backend=config.effective_execution_backend(),
                    notes=f"auto-scheduled by {type(self).__name__}",
                )
            )

        return specs

    def schedule_episodes(
        self,
        *,
        pool: PolicyPool,
        entries: list[PolicyPoolEntry],
        num_agents: int,
        variant_id: str,
    ) -> CommissionerScheduleEpisodes:
        config = PoolConfig.model_validate(pool.config)
        num_episodes = _pool_episode_count(
            config=config,
            num_entries=len(entries),
            num_agents=num_agents,
        )
        episodes: list[CommissionerEpisodeRequest] = []
        for job_index in range(num_episodes):
            entry_indices = _build_entry_indices(
                num_entries=len(entries),
                num_agents=num_agents,
                offset=_entry_index_offset(
                    job_index=job_index,
                    num_entries=len(entries),
                    num_agents=num_agents,
                ),
            )
            episodes.append(
                CommissionerEpisodeRequest(
                    request_id=str(job_index),
                    variant_id=variant_id,
                    policy_version_ids=[entries[i].policy_version_id for i in entry_indices],
                    tags={"pool_id": str(pool.id)},
                )
            )
        return CommissionerScheduleEpisodes(episodes=episodes)

    def complete_round(
        self,
        *,
        round_row: Round,
        pool: PolicyPool,
        entries: list[PolicyPoolEntry],
        episode_results: list[EpisodeResult],
    ) -> CommissionerRoundComplete:
        score_lists = _score_lists_by_policy(episode_results)
        avg_score_by_policy = {
            entry.policy_version_id: (
                sum(score_lists.get(entry.policy_version_id, [])) / len(score_lists.get(entry.policy_version_id, []))
                if score_lists.get(entry.policy_version_id)
                else 0.0
            )
            for entry in entries
        }
        ranked_entries = sorted(
            entries,
            key=lambda entry: (
                -avg_score_by_policy[entry.policy_version_id],
                entry.seed_order,
                str(entry.policy_version_id),
            ),
        )
        rankings = [
            CommissionerRankingEntry(
                policy_version_id=entry.policy_version_id,
                player_id=str(entry.player_id) if entry.player_id is not None else None,
                rank=rank,
                score=avg_score_by_policy[entry.policy_version_id],
                result_metadata={"seed_order": entry.seed_order},
            )
            for rank, entry in enumerate(ranked_entries, start=1)
        ]
        return CommissionerRoundComplete(
            results=[CommissionerDivisionRanking(division_id=round_row.division_id, rankings=rankings)],
            round_display={"phases": [_phase_summary(pool, len(entries))]},
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_COMMISSIONER_REGISTRY: dict[str, type[Commissioner]] = {}


def register_commissioner(key: str, cls: type[Commissioner]) -> None:
    _COMMISSIONER_REGISTRY[key] = cls


def is_registered_commissioner(key: str) -> bool:
    return key in _COMMISSIONER_REGISTRY


def get_commissioner(key: str) -> Commissioner:
    cls = _COMMISSIONER_REGISTRY.get(key)
    if cls is None:
        raise ValueError(f"Unknown commissioner_key: {key}")
    return cls()


# Import game-specific commissioners for registration
from commissioners.among_them.commissioner import AmongThemCommissioner
from commissioners.cogs_vs_clips.commissioner import CogsVsClipsCommissioner
from commissioners.default.manual_commissioner import ManualCommissioner

register_commissioner("auto", BaselineCommissioner)
register_commissioner("manual", ManualCommissioner)
register_commissioner("cogs_vs_clips", CogsVsClipsCommissioner)
register_commissioner("among_them", AmongThemCommissioner)
