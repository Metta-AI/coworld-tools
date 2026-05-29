from __future__ import annotations

from graders.common.grader_runtime import (
    JsonObject,
    clamp,
    magnitude_signal,
    normalized_spread,
    numeric_list,
    run_grader,
    scalar_signal,
    truthy_ratio,
)

GRADER_ID = "liarliar-grader"


def interestingness(results: JsonObject) -> float:
    scores = numeric_list(results.get("scores"))
    modules_solved = numeric_list(results.get("modules_solved"))
    modules_failed = numeric_list(results.get("modules_failed"))
    hint_recoveries = numeric_list(results.get("hint_recoveries"))
    module_attempts = sum(modules_solved) + sum(modules_failed)
    module_success = sum(modules_solved) / module_attempts if module_attempts > 0 else 0.0
    module_activity = clamp(module_attempts / max(len(scores), 1) / 4.0)
    survival = truthy_ratio(results.get("survived"))
    non_detonation = 1.0 - truthy_ratio(results.get("detonated"))
    communication = max(magnitude_signal(hint_recoveries, 3.0), scalar_signal(results.get("rps_outcomes"), 6.0))

    score = (
        0.25 * module_success
        + 0.20 * module_activity
        + 0.15 * survival
        + 0.15 * non_detonation
        + 0.15 * normalized_spread(scores)
        + 0.05 * communication
        + 0.05 * scalar_signal(results.get("duration_seconds"), 300.0)
    )
    return round(clamp(score), 4)


def main() -> None:
    run_grader(GRADER_ID, interestingness, "Liar Liar")


if __name__ == "__main__":
    main()
