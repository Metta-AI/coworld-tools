from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class CogsguardGameStats(BaseModel):
    aligned_junction_held: float | None = Field(default=None, alias="cogs/aligned.junction.held")
    aligned_junction_gained: float | None = Field(default=None, alias="cogs/aligned.junction.gained")


class CogsguardAgentMetrics(BaseModel):
    heart_gained: float | None = Field(default=None, alias="heart.gained")
    heart_lost: float | None = Field(default=None, alias="heart.lost")
    reward: float | None = None


class CogsguardPolicySummary(BaseModel):
    avg_agent_metrics: CogsguardAgentMetrics = Field(default_factory=CogsguardAgentMetrics)
    action_timeouts: float | None = None


class CogsguardMissionSummary(BaseModel):
    policy_summaries: list[CogsguardPolicySummary]
    avg_game_stats: CogsguardGameStats = Field(default_factory=CogsguardGameStats)
    per_episode_per_policy_avg_rewards: dict[str, list[float | None]] = Field(default_factory=dict)


class CogsguardMissionResult(BaseModel):
    mission_summary: CogsguardMissionSummary


class CogsguardEvalResult(BaseModel):
    missions: list[CogsguardMissionResult]


def parse_eval_result_text(text: str) -> dict[str, Any]:
    json_start = text.find("{")
    data = json.loads(text[json_start:] if json_start >= 0 else text)
    return data if isinstance(data, dict) else {}


def extract_cogsguard_eval_metrics(result_data: dict[str, Any]) -> dict[str, float | None]:
    summary = CogsguardEvalResult.model_validate(result_data).missions[0].mission_summary
    policy_summary = summary.policy_summaries[0]
    game_stats = summary.avg_game_stats
    agent_metrics = policy_summary.avg_agent_metrics
    reward_values = [
        episode_rewards[0]
        for episode_rewards in summary.per_episode_per_policy_avg_rewards.values()
        if episode_rewards[0] is not None
    ]
    reward = sum(reward_values) / len(reward_values) if reward_values else agent_metrics.reward

    return {
        "aligned.junction.held": 0.0 if game_stats.aligned_junction_held is None else game_stats.aligned_junction_held,
        "aligned.junction.gained": 0.0
        if game_stats.aligned_junction_gained is None
        else game_stats.aligned_junction_gained,
        "heart.gained": agent_metrics.heart_gained,
        "heart.lost": agent_metrics.heart_lost,
        "reward": reward,
        "action_timeouts": policy_summary.action_timeouts,
    }
