from __future__ import annotations

from graders.common.grader_runtime import (
    JsonObject,
    clamp,
    normalized_spread,
    normalized_top_margin,
    numeric_list,
    numeric_scalar,
    run_grader,
    scalar_signal,
)

GRADER_ID = "tribal-cog-grader"


def interestingness(results: JsonObject) -> float:
    team_scores = numeric_list(results.get("team_scores")) or numeric_list(results.get("scores"))
    winner_team = numeric_scalar(results.get("winner_team"))
    winner_signal = 1.0 if winner_team is not None else 0.0
    reason = results.get("truncation_reason")
    reason_text = reason.lower() if isinstance(reason, str) else ""
    completion_signal = 1.0 if "victory" in reason_text or "winner" in reason_text else 0.25 if reason_text else 0.0
    score = (
        0.35 * normalized_spread(team_scores)
        + 0.20 * normalized_top_margin(team_scores)
        + 0.20 * winner_signal
        + 0.15 * scalar_signal(results.get("steps"), 1000.0)
        + 0.10 * completion_signal
    )
    return round(clamp(score), 4)


def main() -> None:
    run_grader(GRADER_ID, interestingness, "Tribal Cog")


if __name__ == "__main__":
    main()
