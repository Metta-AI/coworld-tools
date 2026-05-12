#!/usr/bin/env python3
"""Post-process cogames run JSON output with derived observability metrics.

This script wraps ``cogames run --format json`` output and computes metrics
that the core eval pipeline does not provide, including:

- Per-policy reward variance, std-dev, min, max, and confidence intervals
- Win-rate estimation (fraction of episodes where a policy has highest reward)
- Cross-mission composite scores (mean-of-means across missions)

Usage:

  # Pipe eval output directly:
  cogames run -m arena -p role --format json | python enrich_eval_output.py

  # Or from a saved file:
  cogames run -m arena -p role --format json > eval.json
  python enrich_eval_output.py --input eval.json

  # Save enriched output:
  python enrich_eval_output.py --input eval.json --output enriched.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any


def _compute_reward_stats(
    per_episode_per_policy_avg_rewards: dict[str, list[float | None]],
    num_policies: int,
) -> list[dict[str, Any]]:
    """Compute per-policy reward distribution statistics."""
    policy_rewards: list[list[float]] = [[] for _ in range(num_policies)]

    for _ep_idx, rewards in per_episode_per_policy_avg_rewards.items():
        for policy_idx, reward in enumerate(rewards):
            if reward is not None:
                policy_rewards[policy_idx].append(reward)

    stats = []
    for policy_idx in range(num_policies):
        values = policy_rewards[policy_idx]
        if not values:
            stats.append(
                {
                    "episodes_with_data": 0,
                    "mean": None,
                    "std": None,
                    "min": None,
                    "max": None,
                    "ci_95_lower": None,
                    "ci_95_upper": None,
                }
            )
            continue

        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
        std = math.sqrt(variance)
        se = std / math.sqrt(n) if n > 0 else 0.0
        ci_95 = 1.96 * se

        stats.append(
            {
                "episodes_with_data": n,
                "mean": round(mean, 4),
                "std": round(std, 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "ci_95_lower": round(mean - ci_95, 4),
                "ci_95_upper": round(mean + ci_95, 4),
            }
        )

    return stats


def _compute_win_rates(
    per_episode_per_policy_avg_rewards: dict[str, list[float | None]],
    num_policies: int,
) -> list[dict[str, Any]]:
    """Compute per-policy win rates (fraction of episodes with highest reward)."""
    wins = [0] * num_policies
    ties = [0] * num_policies
    total_episodes = 0

    for _ep_idx, rewards in per_episode_per_policy_avg_rewards.items():
        valid_rewards = [(i, r) for i, r in enumerate(rewards) if r is not None]
        if not valid_rewards:
            continue

        total_episodes += 1
        max_reward = max(r for _, r in valid_rewards)
        winners = [i for i, r in valid_rewards if r == max_reward]

        if len(winners) == 1:
            wins[winners[0]] += 1
        else:
            for w in winners:
                ties[w] += 1

    results = []
    for policy_idx in range(num_policies):
        results.append(
            {
                "wins": wins[policy_idx],
                "ties": ties[policy_idx],
                "losses": total_episodes - wins[policy_idx] - ties[policy_idx],
                "win_rate": round(wins[policy_idx] / total_episodes, 4) if total_episodes else None,
                "win_or_tie_rate": round((wins[policy_idx] + ties[policy_idx]) / total_episodes, 4)
                if total_episodes
                else None,
                "total_episodes": total_episodes,
            }
        )

    return results


def enrich_mission(mission_data: dict[str, Any]) -> dict[str, Any]:
    """Add derived metrics to a single mission's eval output."""
    summary = mission_data["mission_summary"]
    num_policies = len(summary["policy_summaries"])
    rewards_map = summary.get("per_episode_per_policy_avg_rewards", {})

    enriched = dict(mission_data)
    enriched["derived_metrics"] = {
        "reward_statistics": _compute_reward_stats(rewards_map, num_policies),
        "win_rates": _compute_win_rates(rewards_map, num_policies),
    }

    return enriched


def compute_composite_scores(
    enriched_missions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute cross-mission composite scores per policy.

    Returns a list of per-policy dicts with mean-of-means across missions.
    """
    if not enriched_missions:
        return []

    num_policies = len(enriched_missions[0]["mission_summary"]["policy_summaries"])
    policy_means: list[list[float]] = [[] for _ in range(num_policies)]

    for mission in enriched_missions:
        for policy_idx, stats in enumerate(mission["derived_metrics"]["reward_statistics"]):
            if stats["mean"] is not None:
                policy_means[policy_idx].append(stats["mean"])

    composites = []
    for policy_idx in range(num_policies):
        means = policy_means[policy_idx]
        if not means:
            composites.append(
                {
                    "composite_mean": None,
                    "missions_counted": 0,
                }
            )
        else:
            composites.append(
                {
                    "composite_mean": round(sum(means) / len(means), 4),
                    "missions_counted": len(means),
                }
            )

    return composites


def enrich(eval_output: dict[str, Any]) -> dict[str, Any]:
    """Enrich full eval JSON output with derived metrics."""
    missions = eval_output.get("missions", [])
    enriched_missions = [enrich_mission(m) for m in missions]

    result = dict(eval_output)
    result["missions"] = enriched_missions
    result["composite_scores"] = compute_composite_scores(enriched_missions)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        "-i",
        help="Path to eval JSON file (default: stdin)",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Path to write enriched JSON (default: stdout)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: true)",
    )
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    enriched = enrich(data)

    indent = 2 if args.pretty else None
    output_str = json.dumps(enriched, indent=indent)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_str)
            f.write("\n")
    else:
        print(output_str)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
