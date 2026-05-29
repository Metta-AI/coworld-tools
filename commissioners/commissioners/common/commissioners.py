from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import ceil
from os import getenv
from typing import Any
from uuid import UUID

from commissioners.common.protocol import (
    DescribeDivisionRequest,
    DescribeDivisionResponse,
    DivisionDescription as CommissionerDivisionDescription,
    DivisionLeaderboardEntry as CommissionerDivisionLeaderboardEntry,
    DivisionRanking as CommissionerDivisionRanking,
)
from commissioners.common.protocol import (
    EpisodeRequest as CommissionerEpisodeRequest,
)
from commissioners.common.protocol import (
    EpisodeResult as CommissionerProtocolEpisodeResult,
)
from commissioners.common.protocol import (
    GraduationChange as CommissionerGraduationChange,
)
from commissioners.common.protocol import (
    MembershipChange as CommissionerMembershipChange,
)
from commissioners.common.protocol import (
    RankDivisionRequest,
    RankDivisionResponse,
)
from commissioners.common.protocol import (
    RankingEntry as CommissionerRankingEntry,
)
from commissioners.common.protocol import (
    RoundCompletedRequest,
    RoundCompletedResponse,
)
from commissioners.common.protocol import (
    RoundComplete as CommissionerRoundComplete,
)
from commissioners.common.protocol import (
    RoundInfo,
)
from commissioners.common.protocol import (
    RoundSpec as CommissionerRoundSpec,
)
from commissioners.common.protocol import (
    RoundStart as CommissionerRoundStart,
)
from commissioners.common.protocol import (
    ScheduleRoundsRequest,
    ScheduleRoundsResponse,
)
from commissioners.common.protocol import (
    ScheduleEpisodes as CommissionerScheduleEpisodes,
)
from pydantic import BaseModel, Field, model_validator

PlayerId = str
RoundId = str
SubmissionId = str

DIVISION_TYPE_COMPETITION = "competition"
DIVISION_TYPE_STAGING = "staging"


class RoundExecutionBackend(StrEnum):
    mock = "mock"
    dispatch = "dispatch"


class DivisionCommissionerDescriptionPublic(BaseModel):
    round_schedule: str | None = None
    next_round: str | None = None
    round_structure: str | None = None
    leaderboard_rules: str | None = None
    scoring_mechanics: str | None = None


class LeaderboardRecentRoundPublic(BaseModel):
    id: RoundId
    round_number: int
    status: str
    rank: int | None = None
    score: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class League(BaseModel):
    id: UUID
    commissioner_key: str
    commissioner_config: dict[str, Any] | None = None


class Division(BaseModel):
    id: UUID
    name: str
    level: int
    league_id: UUID
    type: str = DIVISION_TYPE_COMPETITION


class LeaguePolicyMembership(BaseModel):
    id: UUID
    league_id: UUID
    division_id: UUID
    policy_version_id: UUID
    player_id: PlayerId | None = None
    is_champion: bool = False


class PolicyPool(BaseModel):
    id: UUID
    label: str = "Round"
    pool_type: str = "round"
    config: dict[str, Any] = Field(default_factory=dict)


class PolicyPoolEntry(BaseModel):
    pool_id: UUID
    policy_version_id: UUID
    player_id: PlayerId | None = None
    seed_order: int


class Round(BaseModel):
    id: UUID
    public_id: RoundId | None = None
    division_id: UUID
    round_number: int
    commissioner_key: str
    round_config: dict[str, Any] = Field(default_factory=dict)
    status: str = "running"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RoundResult(BaseModel):
    round_id: UUID
    policy_version_id: UUID
    rank: int
    score: float
    result_metadata: dict[str, Any] = Field(default_factory=dict)

PLACEMENT_DRY_RUN_POOL_TYPE = "placement_dry_run"
DIVISION_LEADERBOARD_SCORE_EWMA_HALFLIFE_HOURS = 2
DIVISION_LEADERBOARD_SCORE_EWMA_HALFLIFE = timedelta(hours=DIVISION_LEADERBOARD_SCORE_EWMA_HALFLIFE_HOURS)


# ---------------------------------------------------------------------------
# Pool / episode / round models
# ---------------------------------------------------------------------------


class PoolPlan(BaseModel):
    label: str
    pool_type: str
    config: dict[str, Any] = Field(default_factory=dict)


class PoolEntryPlan(BaseModel):
    league_policy_membership_id: UUID | None = None
    policy_version_id: UUID
    player_id: PlayerId | None = None
    seed_order: int


class RoundPolicyScore(BaseModel):
    policy_version_id: UUID
    player_id: PlayerId | None = None
    score: float


class EpisodeResult(BaseModel):
    episode_request_id: UUID
    scores: list[RoundPolicyScore]
    game_results: dict[str, Any] | None = None


class MembershipChange(BaseModel):
    membership_id: UUID
    from_division_id: UUID
    to_division_id: UUID | None = None
    is_active: bool = True
    reason: str


class V2StageConfig(BaseModel):
    label: str = "Round"
    num_episodes: int = Field(default=1, gt=0)
    min_episodes_per_entrant: int | None = Field(default=None, gt=0)


class V2RoundConfig(BaseModel):
    mock_scores: dict[UUID, float] | None = None
    stages: list[V2StageConfig] | None = None
    entrant_policy_version_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def require_single_stage(self) -> V2RoundConfig:
        if self.stages is not None and len(self.stages) != 1:
            raise ValueError("V2RoundConfig.stages must have exactly one stage")
        return self


class PoolConfig(BaseModel):
    num_episodes: int = Field(default=1, gt=0)
    min_episodes_per_entrant: int | None = Field(default=None, gt=0)
    mock_scores: dict[UUID, float] | None = None


class RoundSchedulingConfig(BaseModel):
    schedule_interval_minutes: int = Field(default=10, gt=0)
    default_execution_backend: str = "mock"
    minimum_champions: int = Field(default=2, gt=0)
    qualifiers_minimum_champions: int = Field(default=1, gt=0)
    stages: list[V2StageConfig] | None = None

    @model_validator(mode="after")
    def require_single_stage(self) -> RoundSchedulingConfig:
        if self.stages is not None and len(self.stages) != 1:
            raise ValueError("RoundSchedulingConfig.stages must have exactly one stage")
        return self

    def effective_execution_backend(self) -> RoundExecutionBackend:
        backend = RoundExecutionBackend(self.default_execution_backend)
        if backend == RoundExecutionBackend.mock and getenv("LOCAL_DEV", "").lower() not in {"1", "true", "yes"}:
            return RoundExecutionBackend.dispatch
        return backend


DEFAULT_STAGES = [V2StageConfig(label="Round", num_episodes=1)]
AMONG_THEM_DEFAULT_STAGE = V2StageConfig(
    label="Round",
    num_episodes=100,
    min_episodes_per_entrant=100,
)
AMONG_THEM_DIRT_STAGE = V2StageConfig(
    label="Round",
    num_episodes=8,
    min_episodes_per_entrant=8,
)


class AmongThemSchedulingConfig(RoundSchedulingConfig):
    schedule_interval_minutes: int = Field(default=10, gt=0)
    default_execution_backend: str = "dispatch"
    stages: list[V2StageConfig] | None = Field(default_factory=lambda: [AMONG_THEM_DEFAULT_STAGE])
    dirt_stages: list[V2StageConfig] | None = Field(default_factory=lambda: [AMONG_THEM_DIRT_STAGE])
    # Dirt exists to evaluate unproven policies, so it needs to run with very few entrants.
    dirt_minimum_champions: int = Field(default=2, gt=0)
    dirt_division_name: str = "Dirt"
    wood_division_name: str = "Wood"

    @model_validator(mode="after")
    def require_inferred_minimum_champions(self) -> AmongThemSchedulingConfig:
        if "minimum_champions" not in self.model_fields_set:
            raise ValueError("AmongThem scheduling requires minimum_champions inferred from the Coworld token count")
        return self


# ---------------------------------------------------------------------------
# Snapshot models — lightweight copies of ORM objects for commissioner methods.
# ---------------------------------------------------------------------------


class LeagueSnapshot(BaseModel):
    id: UUID
    commissioner_key: str
    commissioner_config: dict[str, Any] | None

    @staticmethod
    def from_orm(league: League) -> LeagueSnapshot:
        return LeagueSnapshot(
            id=league.id,
            commissioner_key=league.commissioner_key,
            commissioner_config=league.commissioner_config,
        )


class DivisionSnapshot(BaseModel):
    id: UUID
    name: str
    level: int
    league_id: UUID
    type: str = DIVISION_TYPE_COMPETITION

    @staticmethod
    def from_orm(division: Division) -> DivisionSnapshot:
        return DivisionSnapshot(
            id=division.id,
            name=division.name,
            level=division.level,
            league_id=division.league_id,
            type=division.type,
        )


class MembershipSnapshot(BaseModel):
    id: UUID
    league_id: UUID
    division_id: UUID
    policy_version_id: UUID
    player_id: PlayerId | None
    is_champion: bool

    @staticmethod
    def from_orm(m: LeaguePolicyMembership) -> MembershipSnapshot:
        return MembershipSnapshot(
            id=m.id,
            league_id=m.league_id,
            division_id=m.division_id,
            policy_version_id=m.policy_version_id,
            player_id=m.player_id,
            is_champion=m.is_champion,
        )


class RoundSnapshot(BaseModel):
    id: UUID
    public_id: RoundId
    division_id: UUID
    round_number: int
    status: str
    round_config: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @staticmethod
    def from_orm(r: Round) -> RoundSnapshot:
        return RoundSnapshot(
            id=r.id,
            public_id=r.round_id,
            division_id=r.division_id,
            round_number=r.round_number,
            status=r.status,
            round_config=r.round_config,
            created_at=r.created_at,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )


class RoundResultSnapshot(BaseModel):
    round_id: UUID
    policy_version_id: UUID
    rank: int
    score: float
    result_metadata: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def from_orm(r: RoundResult) -> RoundResultSnapshot:
        return RoundResultSnapshot(
            round_id=r.round_id,
            policy_version_id=r.policy_version_id,
            rank=r.rank,
            score=r.score,
            result_metadata=r.result_metadata or {},
        )


class DivisionLeaderboardSnapshot(BaseModel):
    player_id: PlayerId
    player_name: str | None = None
    rank: int
    score: float
    rounds_played: int
    policy_version_ids: set[UUID] = Field(default_factory=set)
    recent_rounds: list[LeaderboardRecentRoundPublic] | None = None


class _LeaderboardAgg(BaseModel):
    player_id: PlayerId
    player_name: str | None = None
    policy_version_ids: set[UUID] = Field(default_factory=set)
    weighted_score_sum: float = 0.0
    weight_sum: float = 0.0

    def score(self) -> float:
        return self.weighted_score_sum / self.weight_sum


class LeaderboardRoundResultSnapshot(RoundResultSnapshot):
    player_id: PlayerId
    player_name: str | None = None


# ---------------------------------------------------------------------------
# Scheduling context and result models
# ---------------------------------------------------------------------------


class RoundSpec(BaseModel):
    """A round the commissioner wants the pipeline to create."""

    division_id: UUID
    round_config: V2RoundConfig
    execution_backend: str = "mock"
    notes: str | None = None


class ScheduleContext(BaseModel):
    league: LeagueSnapshot
    divisions: list[DivisionSnapshot]
    active_memberships: list[MembershipSnapshot]
    recent_rounds: list[RoundSnapshot]


class DivisionLeaderboardContext(BaseModel):
    league: LeagueSnapshot
    division: DivisionSnapshot
    completed_rounds: list[RoundSnapshot]
    recent_rounds: list[RoundSnapshot]
    round_results: list[LeaderboardRoundResultSnapshot]


class SubmissionPlacementContext(BaseModel):
    league: LeagueSnapshot
    submission_public_id: SubmissionId
    policy_version_id: UUID
    player_id: PlayerId
    num_agents: int


class OnRoundCompletedContext(BaseModel):
    league: LeagueSnapshot
    division: DivisionSnapshot
    all_divisions: list[DivisionSnapshot]
    round_config: V2RoundConfig
    round_results: list[RoundResultSnapshot]
    division_memberships: list[MembershipSnapshot]
    recent_results: list[RoundResultSnapshot]
    commissioner_config: dict[str, Any] | None


class OnRoundCompletedResult(BaseModel):
    membership_changes: list[MembershipChange] = Field(default_factory=list)
    follow_up_rounds: list[RoundSpec] = Field(default_factory=list)


class DivisionDescriptionContext(BaseModel):
    league: LeagueSnapshot
    division: DivisionSnapshot
    active_memberships: list[MembershipSnapshot]
    recent_rounds: list[RoundSnapshot]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def select_division(
    divisions: list[DivisionSnapshot],
    *,
    division_name: str | None,
    fallback_to_lowest: bool,
    division_type: str | None = None,
) -> DivisionSnapshot | None:
    candidates = [division for division in divisions if division_type is None or division.type == division_type]
    if division_name:
        division = next((division for division in candidates if division.name == division_name), None)
        if division is not None:
            return division
    if fallback_to_lowest:
        return min(candidates, key=lambda division: division.level, default=None)
    return None


def select_qualifier_division(
    commissioner_config: dict[str, Any] | None,
    divisions: list[DivisionSnapshot],
) -> DivisionSnapshot | None:
    config = commissioner_config or {}
    qualifiers_division_name = config.get("qualifiers_division_name")
    if not qualifiers_division_name:
        return None
    return select_division(
        divisions,
        division_name=qualifiers_division_name,
        division_type=DIVISION_TYPE_STAGING,
        fallback_to_lowest=False,
    )


def select_competition_entry_division(
    commissioner_config: dict[str, Any] | None,
    divisions: list[DivisionSnapshot],
) -> DivisionSnapshot | None:
    config = commissioner_config or {}
    return select_division(
        divisions,
        division_name=config.get("default_division_name"),
        division_type=DIVISION_TYPE_COMPETITION,
        fallback_to_lowest=True,
    )


_SMALL_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}


def _count_text(count: int) -> str:
    return _SMALL_NUMBER_WORDS.get(count, str(count))


def _plural_word(count: int, singular: str) -> str:
    return singular if count == 1 else f"{singular}s"


def _leaderboard_rules_description() -> str:
    return "Division rankings are ordered by each player's score from completed division rounds."


AMONG_THEM_SCORING_MECHANICS = (
    "Among Them rounds rank policies by the average score reported by the game across each policy's episode slots. "
    "The division leaderboard only uses current average-score round results and combines completed rounds with a "
    "2-hour half-life EWMA, so newer rounds count more than older rounds."
)
AMONG_THEM_RESULT_METADATA_VERSION = 2
AMONG_THEM_SCORE_KIND = "mean_round_score"


def _duration_text(minutes: int) -> str:
    if minutes == 30:
        return "half hour"
    return f"{_count_text(minutes)} {_plural_word(minutes, 'minute')}"


def _join_text(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _schedule_slot_description(config: RoundSchedulingConfig) -> str:
    if 60 % config.schedule_interval_minutes == 0:
        slots = [f":{minute:02d}" for minute in range(0, 60, config.schedule_interval_minutes)]
        return f" at {_join_text(slots)}"
    return ""


def _current_schedule_slot(now: datetime, config: RoundSchedulingConfig) -> datetime:
    minute_index = int(now.timestamp() // 60)
    slot_index = minute_index - (minute_index % config.schedule_interval_minutes)
    return datetime.fromtimestamp(slot_index * 60, UTC)


def _round_structure_description(stages: list[V2StageConfig] | None) -> str:
    stages = stages or DEFAULT_STAGES
    phase_count = "one phase" if len(stages) == 1 else f"{_count_text(len(stages))} phases"
    phases = []
    for stage in stages:
        if stage.min_episodes_per_entrant is not None:
            episodes = f"at least {stage.min_episodes_per_entrant} appearances per entrant"
        else:
            episodes = f"{stage.num_episodes} {_plural_word(stage.num_episodes, 'episode')}"
        phases.append(f"{stage.label}: {episodes}")
    return f"Rounds have {phase_count}: {'; '.join(phases)}."


def _build_entry_indices(*, num_entries: int, num_agents: int, offset: int = 0) -> list[int]:
    if num_entries <= 0:
        raise ValueError("pool must have at least one entry")
    offset %= num_entries
    if num_entries > num_agents:
        return [(offset + i) % num_entries for i in range(num_agents)]
    if num_entries == num_agents:
        return [(offset + i) % num_entries for i in range(num_entries)]
    entry_indices = list(range(num_entries)) * (num_agents // num_entries + 1)
    return [(idx + offset) % num_entries for idx in entry_indices[:num_agents]]


def _entry_index_offset(*, job_index: int, num_entries: int, num_agents: int) -> int:
    if num_entries <= num_agents:
        return job_index
    return job_index * num_agents


def _build_slot_balanced_entry_indices(*, job_index: int, num_entries: int, num_agents: int) -> list[int]:
    if num_entries <= 0:
        raise ValueError("pool must have at least one entry")
    return [(job_index + seat) % num_entries for seat in range(num_agents)]


def _pool_episode_count(*, config: PoolConfig, num_entries: int, num_agents: int) -> int:
    if config.min_episodes_per_entrant is None:
        return config.num_episodes
    return max(config.num_episodes, ceil(num_entries * config.min_episodes_per_entrant / num_agents))


def _score_lists_by_policy(episode_results: list[EpisodeResult]) -> dict[UUID, list[float]]:
    score_lists: dict[UUID, list[float]] = defaultdict(list)
    for result in episode_results:
        for score in result.scores:
            score_lists[score.policy_version_id].append(score.score)
    return score_lists


def _qualification_round_membership_changes(
    ctx: OnRoundCompletedContext,
    *,
    qualifier_division: DivisionSnapshot | None,
    competition_entry_division: DivisionSnapshot | None,
) -> list[MembershipChange]:
    if qualifier_division is None or ctx.division.id != qualifier_division.id:
        return []

    assert qualifier_division.type == DIVISION_TYPE_STAGING, "qualifier division must be a staging division"
    assert competition_entry_division is not None, "qualification round requires a competition entry division"
    qualified_policy_ids = {result.policy_version_id for result in ctx.round_results}
    return [
        MembershipChange(
            membership_id=membership.id,
            from_division_id=membership.division_id,
            to_division_id=competition_entry_division.id,
            reason=f"qualified from {ctx.division.name} to {competition_entry_division.name}",
        )
        if membership.policy_version_id in qualified_policy_ids
        else MembershipChange(
            membership_id=membership.id,
            from_division_id=membership.division_id,
            is_active=False,
            reason=f"did not qualify from {ctx.division.name}",
        )
        for membership in ctx.division_memberships
        if membership.division_id == ctx.division.id
    ]


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

            division_champions = [m for m in ctx.active_memberships if m.division_id == division.id and m.is_champion]
            is_qualifier = qualifier_division is not None and division.id == qualifier_division.id
            min_champs = config.qualifiers_minimum_champions if is_qualifier else config.minimum_champions
            if len(division_champions) < min_champs:
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


class ManualCommissioner(BaselineCommissioner):
    """Same scoring as the baseline but never auto-schedules rounds."""

    def schedule_rounds(self, ctx: ScheduleContext) -> list[RoundSpec]:
        return []

    def describe_division(self, ctx: DivisionDescriptionContext) -> DivisionCommissionerDescriptionPublic:
        config = self._scheduling_config(ctx.league.commissioner_config)
        return DivisionCommissionerDescriptionPublic(
            round_schedule="Rounds are created manually.",
            round_structure=_round_structure_description(config.stages),
            leaderboard_rules=_leaderboard_rules_description(),
        )


class CogsVsClipsCommissioner(BaselineCommissioner):
    """Cogs vs Clips slot-balanced scheduling with baseline mean-score ranking."""

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
            entry_indices = _build_slot_balanced_entry_indices(
                job_index=job_index,
                num_entries=len(entries),
                num_agents=num_agents,
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

            division_champions = [m for m in ctx.active_memberships if m.division_id == division.id and m.is_champion]
            is_qualifier = qualifier_division is not None and division.id == qualifier_division.id
            is_dirt = self._is_dirt_division(division, config)
            if is_qualifier:
                min_champs = config.qualifiers_minimum_champions
            elif is_dirt:
                min_champs = config.dirt_minimum_champions
            else:
                min_champs = config.minimum_champions
            if len(division_champions) < min_champs:
                continue

            stages = config.dirt_stages if is_dirt else config.stages

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
        return (
            super()
            .describe_division(ctx)
            .model_copy(
                update={
                    "scoring_mechanics": AMONG_THEM_SCORING_MECHANICS,
                }
            )
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
                ranking.result_metadata = {
                    "seed_order": ranking.result_metadata["seed_order"],
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


register_commissioner("auto", BaselineCommissioner)
register_commissioner("manual", ManualCommissioner)
register_commissioner("cogs_vs_clips", CogsVsClipsCommissioner)
register_commissioner("among_them", AmongThemCommissioner)


# ---------------------------------------------------------------------------
# Container protocol adapter
# ---------------------------------------------------------------------------


def _round_start_config(round_start: CommissionerRoundStart) -> dict[str, Any]:
    config = round_start.league.commissioner_config or {}
    state = round_start.state if isinstance(round_start.state, dict) else {}
    round_config = state.get("round_config") if isinstance(state.get("round_config"), dict) else {}
    merged = {**config, **round_config}
    if "minimum_champions" not in merged and round_start.variants:
        merged["minimum_champions"] = round_start.variants[0].num_agents
    return merged


def _current_division(round_start: CommissionerRoundStart) -> DivisionSnapshot:
    config = _round_start_config(round_start)
    configured_division_id = config.get("division_id") or config.get("current_division_id")
    if configured_division_id is not None:
        configured = UUID(str(configured_division_id))
        match = next((division for division in round_start.divisions if division.id == configured), None)
        if match is not None:
            return DivisionSnapshot(
                id=match.id,
                name=match.name,
                level=match.level,
                league_id=round_start.league.id,
            )

    membership_division_ids = {membership.division_id for membership in round_start.memberships}
    if len(membership_division_ids) == 1:
        division_id = next(iter(membership_division_ids))
        match = next((division for division in round_start.divisions if division.id == division_id), None)
        if match is not None:
            return DivisionSnapshot(
                id=match.id,
                name=match.name,
                level=match.level,
                league_id=round_start.league.id,
            )

    if not round_start.divisions:
        raise ValueError("round_start must include at least one division")
    division = min(round_start.divisions, key=lambda candidate: (candidate.level, candidate.name, str(candidate.id)))
    return DivisionSnapshot(
        id=division.id,
        name=division.name,
        level=division.level,
        league_id=round_start.league.id,
    )


def _round_start_stage_config(round_start: CommissionerRoundStart) -> dict[str, Any]:
    config = _round_start_config(round_start)
    stages = config.get("stages")
    if isinstance(stages, list) and stages:
        stage = V2StageConfig.model_validate(stages[0])
        return stage.model_dump(mode="json")
    return {
        "num_episodes": config.get("num_episodes", 1),
        "min_episodes_per_entrant": config.get("min_episodes_per_entrant"),
        "mock_scores": config.get("mock_scores"),
    }


def _round_start_pool(round_start: CommissionerRoundStart) -> PolicyPool:
    stage_config = _round_start_stage_config(round_start)
    return PolicyPool(
        id=round_start.round_id,
        label=str(stage_config.get("label") or "Round"),
        pool_type="round",
        config=stage_config,
    )


def _round_start_entries(round_start: CommissionerRoundStart) -> list[PolicyPoolEntry]:
    division = _current_division(round_start)
    entries: list[PolicyPoolEntry] = []
    seen: set[UUID] = set()
    for membership in round_start.memberships:
        if membership.division_id != division.id or membership.policy_version_id in seen:
            continue
        seen.add(membership.policy_version_id)
        entries.append(
            PolicyPoolEntry(
                pool_id=round_start.round_id,
                policy_version_id=membership.policy_version_id,
                player_id=membership.player_id,
                seed_order=len(entries),
            )
        )
    return entries


def _round_start_variant(round_start: CommissionerRoundStart) -> tuple[str, int]:
    config = _round_start_config(round_start)
    variant_id = str(config.get("variant_id") or (round_start.variants[0].id if round_start.variants else "default"))
    variant = next((candidate for candidate in round_start.variants if candidate.id == variant_id), None)
    if variant is None and round_start.variants:
        variant = round_start.variants[0]
        variant_id = variant.id
    if variant is None:
        return variant_id, len(_round_start_entries(round_start))
    tokens = variant.game_config.get("tokens")
    token_count = len(tokens) if isinstance(tokens, list) else None
    num_agents = variant.num_agents or variant.game_config.get("num_agents") or token_count
    if not isinstance(num_agents, int):
        raise ValueError("round_start variant must include num_agents")
    return variant_id, num_agents


def _round_start_round(round_start: CommissionerRoundStart) -> Round:
    division = _current_division(round_start)
    return Round(
        id=round_start.round_id,
        public_id=str(round_start.round_id),
        division_id=division.id,
        round_number=round_start.round_number,
        commissioner_key=round_start.league.commissioner_key or "container",
        round_config=_round_start_config(round_start),
    )


def _round_start_memberships(round_start: CommissionerRoundStart) -> list[MembershipSnapshot]:
    return [
        MembershipSnapshot(
            id=membership.id,
            league_id=round_start.league.id,
            division_id=membership.division_id,
            policy_version_id=membership.policy_version_id,
            player_id=membership.player_id,
            is_champion=membership.is_champion,
        )
        for membership in round_start.memberships
    ]


def _round_start_divisions(round_start: CommissionerRoundStart) -> list[DivisionSnapshot]:
    return [
        DivisionSnapshot(
            id=division.id,
            name=division.name,
            level=division.level,
            league_id=round_start.league.id,
            type=division.type,
        )
        for division in round_start.divisions
    ]


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _round_snapshot(info: RoundInfo) -> RoundSnapshot:
    return RoundSnapshot(
        id=info.id,
        public_id=info.public_id or str(info.id),
        division_id=info.division_id,
        round_number=info.round_number,
        status=info.status,
        round_config=info.round_config,
        created_at=_parse_datetime(info.created_at) or datetime.now(UTC),
        started_at=_parse_datetime(info.started_at),
        completed_at=_parse_datetime(info.completed_at),
    )


def schedule_episodes_for_round_start(
    commissioner: Commissioner,
    round_start: CommissionerRoundStart,
) -> CommissionerScheduleEpisodes:
    variant_id, num_agents = _round_start_variant(round_start)
    return commissioner.schedule_episodes(
        pool=_round_start_pool(round_start),
        entries=_round_start_entries(round_start),
        num_agents=num_agents,
        variant_id=variant_id,
    )


def _protocol_round_spec(spec: RoundSpec) -> CommissionerRoundSpec:
    return CommissionerRoundSpec.model_validate(spec.model_dump(mode="json"))


def _protocol_leaderboard_entry(entry: DivisionLeaderboardSnapshot) -> CommissionerDivisionLeaderboardEntry:
    return CommissionerDivisionLeaderboardEntry.model_validate(entry.model_dump(mode="json"))


def _protocol_division_description(
    description: DivisionCommissionerDescriptionPublic,
) -> CommissionerDivisionDescription:
    return CommissionerDivisionDescription.model_validate(description.model_dump(mode="json"))


def _protocol_membership_change(change: MembershipChange) -> CommissionerMembershipChange:
    return CommissionerMembershipChange.model_validate(change.model_dump(mode="json"))


def complete_round_for_round_start(
    commissioner: Commissioner,
    round_start: CommissionerRoundStart,
    episode_results: list[CommissionerProtocolEpisodeResult],
) -> CommissionerRoundComplete:
    local_episode_results = [
        EpisodeResult(
            episode_request_id=UUID(int=index + 1),
            scores=[
                RoundPolicyScore(
                    policy_version_id=score.policy_version_id,
                    player_id=score.player_id,
                    score=score.score,
                )
                for score in result.scores
            ],
            game_results=result.game_results,
        )
        for index, result in enumerate(episode_results)
    ]
    round_row = _round_start_round(round_start)
    pool = _round_start_pool(round_start)
    entries = _round_start_entries(round_start)
    complete = commissioner.complete_round(
        round_row=round_row,
        pool=pool,
        entries=entries,
        episode_results=local_episode_results,
    )
    hook_result = commissioner.on_round_completed(
        OnRoundCompletedContext(
            league=LeagueSnapshot(
                id=round_start.league.id,
                commissioner_key=round_start.league.commissioner_key or "container",
                commissioner_config=_round_start_config(round_start),
            ),
            division=_current_division(round_start),
            all_divisions=_round_start_divisions(round_start),
            round_config=V2RoundConfig.model_validate(_round_start_config(round_start)),
            round_results=[
                RoundResultSnapshot(
                    round_id=round_start.round_id,
                    policy_version_id=ranking.policy_version_id,
                    rank=ranking.rank,
                    score=ranking.score,
                    result_metadata=ranking.result_metadata,
                )
                for division_ranking in complete.results
                for ranking in division_ranking.rankings
            ],
            division_memberships=_round_start_memberships(round_start),
            recent_results=[],
            commissioner_config=_round_start_config(round_start),
        )
    )
    complete.membership_changes = [_protocol_membership_change(change) for change in hook_result.membership_changes]
    complete.graduation_changes = [
        CommissionerGraduationChange(
            membership_id=change.membership_id,
            to_division_id=change.to_division_id,
            reason=change.reason,
        )
        for change in hook_result.membership_changes
        if change.to_division_id is not None
    ]
    return complete


def schedule_rounds_for_request(
    commissioner: Commissioner,
    request: ScheduleRoundsRequest,
) -> ScheduleRoundsResponse:
    specs = commissioner.schedule_rounds(
        ScheduleContext(
            league=LeagueSnapshot(
                id=request.league.id,
                commissioner_key=request.league.commissioner_key or "container",
                commissioner_config=request.league.commissioner_config,
            ),
            divisions=[
                DivisionSnapshot(
                    id=division.id,
                    name=division.name,
                    level=division.level,
                    league_id=request.league.id,
                    type=division.type,
                )
                for division in request.divisions
            ],
            active_memberships=[
                MembershipSnapshot(
                    id=membership.id,
                    league_id=request.league.id,
                    division_id=membership.division_id,
                    policy_version_id=membership.policy_version_id,
                    player_id=membership.player_id,
                    is_champion=membership.is_champion,
                )
                for membership in request.active_memberships
            ],
            recent_rounds=[_round_snapshot(round_info) for round_info in request.recent_rounds],
        )
    )
    return ScheduleRoundsResponse(rounds=[_protocol_round_spec(spec) for spec in specs])


def rank_division_for_request(
    commissioner: Commissioner,
    request: RankDivisionRequest,
) -> RankDivisionResponse:
    rankings = commissioner.rank_division(
        DivisionLeaderboardContext(
            league=LeagueSnapshot(
                id=request.league.id,
                commissioner_key=request.league.commissioner_key or "container",
                commissioner_config=request.league.commissioner_config,
            ),
            division=DivisionSnapshot(
                id=request.division.id,
                name=request.division.name,
                level=request.division.level,
                league_id=request.league.id,
                type=request.division.type,
            ),
            completed_rounds=[_round_snapshot(round_info) for round_info in request.completed_rounds],
            recent_rounds=[_round_snapshot(round_info) for round_info in request.recent_rounds],
            round_results=[
                LeaderboardRoundResultSnapshot(
                    round_id=result.round_id,
                    policy_version_id=result.policy_version_id,
                    rank=result.rank,
                    score=result.score,
                    result_metadata=result.result_metadata,
                    player_id=result.player_id,
                    player_name=result.player_name,
                )
                for result in request.round_results
            ],
        )
    )
    return RankDivisionResponse(rankings=[_protocol_leaderboard_entry(ranking) for ranking in rankings])


def describe_division_for_request(
    commissioner: Commissioner,
    request: DescribeDivisionRequest,
) -> DescribeDivisionResponse:
    description = commissioner.describe_division(
        DivisionDescriptionContext(
            league=LeagueSnapshot(
                id=request.league.id,
                commissioner_key=request.league.commissioner_key or "container",
                commissioner_config=request.league.commissioner_config,
            ),
            division=DivisionSnapshot(
                id=request.division.id,
                name=request.division.name,
                level=request.division.level,
                league_id=request.league.id,
                type=request.division.type,
            ),
            active_memberships=[
                MembershipSnapshot(
                    id=membership.id,
                    league_id=request.league.id,
                    division_id=membership.division_id,
                    policy_version_id=membership.policy_version_id,
                    player_id=membership.player_id,
                    is_champion=membership.is_champion,
                )
                for membership in request.active_memberships
            ],
            recent_rounds=[_round_snapshot(round_info) for round_info in request.recent_rounds],
        )
    )
    return DescribeDivisionResponse(description=_protocol_division_description(description))


def round_completed_for_request(
    commissioner: Commissioner,
    request: RoundCompletedRequest,
) -> RoundCompletedResponse:
    result = commissioner.on_round_completed(
        OnRoundCompletedContext(
            league=LeagueSnapshot(
                id=request.league.id,
                commissioner_key=request.league.commissioner_key or "container",
                commissioner_config=request.league.commissioner_config,
            ),
            division=DivisionSnapshot(
                id=request.division.id,
                name=request.division.name,
                level=request.division.level,
                league_id=request.league.id,
                type=request.division.type,
            ),
            all_divisions=[
                DivisionSnapshot(
                    id=division.id,
                    name=division.name,
                    level=division.level,
                    league_id=request.league.id,
                    type=division.type,
                )
                for division in request.all_divisions
            ],
            round_config=V2RoundConfig.model_validate(request.round_config.model_dump(mode="json")),
            round_results=[
                RoundResultSnapshot(
                    round_id=round_result.round_id,
                    policy_version_id=round_result.policy_version_id,
                    rank=round_result.rank,
                    score=round_result.score,
                    result_metadata=round_result.result_metadata,
                )
                for round_result in request.round_results
            ],
            division_memberships=[
                MembershipSnapshot(
                    id=membership.id,
                    league_id=request.league.id,
                    division_id=membership.division_id,
                    policy_version_id=membership.policy_version_id,
                    player_id=membership.player_id,
                    is_champion=membership.is_champion,
                )
                for membership in request.division_memberships
            ],
            recent_results=[
                RoundResultSnapshot(
                    round_id=round_result.round_id,
                    policy_version_id=round_result.policy_version_id,
                    rank=round_result.rank,
                    score=round_result.score,
                    result_metadata=round_result.result_metadata,
                )
                for round_result in request.recent_results
            ],
            commissioner_config=request.commissioner_config,
        )
    )
    return RoundCompletedResponse(
        membership_changes=[_protocol_membership_change(change) for change in result.membership_changes],
        follow_up_rounds=[_protocol_round_spec(round_spec) for round_spec in result.follow_up_rounds],
    )
