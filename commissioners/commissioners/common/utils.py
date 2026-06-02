from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any
from uuid import UUID

from commissioners.common.models import (
    DIVISION_LEADERBOARD_SCORE_EWMA_HALFLIFE,
    DIVISION_TYPE_STAGING,
    DEFAULT_STAGES,
    DivisionSnapshot,
    EpisodeResult,
    MembershipChange,
    MembershipSnapshot,
    OnRoundCompletedContext,
    PoolConfig,
    RoundSchedulingConfig,
    V2StageConfig,
)

DIVISION_LEADERBOARD_SCORE_EWMA_HALFLIFE_HOURS = 2
AMONG_THEM_RESULT_METADATA_VERSION = 2
AMONG_THEM_SCORE_KIND = "mean_round_score"
COMPLETED_EPISODE_COUNT_METADATA_KEY = "completed_episode_count"
AMONG_THEM_SCORING_MECHANICS = (
    "Among Them rounds rank policies by the average score reported by the game across each policy's episode slots. "
    "The division leaderboard only uses current average-score round results and combines completed rounds with a "
    "2-hour half-life EWMA, so newer rounds count more than older rounds."
)


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
    from commissioners.common.models import DIVISION_TYPE_STAGING
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
    from commissioners.common.models import DIVISION_TYPE_COMPETITION
    config = commissioner_config or {}
    return select_division(
        divisions,
        division_name=config.get("default_division_name"),
        division_type=DIVISION_TYPE_COMPETITION,
        fallback_to_lowest=True,
    )


def division_entrants(
    memberships: list[MembershipSnapshot],
    division: DivisionSnapshot,
    *,
    is_qualifier: bool,
) -> list[MembershipSnapshot]:
    return [
        membership
        for membership in memberships
        if membership.division_id == division.id and (is_qualifier or membership.is_champion)
    ]


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
    qualified_policy_ids = {
        result.policy_version_id
        for result in ctx.round_results
        if result.result_metadata[COMPLETED_EPISODE_COUNT_METADATA_KEY] > 0
    }
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
