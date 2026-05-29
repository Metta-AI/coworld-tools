"""Matchup-generation strategies for the default commissioner.

A strategy turns the set of policy versions in a division into a list of
episode requests (the `schedule_episodes.episodes` payload). See the
commissioner protocol for the exact shape of an episode request:
https://github.com/Metta-AI/coworld/blob/main/src/coworld/commissioner/protocol.py
"""

from __future__ import annotations

import itertools
import uuid
from typing import Any


def round_robin_matchups(
    policy_version_ids: list[str],
    *,
    variant_id: str,
    num_agents: int,
    episodes_per_pair: int = 1,
    seed_base: int = 0,
) -> list[dict[str, Any]]:
    """Generate round-robin matchups over all size-`num_agents` combinations.

    Every unordered combination of `num_agents` distinct policies plays
    `episodes_per_pair` episodes. Each episode is one entry in a
    `schedule_episodes` message: a commissioner-generated `request_id`, the
    chosen `variant_id`, the ordered `policy_version_ids` for the slots, a
    `seed`, and free-form `tags`.

    Args:
        policy_version_ids: Policy versions competing in this division.
        variant_id: The variant these episodes run under.
        num_agents: Player slots per episode (from the variant's token count).
        episodes_per_pair: Episodes scheduled per combination.
        seed_base: Starting seed; incremented per scheduled episode so repeated
            matchups are reproducible but distinct.

    Returns:
        A list of episode-request dicts ready to put in `schedule_episodes`.
    """
    if num_agents < 1:
        raise ValueError(f"num_agents must be >= 1, got {num_agents}")
    if len(policy_version_ids) < num_agents:
        return []

    episodes: list[dict[str, Any]] = []
    seed = seed_base

    for combo in itertools.combinations(policy_version_ids, num_agents):
        for _ in range(episodes_per_pair):
            episodes.append(
                {
                    "request_id": str(uuid.uuid4()),
                    "variant_id": variant_id,
                    "policy_version_ids": list(combo),
                    "seed": seed,
                    "tags": {},
                }
            )
            seed += 1

    return episodes
