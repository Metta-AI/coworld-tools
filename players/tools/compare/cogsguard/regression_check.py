#!/usr/bin/env python3
"""regression_check.py — Compare current eval results against baseline and flag regressions.

Usage:
    python scripts/regression_check.py --result RESULT.json --baseline BASELINE.json

The script:
  1. Extracts key metrics from the current result JSON.
  2. Loads the stored baseline (previous best) if it exists.
  3. Compares each metric; flags regressions beyond a tolerance margin.
  4. Optionally updates the baseline when scores improve.

Exit codes:
  0 — no regressions (or no baseline to compare against)
  1 — regression detected in one or more metrics
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Metrics to track: (key, source, higher_is_better, regression_tolerance_pct)
TRACKED_METRICS = [
    ("aligned.junction.held", "derived", True, 5.0),
    ("aligned.junction.gained", "derived", True, 5.0),
    ("reward", "derived", True, 10.0),
    ("heart.gained", "derived", True, 10.0),
    ("heart.lost", "derived", False, 10.0),  # lower is better
    ("action_timeouts", "derived", False, 20.0),  # lower is better
]


def extract_metrics(data: dict) -> dict[str, float | None]:
    """Extract tracked metrics from cogames scrimmage JSON output."""
    derived = importlib.import_module("agent_policies.tools.eval.cogsguard.eval_result_metrics").extract_cogsguard_eval_metrics(data)
    return {key: derived.get(key) for key, _source, _hib, _tol in TRACKED_METRICS}


def fmt(v: float | None) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def check_regressions(
    current: dict[str, float | None],
    baseline: dict[str, float | None],
) -> list[str]:
    """Compare current metrics against baseline. Returns list of regression messages."""
    regressions = []

    for key, _source, higher_is_better, tolerance_pct in TRACKED_METRICS:
        cur = current.get(key)
        base = baseline.get(key)

        if cur is None or base is None:
            continue

        if base == 0:
            continue

        if higher_is_better:
            threshold = base * (1.0 - tolerance_pct / 100.0)
            if cur < threshold:
                regressions.append(
                    f"  REGRESS: {key} = {fmt(cur)} < {fmt(threshold)} (baseline {fmt(base)}, -{tolerance_pct}% margin)"
                )
        else:
            threshold = base * (1.0 + tolerance_pct / 100.0)
            if cur > threshold:
                regressions.append(
                    f"  REGRESS: {key} = {fmt(cur)} > {fmt(threshold)} (baseline {fmt(base)}, +{tolerance_pct}% margin)"
                )

    return regressions


def update_baseline(
    baseline_path: Path,
    current: dict[str, float | None],
    metadata: dict[str, str],
) -> None:
    """Update the baseline file with current results if they represent improvements."""
    existing: dict[str, float | None] = {}
    if baseline_path.exists():
        try:
            data = json.loads(baseline_path.read_text())
            existing = data.get("metrics", {})
        except (json.JSONDecodeError, OSError):
            pass

    updated = dict(existing)
    improved = False

    for key, _source, higher_is_better, _tol in TRACKED_METRICS:
        cur = current.get(key)
        old = existing.get(key)

        if cur is None:
            continue

        if old is None:
            updated[key] = cur
            improved = True
            continue

        if higher_is_better and cur > old:
            updated[key] = cur
            improved = True
        elif not higher_is_better and cur < old:
            updated[key] = cur
            improved = True

    if improved:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(
                {
                    "metrics": updated,
                    "updated_at": metadata.get("timestamp", ""),
                    "updated_by": metadata.get("label", ""),
                    "policy": metadata.get("policy", ""),
                },
                indent=2,
            )
            + "\n"
        )
        print(f"Baseline updated: {baseline_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--result", required=True, help="Path to current eval result JSON")
    parser.add_argument("--baseline", required=True, help="Path to baseline JSON file")
    parser.add_argument("--label", default="", help="Version label (e.g. git SHA)")
    parser.add_argument("--timestamp", default="", help="Run timestamp")
    parser.add_argument("--params", default="", help="Policy params used")
    parser.add_argument("--policy", default="", help="Policy URI used")
    parser.add_argument("--no-update", action="store_true", help="Don't update baseline on improvement")
    args = parser.parse_args()

    # Load current result
    result_path = Path(args.result)
    if not result_path.exists():
        print(f"ERROR: Result file not found: {result_path}")
        return 1

    parse_eval_result_text = importlib.import_module("agent_policies.tools.eval.cogsguard.eval_result_metrics").parse_eval_result_text
    result_data = parse_eval_result_text(result_path.read_text())

    current = extract_metrics(result_data)

    # Print current metrics
    print("=== Current Metrics ===")
    for key, _source, _hib, _tol in TRACKED_METRICS:
        print(f"  {key:30s} {fmt(current.get(key))}")
    print()

    # Load baseline
    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        print("No baseline found — establishing initial baseline.")
        if not args.no_update:
            update_baseline(
                baseline_path,
                current,
                {
                    "timestamp": args.timestamp,
                    "label": args.label,
                    "policy": args.policy,
                },
            )
        return 0

    try:
        baseline_data = json.loads(baseline_path.read_text())
        baseline = baseline_data.get("metrics", {})
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARN: Could not read baseline ({exc}), treating as first run.")
        if not args.no_update:
            update_baseline(
                baseline_path,
                current,
                {
                    "timestamp": args.timestamp,
                    "label": args.label,
                    "policy": args.policy,
                },
            )
        return 0

    # Print baseline for comparison
    print("=== Baseline ===")
    for key, _source, _hib, _tol in TRACKED_METRICS:
        print(f"  {key:30s} {fmt(baseline.get(key))}")
    print()

    # Check regressions
    regressions = check_regressions(current, baseline)

    if regressions:
        print("=== REGRESSIONS DETECTED ===")
        for msg in regressions:
            print(msg)
        print()
        return 1

    print("=== No Regressions ===")
    print("All metrics within tolerance of baseline.")
    print()

    # Update baseline if improved
    if not args.no_update:
        update_baseline(
            baseline_path,
            current,
            {
                "timestamp": args.timestamp,
                "label": args.label,
                "policy": args.policy,
            },
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
