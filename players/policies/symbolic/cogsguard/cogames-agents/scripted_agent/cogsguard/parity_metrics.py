from __future__ import annotations

from collections import Counter


def update_action_counts(counts: Counter[str], action_name: str) -> None:
    counts[action_name] += 1


def update_move_stats(move_stats: dict[str, int], action_name: str, success: bool) -> None:
    if not action_name.startswith("move"):
        return
    move_stats["attempts"] += 1
    if success:
        move_stats["success"] += 1
    else:
        move_stats["fail"] += 1


def move_success_rate(move_stats: dict[str, int]) -> float:
    attempts = move_stats.get("attempts", 0)
    if attempts == 0:
        return 0.0
    return move_stats.get("success", 0) / attempts


def diff_action_counts(
    first: Counter[str],
    second: Counter[str],
    *,
    top_n: int,
) -> list[tuple[str, int]]:
    deltas: dict[str, int] = {}
    for action in set(first) | set(second):
        deltas[action] = first.get(action, 0) - second.get(action, 0)
    return sorted(deltas.items(), key=lambda item: abs(item[1]), reverse=True)[:top_n]
