from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from commissioners.common.commissioners import BaselineCommissioner
from commissioners.common.models import (
    DIVISION_TYPE_STAGING,
    AmongThemSchedulingConfig,
    DivisionCommissionerDescriptionPublic,
    DivisionDescriptionContext,
    DivisionLeaderboardContext,
    DivisionLeaderboardSnapshot,
    DivisionSnapshot,
    EpisodeResult,
    OnRoundCompletedContext,
    OnRoundCompletedResult,
    PolicyPool,
    PolicyPoolEntry,
    PoolConfig,
    Round,
    RoundSpec,
    ScheduleContext,
    V2RoundConfig,
)
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
from commissioners.common.utils import (
    AMONG_THEM_RESULT_METADATA_VERSION,
    AMONG_THEM_SCORE_KIND,
    AMONG_THEM_SCORING_MECHANICS,
    _count_text,
    _current_schedule_slot,
    _duration_text,
    _leaderboard_rules_description,
    _plural_word,
    _pool_episode_count,
    _qualification_round_membership_changes,
    _round_structure_description,
    _schedule_slot_description,
    division_entrants,
    select_competition_entry_division,
    select_qualifier_division,
)
from commissioners.common.models import MembershipChange


class AmongThemCommissioner(BaselineCommissioner):
    """Among Them seat rotation with average game-score ranking."""

    def _scheduling_config(self, commissioner_config: dict[str, Any] | None) -> AmongThemSchedulingConfig:
        return AmongThemSchedulingConfig.model_validate(commissioner_config or {})

    def _is_dirt_division(self, division: DivisionSnapshot, config: AmongThemSchedulingConfig) -> bool:
        return division.name == config.dirt_division_name

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
            is_dirt = self._is_dirt_division(division, config)
            if is_qualifier:
                min_champs = config.qualifiers_minimum_champions
            elif is_dirt:
                min_champs = config.dirt_minimum_champions
            else:
                min_champs = config.minimum_champions
            if len(entrants) < min_champs:
                continue

            if is_qualifier:
                stages = config.qualifier_stages
            elif is_dirt:
                stages = config.dirt_stages
            else:
                stages = config.stages

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

    def describe_division(self, ctx: DivisionDescriptionContext) -> DivisionCommissionerDescriptionPublic:
        config = self._scheduling_config(ctx.league.commissioner_config)
        is_qualifier = select_qualifier_division(ctx.league.commissioner_config, [ctx.division]) is not None
        if is_qualifier:
            minimum_entrants, stages, entrant_label = (
                config.qualifiers_minimum_champions,
                config.qualifier_stages,
                "qualifying entrant",
            )
        elif self._is_dirt_division(ctx.division, config):
            minimum_entrants, stages, entrant_label = (
                config.dirt_minimum_champions,
                config.dirt_stages,
                "champion entrant",
            )
        else:
            minimum_entrants, stages, entrant_label = (
                config.minimum_champions,
                config.stages,
                "champion entrant",
            )

        active_round = next((r for r in ctx.recent_rounds if r.status in ("pending", "claimed", "running")), None)
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
                f"{_count_text(minimum_entrants)} {_plural_word(minimum_entrants, entrant_label)} "
                "in the division."
            ),
            next_round=next_round,
            round_structure=_round_structure_description(stages),
            leaderboard_rules=_leaderboard_rules_description(),
            scoring_mechanics=AMONG_THEM_SCORING_MECHANICS,
        )

    def rank_division(self, ctx: DivisionLeaderboardContext) -> list[DivisionLeaderboardSnapshot]:
        current_results = [
            result
            for result in ctx.round_results
            if "version" in result.result_metadata
            and "score_kind" in result.result_metadata
            and result.result_metadata["version"] == AMONG_THEM_RESULT_METADATA_VERSION
            and result.result_metadata["score_kind"] == AMONG_THEM_SCORE_KIND
        ]
        return super().rank_division(ctx.model_copy(update={"round_results": current_results}))

    def schedule_episodes(
        self,
        *,
        pool: PolicyPool,
        entries: list[PolicyPoolEntry],
        num_agents: int,
        variant_id: str,
    ) -> CommissionerScheduleEpisodes:
        config = PoolConfig.model_validate(pool.config)

        if config.self_play:
            # Each entrant gets its own episodes with every seat filled by its own
            # policy, so its score reflects only its own play, not its opponents'.
            # min_episodes_per_entrant is the number of self-play episodes per entrant
            # (not divided across seats, since each episode features one entrant).
            episodes_per_entrant = config.min_episodes_per_entrant or config.num_episodes
            episodes = [
                CommissionerEpisodeRequest(
                    request_id=str(entry_index * episodes_per_entrant + episode_index),
                    variant_id=variant_id,
                    policy_version_ids=[entry.policy_version_id] * num_agents,
                    tags={"pool_id": str(pool.id)},
                )
                for entry_index, entry in enumerate(entries)
                for episode_index in range(episodes_per_entrant)
            ]
            return CommissionerScheduleEpisodes(episodes=episodes)

        num_episodes = _pool_episode_count(
            config=config,
            num_entries=len(entries),
            num_agents=num_agents,
        )
        episodes = [
            CommissionerEpisodeRequest(
                request_id=str(job_index),
                variant_id=variant_id,
                policy_version_ids=[
                    entries[(job_index + seat) % len(entries)].policy_version_id for seat in range(num_agents)
                ],
                tags={"pool_id": str(pool.id)},
            )
            for job_index in range(num_episodes)
        ]
        return CommissionerScheduleEpisodes(episodes=episodes)

    def complete_round(
        self,
        *,
        round_row: Round,
        pool: PolicyPool,
        entries: list[PolicyPoolEntry],
        episode_results: list[EpisodeResult],
    ) -> CommissionerRoundComplete:
        complete = super().complete_round(
            round_row=round_row,
            pool=pool,
            entries=entries,
            episode_results=episode_results,
        )
        for division_ranking in complete.results:
            for ranking in division_ranking.rankings:
                ranking.result_metadata = dict(ranking.result_metadata) | {
                    "score_kind": AMONG_THEM_SCORE_KIND,
                    "version": AMONG_THEM_RESULT_METADATA_VERSION,
                }
        return complete

    def on_round_completed(self, ctx: OnRoundCompletedContext) -> OnRoundCompletedResult:
        config = self._scheduling_config(ctx.commissioner_config)
        qualification_changes = _qualification_round_membership_changes(
            ctx,
            qualifier_division=select_qualifier_division(ctx.commissioner_config, ctx.all_divisions),
            competition_entry_division=select_competition_entry_division(ctx.commissioner_config, ctx.all_divisions),
        )
        if ctx.division.type == DIVISION_TYPE_STAGING:
            return OnRoundCompletedResult(membership_changes=qualification_changes)

        dirt_division = next((d for d in ctx.all_divisions if d.name == config.dirt_division_name), None)
        wood_division = next((d for d in ctx.all_divisions if d.name == config.wood_division_name), None)
        if dirt_division is None or wood_division is None:
            return OnRoundCompletedResult()

        current_round_results = [r for r in ctx.round_results if r.round_id == ctx.round_results[0].round_id]
        membership_by_policy = {m.policy_version_id: m for m in ctx.division_memberships}

        changes: list[MembershipChange] = []
        for result in current_round_results:
            membership = membership_by_policy.get(result.policy_version_id)
            if membership is None:
                continue

            target_division = wood_division if result.score > 0 else dirt_division

            if membership.division_id != target_division.id:
                changes.append(
                    MembershipChange(
                        membership_id=membership.id,
                        from_division_id=membership.division_id,
                        to_division_id=target_division.id,
                        reason="average score > 0: promoted to Wood"
                        if result.score > 0
                        else "average score <= 0: relegated to Dirt",
                    )
                )

        return OnRoundCompletedResult(membership_changes=changes)
