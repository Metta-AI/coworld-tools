from __future__ import annotations

from graders.common.grader_runtime import (
    JsonObject,
    clamp,
    magnitude_signal,
    mixed_flag_signal,
    normalized_spread,
    normalized_top_margin,
    numeric_leaf_sum,
    numeric_list,
    run_grader,
    scalar_signal,
)

GRADER_ID = "bitworld-score-grader"


def interestingness(results: JsonObject) -> float:
    scores = numeric_list(results.get("scores"))
    activity = max(
        magnitude_signal(scores, 100.0),
        magnitude_signal(numeric_list(results.get("distance_walked")), 100.0),
        magnitude_signal(numeric_list(results.get("survival_ticks")), 500.0),
        magnitude_signal(numeric_list(results.get("ships")), 50.0),
        magnitude_signal(numeric_list(results.get("planets")), 10.0),
        magnitude_signal(numeric_list(results.get("hearts")), 5.0),
        scalar_signal(results.get("day"), 3.0),
        clamp(numeric_leaf_sum(results.get("stats")) / 100.0),
    )
    outcome = max(mixed_flag_signal(results.get("win")), mixed_flag_signal(results.get("alive")))
    score = (
        0.40 * normalized_spread(scores)
        + 0.25 * normalized_top_margin(scores)
        + 0.25 * activity
        + 0.10 * outcome
    )
    return round(clamp(score), 4)


def main() -> None:
    run_grader(GRADER_ID, interestingness, "BitWorld score")


if __name__ == "__main__":
    main()
