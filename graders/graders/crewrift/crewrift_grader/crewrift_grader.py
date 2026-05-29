from __future__ import annotations

from graders.common.grader_runtime import JsonObject, clamp, normalized_spread, numeric_list, run_grader, truthy_list

GRADER_ID = "crewrift-grader"


def interestingness(results: JsonObject) -> float:
    scores = numeric_list(results.get("scores"))
    wins = truthy_list(results.get("win"))
    tasks = numeric_list(results.get("tasks"))
    kills = numeric_list(results.get("kills"))
    vote_players = numeric_list(results.get("vote_players"))
    vote_skip = numeric_list(results.get("vote_skip"))
    vote_timeout = numeric_list(results.get("vote_timeout"))

    win_balance = 1.0 if any(wins) and not all(wins) else 0.25 if wins else 0.0
    task_signal = clamp(sum(tasks) / max(len(tasks), 1) / 8.0) if tasks else 0.0
    kill_signal = clamp(sum(kills) / max(len(kills), 1)) if kills else 0.0
    vote_activity = clamp((sum(vote_players) + sum(vote_skip)) / max(len(vote_players) + len(vote_skip), 1))
    timeout_penalty = 0.25 * clamp(sum(vote_timeout) / max(len(vote_timeout), 1)) if vote_timeout else 0.0

    score = (
        0.30 * win_balance
        + 0.25 * normalized_spread(scores)
        + 0.25 * task_signal
        + 0.15 * kill_signal
        + 0.05 * max(0.0, vote_activity - timeout_penalty)
    )
    return round(clamp(score), 4)


def main() -> None:
    run_grader(GRADER_ID, interestingness, "Crewrift")


if __name__ == "__main__":
    main()
