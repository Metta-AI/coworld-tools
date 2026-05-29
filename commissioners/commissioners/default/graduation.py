"""Graduation strategies: moving memberships between divisions after a round.

A graduation strategy reads a division's final rankings and returns
`graduation_changes` entries for the `round_complete` message. Each change names
a `membership_id`, the `to_division_id` it should move to, and a human-readable
`reason`. See the commissioner protocol and the round-decisions artifact:
https://github.com/Metta-AI/coworld/blob/main/src/coworld/commissioner/protocol.py
https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/artifacts/ROUND_DECISIONS.md
"""

from __future__ import annotations

import math
from typing import Any


def percentile_graduation(
    rankings: list[dict[str, Any]],
    *,
    memberships: list[dict[str, Any]],
    divisions: list[dict[str, Any]],
    current_division_id: str,
    promote_top_pct: int = 0,
    relegate_bottom_pct: int = 0,
) -> list[dict[str, Any]]:
    """Promote the top N% to the next-higher division, relegate the bottom N%.

    Divisions are ordered by their integer `level`; "higher" means `level + 1`
    and "lower" means `level - 1`. Promotion/relegation only happens when an
    adjacent division actually exists. At least one policy moves whenever the
    relevant percentage is positive and the division is non-empty.

    Args:
        rankings: This division's rankings, best-first, each with
            `policy_version_id`.
        memberships: All league memberships; each has `id`, `policy_version_id`,
            and `division_id`.
        divisions: All divisions; each has `id`, `name`, and `level`.
        current_division_id: The division `rankings` belongs to.
        promote_top_pct: Percent of the top of the ranking to promote (0-100).
        relegate_bottom_pct: Percent of the bottom to relegate (0-100).

    Returns:
        A list of graduation-change dicts for `round_complete`.
    """
    if not rankings:
        return []

    division_by_id = {d["id"]: d for d in divisions}
    current_level = division_by_id[current_division_id]["level"]

    higher_division = next((d for d in divisions if d["level"] == current_level + 1), None)
    lower_division = next((d for d in divisions if d["level"] == current_level - 1), None)

    # Only memberships sitting in this division are eligible to move.
    membership_by_policy = {
        m["policy_version_id"]: m for m in memberships if m["division_id"] == current_division_id
    }

    changes: list[dict[str, Any]] = []
    n = len(rankings)

    if promote_top_pct > 0 and higher_division is not None:
        num_promote = max(1, math.floor(n * promote_top_pct / 100))
        for ranking in rankings[:num_promote]:
            membership = membership_by_policy.get(ranking["policy_version_id"])
            if membership is not None:
                changes.append(
                    {
                        "membership_id": membership["id"],
                        "to_division_id": higher_division["id"],
                        "reason": f"promoted (top {promote_top_pct}%)",
                    }
                )

    if relegate_bottom_pct > 0 and lower_division is not None:
        num_relegate = max(1, math.floor(n * relegate_bottom_pct / 100))
        for ranking in rankings[-num_relegate:]:
            membership = membership_by_policy.get(ranking["policy_version_id"])
            if membership is not None:
                changes.append(
                    {
                        "membership_id": membership["id"],
                        "to_division_id": lower_division["id"],
                        "reason": f"relegated (bottom {relegate_bottom_pct}%)",
                    }
                )

    return changes
