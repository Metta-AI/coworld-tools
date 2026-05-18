from __future__ import annotations

from collections import defaultdict
from typing import Iterable


def summarize_role_counts(
    role_counts_history: list[dict[str, int]],
    roles: Iterable[str],
) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    total_steps = max(len(role_counts_history), 1)
    for role in roles:
        counts = [counts_map.get(role, 0) for counts_map in role_counts_history]
        summary[role] = {
            "min": min(counts) if counts else 0,
            "max": max(counts) if counts else 0,
            "avg": sum(counts) / total_steps,
        }
    return summary


def count_steps_with_roles(
    role_counts_history: list[dict[str, int]],
    required_roles: Iterable[str],
) -> int:
    required = list(required_roles)
    return sum(1 for counts_map in role_counts_history if all(counts_map.get(role, 0) > 0 for role in required))


def count_role_transitions(
    transitions: list[tuple[str, str]],
) -> dict[tuple[str, str], int]:
    transition_counts: dict[tuple[str, str], int] = defaultdict(int)
    for prev_role, next_role in transitions:
        transition_counts[(prev_role, next_role)] += 1
    return dict(transition_counts)


def format_role_trace_line(
    *,
    step: int,
    role_counts: dict[str, int],
    roles: Iterable[str],
    transitions: int,
) -> str:
    role_list = list(roles)
    counts_str = " ".join(f"{role}={role_counts.get(role, 0)}" for role in role_list)
    present_str = ",".join(role for role in role_list if role_counts.get(role, 0) > 0) or "-"
    return f"step={step} roles[{counts_str}] present[{present_str}] transitions={transitions}"
