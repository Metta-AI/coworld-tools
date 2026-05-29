from __future__ import annotations

from graders.common.grader_runtime import (
    JsonObject,
    clamp,
    magnitude_signal,
    normalized_spread,
    normalized_top_margin,
    numeric_list,
    run_grader,
    scalar_signal,
)

GRADER_ID = "mettagrid-score-grader"


def interestingness(results: JsonObject) -> float:
    scores = numeric_list(results.get("scores"))
    score = (
        0.50 * normalized_spread(scores)
        + 0.20 * normalized_top_margin(scores)
        + 0.20 * magnitude_signal(scores, 100.0)
        + 0.10 * scalar_signal(results.get("steps"), 1000.0)
    )
    return round(clamp(score), 4)


def main() -> None:
    run_grader(GRADER_ID, interestingness, "MettaGrid score")


if __name__ == "__main__":
    main()
