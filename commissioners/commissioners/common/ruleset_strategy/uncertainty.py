from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Any
from uuid import UUID

from commissioners.common.ruleset_strategy.config import AdaptiveScheduleConfig

# Trend compares the mean of the last TREND_WINDOW_ROUNDS round scores against the mean
# of the TREND_WINDOW_ROUNDS before those, so it needs 2x this many rounds on record.
TREND_WINDOW_ROUNDS = 3


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


def entrant_uncertainties(
    policy_version_ids: list[UUID],
    recent_results: list[Any],
    config: AdaptiveScheduleConfig,
) -> dict[UUID, EntrantUncertainty]:
    """Per-entrant uncertainty in [0, 1] from recent round-score history.

    History is keyed by policy version, so a freshly promoted champion is fully
    uncertain even though its player has board history. Three signals, combined
    with max: newness (few rounds on record for this version), volatility (std of
    recent round scores), and trend (recent mean shifted vs the prior window,
    catching same-version entrants whose true strength moved when the game or the
    field changed around them).
    """
    scores_by_round: dict[UUID, dict[Any, tuple[int, float]]] = defaultdict(dict)
    for result in recent_results:
        policy_version_id = result.policy_version_id
        scores_by_round[policy_version_id][result.round_id] = (
            getattr(result, "round_number", 0),
            result.score,
        )

    uncertainties: dict[UUID, EntrantUncertainty] = {}
    for policy_version_id in policy_version_ids:
        rows = sorted(scores_by_round.get(policy_version_id, {}).values())
        scores = [score for _, score in rows]
        rounds_on_record = len(scores)
        newness = _clamp01(1.0 - rounds_on_record / config.settle_rounds)
        window = scores[-config.volatility_rounds :]
        volatility = _clamp01(pstdev(window) / config.volatility_scale) if len(window) >= 3 else 0.0
        trend = 0.0
        if rounds_on_record >= 2 * TREND_WINDOW_ROUNDS:
            recent_mean = fmean(scores[-TREND_WINDOW_ROUNDS:])
            prior_mean = fmean(scores[-2 * TREND_WINDOW_ROUNDS : -TREND_WINDOW_ROUNDS])
            trend = _clamp01(abs(recent_mean - prior_mean) / config.trend_scale)
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
