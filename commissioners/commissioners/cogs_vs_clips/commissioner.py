from __future__ import annotations

from commissioners.common.commissioners import BaselineCommissioner
from commissioners.common.models import (
    PolicyPool,
    PolicyPoolEntry,
    PoolConfig,
)
from commissioners.common.protocol import (
    EpisodeRequest as CommissionerEpisodeRequest,
)
from commissioners.common.protocol import (
    ScheduleEpisodes as CommissionerScheduleEpisodes,
)
from commissioners.common.utils import (
    _build_rolling_window_entry_indices,
    _pool_episode_count,
)


class CogsVsClipsCommissioner(BaselineCommissioner):
    """Cogs vs Clips rolling-window scheduling with baseline mean-score ranking."""

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
            episodes_per_entrant = config.min_episodes_per_entrant or config.num_episodes
            return CommissionerScheduleEpisodes(
                episodes=[
                    CommissionerEpisodeRequest(
                        request_id=str(entry_index * episodes_per_entrant + episode_index),
                        variant_id=variant_id,
                        policy_version_ids=[entry.policy_version_id] * num_agents,
                        tags={"pool_id": str(pool.id)},
                    )
                    for entry_index, entry in enumerate(entries)
                    for episode_index in range(episodes_per_entrant)
                ]
            )

        num_episodes = _pool_episode_count(
            config=config,
            num_entries=len(entries),
            num_agents=num_agents,
        )
        episodes: list[CommissionerEpisodeRequest] = []
        for job_index in range(num_episodes):
            entry_indices = _build_rolling_window_entry_indices(
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
