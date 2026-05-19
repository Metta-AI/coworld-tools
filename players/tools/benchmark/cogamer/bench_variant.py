#!/usr/bin/env python3
"""Run Cogamer CvC episodes for a named variant and summarize learnings."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from policies.cyborg.cogamer.cvc.benchmarking import (  # noqa: E402
    compare_learning_runs,
    discover_learning_files,
    format_metric,
    summarize_learning_file,
)

BENCH_ROOT = REPO_ROOT / ".benchmarks" / "cogamer"

_KEY_METRICS = [
    "final_hearts",
    "peak_friendly_junctions",
    "friendly_junctions_final",
    "final_resource_units",
    "resource_types_seen",
    "stalled_fraction",
    "longest_stall",
    "num_stall_periods",
    "stall_steps_resource_coverage",
    "stall_steps_economy_bootstrap",
    "stall_steps_aligner_pressure",
    "stall_steps_unknown",
    "llm_count",
    "llm_error_rate",
    "avg_latency_ms",
]


def run_episode(
    variant_dir: Path,
    run_index: int,
    *,
    mission: str,
    policy: str,
    agents: int,
    steps: int,
    renderer: str,
    seed: int,
) -> Path:
    run_dir = variant_dir / f"run-{run_index}"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ("UV_PROJECT", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT"):
        env.pop(key, None)
    env["COGLET_LEARNINGS_DIR"] = str(run_dir.resolve())
    cmd = [
        "uv",
        "run",
        "--extra",
        "cogames",
        "cogames",
        "play",
        "-m",
        mission,
        "-p",
        policy,
        "-c",
        str(agents),
        "-s",
        str(steps),
        "-r",
        renderer,
        "--seed",
        str(seed),
    ]
    print(f"run-{run_index}: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=True)
    return run_dir


def print_variant_summary(
    variant: str, files: list[Path], outlier_threshold: float
) -> None:
    print(f"\n{variant} ({len(files)} learning files)")
    for path in files:
        summary = summarize_learning_file(path)
        print(
            f"  {path.parent.name}/{path.name}: "
            f"steps={summary.total_steps} "
            f"agents={summary.agents} "
            f"hearts={summary.final_hearts} "
            f"junction_peak={summary.peak_friendly_junctions} "
            f"stalled={summary.stagnation.stalled_fraction:.1%} "
            f"llm={summary.llm_count}"
        )
    metrics = compare_learning_runs(files, outlier_threshold=outlier_threshold)
    print()
    print(f"  {'Metric':<32s} {'Mean +/- Std':>20s}")
    print(f"  {'-' * 32} {'-' * 20}")
    for name in _KEY_METRICS:
        if name in metrics:
            print(f"  {name:<32s} {format_metric(metrics[name]):>20s}")


def print_comparison(
    before: str,
    after: str,
    before_files: list[Path],
    after_files: list[Path],
    outlier_threshold: float,
) -> None:
    before_metrics = compare_learning_runs(
        before_files, outlier_threshold=outlier_threshold
    )
    after_metrics = compare_learning_runs(
        after_files, outlier_threshold=outlier_threshold
    )
    print(f"\nBEFORE vs AFTER: {before} -> {after}")
    print(f"  {'Metric':<32s} {before[:18]:>18s} {after[:18]:>18s} {'Delta':>14s}")
    print(f"  {'-' * 32} {'-' * 18} {'-' * 18} {'-' * 14}")
    for name in _KEY_METRICS:
        if name not in before_metrics or name not in after_metrics:
            continue
        before_stat = before_metrics[name]
        after_stat = after_metrics[name]
        before_text = format_metric(before_stat)
        after_text = format_metric(after_stat)
        delta_text = "N/A"
        if before_stat.mean is not None and after_stat.mean is not None:
            delta = after_stat.mean - before_stat.mean
            delta_text = f"{delta:+.2f}"
        print(f"  {name:<32s} {before_text:>18s} {after_text:>18s} {delta_text:>14s}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant")
    parser.add_argument("--runs", "-n", type=int, default=1)
    parser.add_argument("--start-run", type=int, default=0)
    parser.add_argument("--agents", "-a", type=int, default=8)
    parser.add_argument("--steps", "-s", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mission", "-m", default="machina_1")
    parser.add_argument("--renderer", "-r", default="none")
    parser.add_argument(
        "--policy",
        "-p",
        default="class=policies.cyborg.cogamer.cvc.cogamer_policy.CvCPolicy",
    )
    parser.add_argument("--compare-to")
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--outlier-threshold", "-t", type=float, default=2.0)
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()

    variant_dir = BENCH_ROOT / args.variant
    if not args.analyze_only:
        for run_index in range(args.start_run, args.start_run + args.runs):
            run_episode(
                variant_dir,
                run_index,
                mission=args.mission,
                policy=args.policy,
                agents=args.agents,
                steps=args.steps,
                renderer=args.renderer,
                seed=args.seed + run_index,
            )

    files = discover_learning_files(variant_dir)
    if not files:
        raise FileNotFoundError(f"No Cogamer learnings files found in {variant_dir}")
    print_variant_summary(args.variant, files, args.outlier_threshold)

    if args.compare_to:
        compare_dir = (
            args.baseline_dir.resolve()
            if args.baseline_dir
            else BENCH_ROOT / args.compare_to
        )
        compare_files = discover_learning_files(compare_dir)
        if not compare_files:
            raise FileNotFoundError(
                f"No baseline learnings files found in {compare_dir}"
            )
        print_comparison(
            args.compare_to, args.variant, compare_files, files, args.outlier_threshold
        )


if __name__ == "__main__":
    main()
