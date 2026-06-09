from __future__ import annotations

from commissioners.common.models import PolicyPool, PolicyPoolEntry, PoolConfig
from commissioners.common.protocol import EpisodeRequest as CommissionerEpisodeRequest
from commissioners.common.protocol import ScheduleEpisodes as CommissionerScheduleEpisodes
from commissioners.common.utils import (
    _build_entry_indices,
    _build_rolling_window_entry_indices,
    _entry_index_offset,
    _pool_episode_count,
)
from commissioners.common.ruleset_strategy.config import RulesetStrategyCommissionerConfig


def schedule_entries(
    *,
    pool: PolicyPool,
    primary_entries: list[PolicyPoolEntry],
    filler_entries: list[PolicyPoolEntry],
    num_agents: int,
    variant_id: str,
    config: RulesetStrategyCommissionerConfig,
) -> CommissionerScheduleEpisodes:
    if not primary_entries:
        raise ValueError("pool must have at least one primary entry")
    pool_config = PoolConfig.model_validate(pool.config)
    if pool_config.self_play:
        episodes_per_entrant = pool_config.min_episodes_per_entrant or pool_config.num_episodes
        return CommissionerScheduleEpisodes(
            episodes=[
                CommissionerEpisodeRequest(
                    request_id=str(entry_index * episodes_per_entrant + episode_index),
                    variant_id=variant_id,
                    policy_version_ids=[entry.policy_version_id] * num_agents,
                    tags={"pool_id": str(pool.id)},
                )
                for entry_index, entry in enumerate(primary_entries)
                for episode_index in range(episodes_per_entrant)
            ]
        )

    if config.seating == "team_blocks":
        team_count = config.defaults.team_count
        if len(primary_entries) < team_count:
            raise ValueError(f"team_blocks seating requires at least {team_count} primary entries")
        if num_agents % team_count != 0:
            raise ValueError(f"team_blocks seating requires num_agents divisible by {team_count}")

        team_size = num_agents // team_count
        num_episodes = _pool_episode_count(
            config=pool_config,
            num_entries=len(primary_entries),
            num_agents=team_count,
        )
        episodes: list[CommissionerEpisodeRequest] = []
        for job_index in range(num_episodes):
            entry_indices = [
                (job_index * team_count + team_index) % len(primary_entries) for team_index in range(team_count)
            ]
            rotation = job_index % team_count
            entry_indices = entry_indices[rotation:] + entry_indices[:rotation]
            episodes.append(
                CommissionerEpisodeRequest(
                    request_id=str(job_index),
                    variant_id=variant_id,
                    policy_version_ids=[
                        primary_entries[entry_index].policy_version_id
                        for entry_index in entry_indices
                        for _slot in range(team_size)
                    ],
                    tags={"pool_id": str(pool.id)},
                )
            )
        return CommissionerScheduleEpisodes(episodes=episodes)

    num_episodes = _pool_episode_count(
        config=pool_config,
        num_entries=len(primary_entries),
        num_agents=num_agents,
    )
    return CommissionerScheduleEpisodes(
        episodes=[
            CommissionerEpisodeRequest(
                request_id=str(job_index),
                variant_id=variant_id,
                policy_version_ids=[
                    entry.policy_version_id
                    for entry in episode_entries(
                        job_index,
                        primary_entries=primary_entries,
                        filler_entries=filler_entries,
                        num_agents=num_agents,
                        config=config,
                    )
                ],
                tags={"pool_id": str(pool.id)},
            )
            for job_index in range(num_episodes)
        ]
    )


def episode_entries(
    job_index: int,
    *,
    primary_entries: list[PolicyPoolEntry],
    filler_entries: list[PolicyPoolEntry],
    num_agents: int,
    config: RulesetStrategyCommissionerConfig,
) -> list[PolicyPoolEntry]:
    if len(primary_entries) >= num_agents:
        if config.seating == "baseline_window":
            indices = _build_entry_indices(
                num_entries=len(primary_entries),
                num_agents=num_agents,
                offset=_entry_index_offset(
                    job_index=job_index,
                    num_entries=len(primary_entries),
                    num_agents=num_agents,
                ),
            )
        else:
            indices = _build_rolling_window_entry_indices(
                job_index=job_index,
                num_entries=len(primary_entries),
                num_agents=num_agents,
            )
        return [primary_entries[index] for index in indices]

    seats = list(primary_entries)
    if config.insufficient_players.strategy == "strict":
        raise ValueError(f"not enough primary entries to fill {num_agents} seats")
    if config.insufficient_players.strategy == "fill_from_divisions":
        seats.extend(cycled(filler_entries, num_agents - len(seats), offset=job_index))
    if len(seats) < num_agents and config.insufficient_players.duplicate_after_fill:
        seats.extend(cycled(seats or primary_entries, num_agents - len(seats), offset=job_index))
    if len(seats) < num_agents:
        raise ValueError(f"not enough entries to fill {num_agents} seats")
    return seats[:num_agents]


def cycled(entries: list[PolicyPoolEntry], count: int, *, offset: int = 0) -> list[PolicyPoolEntry]:
    if count <= 0 or not entries:
        return []
    return [entries[(offset + index) % len(entries)] for index in range(count)]
