from __future__ import annotations

# ruff: noqa: F401,E402

from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import UTC, datetime, timedelta
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
    DivisionConfig,
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
    DivisionLeaderboardAxisSnapshot,
    DivisionLeaderboardColumnSnapshot,
    DivisionLeaderboardRowSnapshot,
    DivisionLeaderboardSnapshot,
    DivisionLeaderboardTablesSnapshot,
    DivisionLeaderboardViewSnapshot,
    DivisionLeaderboardsSnapshot,
    _LeaderboardAgg,
    LeaderboardRoundResultSnapshot,
    RoundSpec,
    ScheduleContext,
    LeagueMigrationConfigContext,
    LeagueMigrationContext,
    LeagueMigrationResult,
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
    COMPLETED_EPISODE_COUNT_METADATA_KEY,
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
    _build_rolling_window_entry_indices,
    _pool_episode_count,
    _score_lists_by_policy,
    _qualification_round_membership_changes,
    MEAN_ROUND_SCORE_KIND,
    MEAN_SCORE_EWMA_SCORING_MECHANICS,
    RANKED_SCORE_COUNT_METADATA_KEY,
)

# Re-export adapters for backwards compatibility
from commissioners.common.adapters import (
    schedule_episodes_for_round_start,
    complete_round_for_round_start,
    schedule_rounds_for_request,
    league_migration_config_for_request,
    migrate_league_for_request,
    rank_division_for_request,
    describe_division_for_request,
    round_completed_for_request,
)
from commissioners.common.ruleset_strategy.membership_events import build_default_competing_substatus_events


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

    def league_migration_config(self, ctx: LeagueMigrationConfigContext) -> list[DivisionConfig]:
        return [
            DivisionConfig(
                name=division.name,
                level=division.level,
                type=division.type,
            )
            for division in ctx.divisions
        ]

    def migrate_league(self, ctx: LeagueMigrationContext) -> LeagueMigrationResult:
        return LeagueMigrationResult()

    @abstractmethod
    def rank_division(self, ctx: DivisionLeaderboardContext) -> list[DivisionLeaderboardSnapshot]: ...

    def rank_division_leaderboards(self, ctx: DivisionLeaderboardContext) -> DivisionLeaderboardsSnapshot:
        # TODO: delete compatibility shim after all commissioners implement generic leaderboard views.
        entries = self.rank_division(ctx)
        view = DivisionLeaderboardViewSnapshot(
            key="score",
            title="Score",
            axis_values={"metric": "score", "timeframe": "legacy"},
            columns=[
                DivisionLeaderboardColumnSnapshot(key="rank", label="Rank", value_type="integer", sort="asc"),
                DivisionLeaderboardColumnSnapshot(key="score", label="Score", value_type="number", sort="desc"),
                DivisionLeaderboardColumnSnapshot(
                    key="rounds_played",
                    label="Rounds Played",
                    value_type="integer",
                ),
            ],
            rows=[
                DivisionLeaderboardRowSnapshot(
                    subject_id=entry.player_id,
                    subject_name=entry.player_name,
                    values={
                        "rank": entry.rank,
                        "score": entry.score,
                        "rounds_played": entry.rounds_played,
                    },
                    policy_version_ids=entry.policy_version_ids,
                    recent_rounds=entry.recent_rounds,
                )
                for entry in entries
            ],
        )
        return DivisionLeaderboardsSnapshot(
            default_view_key=view.key,
            axes=_leaderboard_axes([view]),
            views=[view],
        )

    def rank_division_tables(self, ctx: DivisionLeaderboardContext) -> DivisionLeaderboardTablesSnapshot:
        # TODO: delete compatibility shim after callers stop using table terminology.
        return self.rank_division_leaderboards(ctx)

    @abstractmethod
    def describe_division(self, ctx: DivisionDescriptionContext) -> DivisionCommissionerDescriptionPublic: ...

    def on_round_completed(self, ctx: OnRoundCompletedContext) -> OnRoundCompletedResult:
        return OnRoundCompletedResult(policy_membership_events=build_default_competing_substatus_events(ctx))

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


def _string_axis_values(raw_value: Any) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        return {}
    return {str(key): str(value) for key, value in raw_value.items()}


def _default_axis_values(score_key: str, window_hours: Any) -> dict[str, str]:
    return {
        "metric": score_key,
        "timeframe": f"{window_hours}h" if window_hours is not None else "all",
    }


def _leaderboard_axes(views: list[DivisionLeaderboardViewSnapshot]) -> list[DivisionLeaderboardAxisSnapshot]:
    axis_keys: list[str] = []
    for view in views:
        for key in view.axis_values:
            if key not in axis_keys:
                axis_keys.append(key)
    return [DivisionLeaderboardAxisSnapshot(key=key, label=key.replace("_", " ").title()) for key in axis_keys]


class BaselineCommissioner(Commissioner):
    """Cadence-scheduled commissioner with mean-score ranking and no graduation."""

    def _scheduling_config(self, commissioner_config: dict[str, Any] | None) -> RoundSchedulingConfig:
        return RoundSchedulingConfig.model_validate(commissioner_config or {})

    def _round_result_score(self, result: LeaderboardRoundResultSnapshot, score_key: str) -> float | None:
        if score_key == "score":
            return result.score
        scores = result.result_metadata.get("scores")
        if not isinstance(scores, dict):
            return None
        value = scores.get(score_key)
        return float(value) if isinstance(value, (int, float)) else None

    def _rank_division_view_by_metric(
        self,
        ctx: DivisionLeaderboardContext,
        *,
        view_key: str = "score",
        title: str = "Score",
        description: str | None = None,
        score_axis_label: str = "Score",
        axis_values: dict[str, str] | None = None,
        score_key: str = "score",
        half_life_hours: float | None = None,
        window_hours: float | None = None,
    ) -> DivisionLeaderboardViewSnapshot:
        columns = [
            DivisionLeaderboardColumnSnapshot(key="rank", label="Rank", value_type="integer", sort="asc"),
            DivisionLeaderboardColumnSnapshot(key=score_key, label=score_axis_label, value_type="number", sort="desc"),
            DivisionLeaderboardColumnSnapshot(key="rounds_played", label="Rounds Played", value_type="integer"),
        ]
        if not ctx.completed_rounds or not ctx.round_results:
            return DivisionLeaderboardViewSnapshot(
                key=view_key,
                title=title,
                description=description,
                axis_values=axis_values or {},
                columns=columns,
            )

        completed_rounds = ctx.completed_rounds
        latest_completed_at = completed_rounds[0].completed_at
        assert latest_completed_at is not None, f"Completed round {ctx.completed_rounds[0].id} is missing completed_at"
        if window_hours is not None:
            cutoff = latest_completed_at - timedelta(hours=window_hours)
            completed_rounds = [
                round_row
                for round_row in completed_rounds
                if round_row.completed_at is not None and round_row.completed_at >= cutoff
            ]
        if not completed_rounds:
            return DivisionLeaderboardViewSnapshot(
                key=view_key,
                title=title,
                description=description,
                axis_values=axis_values or {},
                columns=columns,
            )

        completed_rounds_by_id = {round_row.id: round_row for round_row in completed_rounds}
        halflife_seconds = (
            timedelta(hours=half_life_hours).total_seconds()
            if half_life_hours is not None
            else self._leaderboard_ewma_halflife(ctx).total_seconds()
        )

        player_rounds: dict[tuple[PlayerId, UUID], LeaderboardRoundResultSnapshot] = {}
        for result in ctx.round_results:
            if int(result.result_metadata.get(RANKED_SCORE_COUNT_METADATA_KEY, 1)) <= 0:
                continue
            score = self._round_result_score(result, score_key)
            if score is None:
                continue
            key = (result.player_id, result.round_id)
            current = player_rounds.get(key)
            current_score = self._round_result_score(current, score_key) if current is not None else None
            if current is None or current_score is None or (score, -result.rank) > (current_score, -current.rank):
                player_rounds[key] = result

        rounds_played_by_player: dict[PlayerId, int] = {}
        aggs: dict[PlayerId, _LeaderboardAgg] = {}
        for player_round in player_rounds.values():
            round_row = completed_rounds_by_id.get(player_round.round_id)
            if round_row is None:
                continue
            score = self._round_result_score(player_round, score_key)
            if score is None:
                continue
            rounds_played_by_player[player_round.player_id] = rounds_played_by_player.get(player_round.player_id, 0) + 1
            if player_round.player_id not in aggs:
                aggs[player_round.player_id] = _LeaderboardAgg(
                    player_id=player_round.player_id,
                    player_name=player_round.player_name,
                )
            assert round_row.completed_at is not None, f"Completed round {round_row.id} is missing completed_at"
            weight = 0.5 ** ((latest_completed_at - round_row.completed_at).total_seconds() / halflife_seconds)
            aggs[player_round.player_id].policy_version_ids.add(player_round.policy_version_id)
            aggs[player_round.player_id].weighted_score_sum += score * weight
            aggs[player_round.player_id].weight_sum += weight

        ranks_by_round_and_player = {
            (player_round.round_id, player_round.player_id): player_round.rank
            for player_round in player_rounds.values()
        }
        scores_by_round_and_player = {
            (player_round.round_id, player_round.player_id): self._round_result_score(player_round, score_key)
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
            [agg for agg in aggs.values() if agg.weight_sum > 0],
            key=lambda agg: (
                -agg.score(),
                agg.player_name or "",
                str(agg.player_id),
            ),
        )
        return DivisionLeaderboardViewSnapshot(
            key=view_key,
            title=title,
            description=description,
            axis_values=axis_values or {},
            columns=columns,
            rows=[
                DivisionLeaderboardRowSnapshot(
                    subject_id=agg.player_id,
                    subject_name=agg.player_name,
                    values={
                        "rank": rank,
                        score_key: agg.score(),
                        "rounds_played": rounds_played_by_player[agg.player_id],
                    },
                    policy_version_ids=agg.policy_version_ids,
                    recent_rounds=build_recent_rounds(agg.player_id),
                )
                for rank, agg in enumerate(ranked_aggs, start=1)
            ],
        )

    def _rank_division_leaderboards_from_config(
        self,
        ctx: DivisionLeaderboardContext,
        leaderboard_configs: list[dict[str, Any]],
        *,
        default_half_life_hours: float | None = None,
    ) -> DivisionLeaderboardsSnapshot:
        if not leaderboard_configs:
            leaderboard_configs = [{"key": "score", "title": "Score", "score_key": "score", "default": True}]

        default_view_key = "score"
        views: list[DivisionLeaderboardViewSnapshot] = []
        for raw_view in leaderboard_configs:
            raw_columns = raw_view.get("columns")
            # TODO: delete compatibility alias after old configs stop using axes as display columns.
            raw_columns = raw_columns if raw_columns is not None else raw_view.get("axes")
            columns_config: list[Any] = raw_columns if isinstance(raw_columns, list) else []
            configured_score_axis = next(
                (column for column in columns_config if isinstance(column, dict) and column.get("sort") == "desc"),
                None,
            )
            score_key = str(
                raw_view.get("score_key")
                or raw_view.get("metric")
                or (configured_score_axis or {}).get("key")
                or raw_view.get("key")
                or raw_view.get("id")
                or "score"
            )
            view_key = str(raw_view.get("key") or raw_view.get("id") or score_key)
            if raw_view.get("default", raw_view.get("primary", False)):
                default_view_key = view_key
            title = str(raw_view.get("title") or raw_view.get("label") or score_key.replace("_", " ").title())
            score_axis_label = str(raw_view.get("score_axis_label") or raw_view.get("score_label") or title)
            window_hours = raw_view.get("window_hours", raw_view.get("lookback_hours"))
            axis_values = _string_axis_values(raw_view.get("axis_values")) or _default_axis_values(
                score_key,
                window_hours,
            )
            view = self._rank_division_view_by_metric(
                ctx,
                view_key=view_key,
                title=title,
                description=raw_view.get("description"),
                score_axis_label=score_axis_label,
                axis_values=axis_values,
                score_key=score_key,
                half_life_hours=float(raw_view.get("half_life_hours", default_half_life_hours))
                if raw_view.get("half_life_hours", default_half_life_hours) is not None
                else None,
                window_hours=float(window_hours) if window_hours is not None else None,
            )
            if columns_config:
                view.columns = [DivisionLeaderboardColumnSnapshot.model_validate(column) for column in columns_config]
            views.append(view)

        if not any(view.key == default_view_key for view in views) and views:
            default_view_key = views[0].key
        return DivisionLeaderboardsSnapshot(default_view_key=default_view_key, axes=_leaderboard_axes(views), views=views)

    def _rank_division_tables_from_config(
        self,
        ctx: DivisionLeaderboardContext,
        leaderboard_configs: list[dict[str, Any]],
        *,
        default_half_life_hours: float | None = None,
    ) -> DivisionLeaderboardTablesSnapshot:
        # TODO: delete compatibility shim after callers stop using table terminology.
        return self._rank_division_leaderboards_from_config(
            ctx,
            leaderboard_configs,
            default_half_life_hours=default_half_life_hours,
        )

    def rank_division_leaderboards(self, ctx: DivisionLeaderboardContext) -> DivisionLeaderboardsSnapshot:
        return self._rank_division_leaderboards_from_config(ctx, [])

    def rank_division_tables(self, ctx: DivisionLeaderboardContext) -> DivisionLeaderboardTablesSnapshot:
        # TODO: delete compatibility shim after callers stop using table terminology.
        return self.rank_division_leaderboards(ctx)

    def rank_division(self, ctx: DivisionLeaderboardContext) -> list[DivisionLeaderboardSnapshot]:
        if not ctx.completed_rounds or not ctx.round_results:
            return []

        completed_rounds_by_id = {round_row.id: round_row for round_row in ctx.completed_rounds}
        latest_completed_at = ctx.completed_rounds[0].completed_at
        assert latest_completed_at is not None, f"Completed round {ctx.completed_rounds[0].id} is missing completed_at"

        player_rounds: dict[tuple[PlayerId, UUID], LeaderboardRoundResultSnapshot] = {}
        for result in ctx.round_results:
            if int(result.result_metadata.get(RANKED_SCORE_COUNT_METADATA_KEY, 1)) <= 0:
                continue
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
                / self._leaderboard_ewma_halflife(ctx).total_seconds()
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

    def _leaderboard_ewma_halflife(self, ctx: DivisionLeaderboardContext) -> timedelta:
        return DIVISION_LEADERBOARD_SCORE_EWMA_HALFLIFE

    def on_round_completed(self, ctx: OnRoundCompletedContext) -> OnRoundCompletedResult:
        return OnRoundCompletedResult(
            policy_membership_events=build_default_competing_substatus_events(ctx),
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
        is_qualifier = select_qualifier_division(ctx.league.commissioner_config, [ctx.division]) is not None
        minimum_entrants = config.qualifiers_minimum_champions if is_qualifier else config.minimum_champions
        entrant_label = "qualifying entrant" if is_qualifier else "champion entrant"
        stages = config.qualifier_stages if is_qualifier and config.qualifier_stages is not None else config.stages
        entrant_count = len(division_entrants(ctx.active_memberships, ctx.division, is_qualifier=is_qualifier))
        next_round = None
        if entrant_count < minimum_entrants:
            needed = minimum_entrants - entrant_count
            next_round = f"Add {needed} more {_plural_word(needed, entrant_label)} before scheduling can continue."
        elif active_round is not None:
            next_round = f"The next round waits for round #{active_round.round_number} to finish."

        return DivisionCommissionerDescriptionPublic(
            round_schedule=(
                f"Rounds start every {_duration_text(config.schedule_interval_minutes)}"
                f"{_schedule_slot_description(config)} if there are at least "
                f"{_count_text(minimum_entrants)} {_plural_word(minimum_entrants, entrant_label)} in the division."
            ),
            next_round=next_round,
            round_structure=_round_structure_description(stages),
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

            stages = config.qualifier_stages if is_qualifier and config.qualifier_stages is not None else config.stages
            specs.append(
                RoundSpec(
                    division_id=division.id,
                    round_config=V2RoundConfig(
                        stages=stages,
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

    def _round_scores_by_policy(
        self,
        entries: list[PolicyPoolEntry],
        episode_results: list[EpisodeResult],
    ) -> tuple[dict[UUID, float], dict[UUID, int]]:
        """Per-policy round score and the number of samples behind each.

        Default: the mean of a policy's per-episode scores. Subclasses (e.g. the ruleset
        commissioner's rank-by-episode mode) override this to score rounds differently while
        reusing the ranking/metadata assembly in ``complete_round``.
        """
        score_lists = _score_lists_by_policy(episode_results)
        scores = {
            entry.policy_version_id: (
                sum(score_lists.get(entry.policy_version_id, [])) / len(score_lists.get(entry.policy_version_id, []))
                if score_lists.get(entry.policy_version_id)
                else 0.0
            )
            for entry in entries
        }
        ranked_counts = {
            entry.policy_version_id: len(score_lists.get(entry.policy_version_id, [])) for entry in entries
        }
        return scores, ranked_counts

    def complete_round(
        self,
        *,
        round_row: Round,
        pool: PolicyPool,
        entries: list[PolicyPoolEntry],
        episode_results: list[EpisodeResult],
    ) -> CommissionerRoundComplete:
        round_score_by_policy, ranked_score_counts = self._round_scores_by_policy(entries, episode_results)
        completed_episode_counts: dict[UUID, int] = defaultdict(int)
        for result in episode_results:
            for policy_version_id in {score.policy_version_id for score in result.scores}:
                completed_episode_counts[policy_version_id] += 1
        ranked_entries = sorted(
            entries,
            key=lambda entry: (
                -round_score_by_policy[entry.policy_version_id],
                entry.seed_order,
                str(entry.policy_version_id),
            ),
        )
        rankings = [
            CommissionerRankingEntry(
                policy_version_id=entry.policy_version_id,
                player_id=str(entry.player_id) if entry.player_id is not None else None,
                rank=rank,
                score=round_score_by_policy[entry.policy_version_id],
                result_metadata={
                    "seed_order": entry.seed_order,
                    COMPLETED_EPISODE_COUNT_METADATA_KEY: completed_episode_counts[entry.policy_version_id],
                    RANKED_SCORE_COUNT_METADATA_KEY: ranked_score_counts[entry.policy_version_id],
                },
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


from commissioners.common.ruleset_strategy.commissioner import RulesetStrategyCommissioner
from commissioners.default.manual_commissioner import ManualCommissioner

register_commissioner("config_driven", RulesetStrategyCommissioner)
register_commissioner("ruleset_strategy", RulesetStrategyCommissioner)
register_commissioner("manual", ManualCommissioner)
