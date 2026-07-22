from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt
from statistics import fmean, pstdev
from typing import Any
from uuid import UUID

from commissioners.common.ruleset_strategy.config import AdaptiveScheduleConfig

# Trend compares the mean of the last TREND_WINDOW_ROUNDS round scores against the mean
# of the TREND_WINDOW_ROUNDS before those, so it needs 2x this many rounds on record.
TREND_WINDOW_ROUNDS = 3

COMPLETED_EPISODE_COUNT_KEY = "completed_episode_count"


@dataclass(frozen=True)
class EntrantUncertainty:
    rounds_on_record: int
    newness: float
    volatility: float
    trend: float

    @property
    def value(self) -> float:
        return max(self.newness, self.volatility, self.trend)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _round_episode_count(result: Any, fallback: int) -> int:
    metadata = getattr(result, "result_metadata", None)
    if isinstance(metadata, dict):
        count = metadata.get(COMPLETED_EPISODE_COUNT_KEY)
        if isinstance(count, (int, float)) and count > 0:
            return int(count)
    return fallback


def _sampling_noise_std(scores: list[float], episode_counts: list[int]) -> float:
    """Std-dev a stable policy's round win rates would show from sampling alone.

    Round scores here are win rates over a handful of episodes, so even a policy of
    perfectly constant true strength p shows per-round std ~ sqrt(p*(1-p)/n) — at
    p=0.5 over 10 episodes that's ~0.16, larger than any volatility scale we'd want
    to rank real movement with. Signals must measure the excess over this floor or
    a stable mid-field policy reads as fully volatile forever.
    """
    p = _clamp01(fmean(scores))
    n = max(1.0, fmean(episode_counts))
    return sqrt(p * (1.0 - p) / n)


def entrant_uncertainties(
    policy_version_ids: list[UUID],
    recent_results: list[Any],
    config: AdaptiveScheduleConfig,
    *,
    fallback_episodes_per_round: int = 4,
) -> dict[UUID, EntrantUncertainty]:
    """Per-entrant uncertainty in [0, 1] from recent round-score history.

    History is keyed by policy version, so a freshly promoted champion is fully
    uncertain even though its player has board history. Three signals, combined
    with max: newness (few rounds on record for this version), volatility (std of
    recent round scores in excess of the sampling-noise floor), and trend (recent
    mean shifted vs the prior window beyond noise, catching same-version entrants
    whose true strength moved when the game or the field changed around them).
    """
    rows_by_policy: dict[UUID, dict[Any, tuple[int, float, int]]] = defaultdict(dict)
    for result in recent_results:
        rows_by_policy[result.policy_version_id][result.round_id] = (
            getattr(result, "round_number", 0),
            result.score,
            _round_episode_count(result, fallback_episodes_per_round),
        )

    uncertainties: dict[UUID, EntrantUncertainty] = {}
    for policy_version_id in policy_version_ids:
        rows = sorted(rows_by_policy.get(policy_version_id, {}).values())
        scores = [score for _, score, _ in rows]
        episode_counts = [count for _, _, count in rows]
        rounds_on_record = len(scores)
        newness = _clamp01(1.0 - rounds_on_record / config.settle_rounds)

        volatility = 0.0
        window = scores[-config.volatility_rounds :]
        if len(window) >= 3:
            noise_std = _sampling_noise_std(window, episode_counts[-config.volatility_rounds :])
            # Quadrature subtraction: observed variance = true variance + noise variance.
            excess_std = sqrt(max(0.0, pstdev(window) ** 2 - noise_std**2))
            volatility = _clamp01(excess_std / config.volatility_scale)

        trend = 0.0
        if rounds_on_record >= 2 * TREND_WINDOW_ROUNDS:
            trend_scores = scores[-2 * TREND_WINDOW_ROUNDS :]
            recent_mean = fmean(trend_scores[TREND_WINDOW_ROUNDS:])
            prior_mean = fmean(trend_scores[:TREND_WINDOW_ROUNDS])
            noise_std = _sampling_noise_std(trend_scores, episode_counts[-2 * TREND_WINDOW_ROUNDS :])
            # Std of the difference of two TREND_WINDOW_ROUNDS-round means under a
            # stable policy; shifts inside one noise-std of that are not evidence.
            delta_noise_std = noise_std * sqrt(2.0 / TREND_WINDOW_ROUNDS)
            excess_shift = max(0.0, abs(recent_mean - prior_mean) - delta_noise_std)
            trend = _clamp01(excess_shift / config.trend_scale)

        uncertainties[policy_version_id] = EntrantUncertainty(
            rounds_on_record=rounds_on_record,
            newness=newness,
            volatility=volatility,
            trend=trend,
        )
    return uncertainties


def episode_budget(uncertainty: float, *, min_episodes: int, max_episodes: int) -> int:
    max_episodes = max(max_episodes, min_episodes)
    return min_episodes + round(_clamp01(uncertainty) * (max_episodes - min_episodes))
