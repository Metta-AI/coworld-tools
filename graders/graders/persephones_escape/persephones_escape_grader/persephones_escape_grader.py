from __future__ import annotations

from graders.common.grader_runtime import (
    JsonObject,
    clamp,
    normalized_spread,
    numeric_list,
    run_grader,
    scalar_signal,
)

GRADER_ID = "persephones-escape-grader"
DRAW_VALUES = {"", "draw", "none", "no one wins", "nobody", "null"}


def interestingness(results: JsonObject) -> float:
    scores = numeric_list(results.get("scores"))
    winner = results.get("winner")
    winner_text = winner.strip().lower() if isinstance(winner, str) else ""
    decisive = 1.0 if winner_text and winner_text not in DRAW_VALUES else 0.0
    player_count_signal = scalar_signal(len(results.get("players")) if isinstance(results.get("players"), list) else 0, 12.0)
    score = (
        0.45 * decisive
        + 0.30 * normalized_spread(scores)
        + 0.15 * scalar_signal(results.get("ticks"), 300.0)
        + 0.10 * player_count_signal
    )
    return round(clamp(score), 4)


def main() -> None:
    run_grader(GRADER_ID, interestingness, "Persephone's Escape")


if __name__ == "__main__":
    main()
