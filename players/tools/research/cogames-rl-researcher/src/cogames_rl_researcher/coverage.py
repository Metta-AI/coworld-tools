from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from cogames.cli.submit import DEFAULT_SUBMIT_SERVER
from cogames_rl_researcher.json_io import read_json, write_json
from cogames_rl_researcher.startup import (
    DEFAULT_SEASON,
    RunStatus,
    StartupConfig,
    _policy_family_key,
    run_startup,
)
from softmax.auth import DEFAULT_COGAMES_SERVER


class CoverageVariant(BaseModel):
    variant_id: str
    policy_name: str
    policy: str | None = None
    mission: str | None = None
    experiment_family: str | None = None
    episodes: int | None = Field(default=None, ge=1)
    steps: int | None = Field(default=None, ge=1)
    seed: int | None = Field(default=None, ge=0)


class CoverageVariantResult(BaseModel):
    variant_id: str
    policy_name: str
    experiment_family: str
    run_id: str
    run_dir: str
    status: RunStatus
    submit_attempts: int
    submit_successes: int
    attempt_to_submit_ratio: float
    leaderboard_rank: int | None


class CoveragePackSummary(BaseModel):
    generated_at: datetime
    season: str
    base_policy: str
    attempted_variants: int
    successful_submits: int
    valid_submit_coverage_ratio: float
    attempted_experiment_families: int
    experiment_family_breadth: int
    experiment_family_breadth_ratio: float
    results: list[CoverageVariantResult]


def _variant_startup_config(base_config: StartupConfig, variant: CoverageVariant) -> StartupConfig:
    return base_config.model_copy(
        update={
            "policy": variant.policy or base_config.policy,
            "policy_name": variant.policy_name,
            "mission": variant.mission or base_config.mission,
            "episodes": variant.episodes or base_config.episodes,
            "steps": variant.steps or base_config.steps,
            "seed": variant.seed if variant.seed is not None else base_config.seed,
            "run_upload": True,
            "run_submit": True,
        }
    )


def _experiment_family(variant: CoverageVariant) -> str:
    return _policy_family_key(variant.experiment_family or variant.policy_name)


def run_submit_coverage_pack(
    *,
    base_config: StartupConfig,
    variants: list[CoverageVariant],
) -> CoveragePackSummary:
    results: list[CoverageVariantResult] = []

    for variant in variants:
        variant_config = _variant_startup_config(base_config, variant)
        bundle = run_startup(variant_config)

        submit_attempts = sum(1 for step in bundle.steps if step.step_name == "submit")
        submit_successes = sum(1 for step in bundle.steps if step.step_name == "submit" and step.status == "success")
        attempt_to_submit_ratio = (
            float(submit_successes) / float(submit_attempts)
            if submit_attempts > 0
            else bundle.submit_coverage_index.attempt_to_submit_ratio
        )

        results.append(
            CoverageVariantResult(
                variant_id=variant.variant_id,
                policy_name=variant.policy_name,
                experiment_family=_experiment_family(variant),
                run_id=bundle.run_id,
                run_dir=bundle.run_dir,
                status=bundle.status,
                submit_attempts=submit_attempts,
                submit_successes=submit_successes,
                attempt_to_submit_ratio=attempt_to_submit_ratio,
                leaderboard_rank=bundle.leaderboard_rank,
            )
        )

    attempted_variants = len(variants)
    successful_submits = sum(1 for result in results if result.submit_successes > 0)
    valid_submit_coverage_ratio = (
        float(successful_submits) / float(attempted_variants) if attempted_variants > 0 else 0.0
    )

    attempted_families = {result.experiment_family for result in results}
    submitted_families = {result.experiment_family for result in results if result.submit_successes > 0}
    attempted_experiment_families = len(attempted_families)
    experiment_family_breadth = len(submitted_families)
    experiment_family_breadth_ratio = (
        float(experiment_family_breadth) / float(attempted_experiment_families)
        if attempted_experiment_families > 0
        else 0.0
    )

    return CoveragePackSummary(
        generated_at=datetime.now(UTC),
        season=base_config.season,
        base_policy=base_config.policy,
        attempted_variants=attempted_variants,
        successful_submits=successful_submits,
        valid_submit_coverage_ratio=valid_submit_coverage_ratio,
        attempted_experiment_families=attempted_experiment_families,
        experiment_family_breadth=experiment_family_breadth,
        experiment_family_breadth_ratio=experiment_family_breadth_ratio,
        results=results,
    )


def write_submit_coverage_pack(
    *,
    base_config: StartupConfig,
    variants: list[CoverageVariant],
    output_path: Path,
) -> CoveragePackSummary:
    summary = run_submit_coverage_pack(base_config=base_config, variants=variants)
    write_json(output_path, summary)
    return summary


def _load_variants(path: Path) -> list[CoverageVariant]:
    payload = read_json(path)
    if not isinstance(payload, list):
        raise ValueError("variants file must contain a JSON list")
    return [CoverageVariant.model_validate(item) for item in payload]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run submit-coverage expansion pack across variants")
    parser.add_argument("--variants-file", required=True, help="JSON list of variant definitions")
    parser.add_argument("--output", required=True, help="Output JSON path for coverage pack summary")
    parser.add_argument("--policy", required=True, help="Base policy URI/path")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--mission", default="arena")
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-root", default="./artifacts/ai_researcher")
    parser.add_argument("--cogames-bin", default="cogames")
    parser.add_argument("--login-server", default=DEFAULT_COGAMES_SERVER)
    parser.add_argument("--server", default=DEFAULT_SUBMIT_SERVER)
    parser.add_argument("--detect-idle-seconds", type=int, default=600)
    parser.add_argument("--max-step-seconds", type=int, default=1800)
    parser.add_argument("--max-recoveries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=int, default=1)
    parser.add_argument("--no-leaderboard", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    variants = _load_variants(Path(args.variants_file))
    if not variants:
        raise SystemExit("No variants provided in variants file")

    base_config = StartupConfig(
        policy=args.policy,
        policy_name=variants[0].policy_name,
        season=args.season,
        mission=args.mission,
        episodes=args.episodes,
        steps=args.steps,
        seed=args.seed,
        output_root=Path(args.output_root),
        cogames_bin=args.cogames_bin,
        login_server=args.login_server,
        server=args.server,
        detect_idle_seconds=args.detect_idle_seconds,
        max_step_seconds=args.max_step_seconds,
        max_recoveries=args.max_recoveries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        run_upload=True,
        run_submit=True,
        run_leaderboard=not args.no_leaderboard,
    )

    summary = write_submit_coverage_pack(
        base_config=base_config,
        variants=variants,
        output_path=Path(args.output),
    )

    print(f"attempted_variants={summary.attempted_variants}")
    print(f"successful_submits={summary.successful_submits}")
    print(f"valid_submit_coverage_ratio={summary.valid_submit_coverage_ratio:.2f}")
    print(f"experiment_family_breadth={summary.experiment_family_breadth}")
    print(f"experiment_family_breadth_ratio={summary.experiment_family_breadth_ratio:.2f}")
    print(f"output={args.output}")

    return 0 if summary.successful_submits == summary.attempted_variants else 1


if __name__ == "__main__":
    raise SystemExit(main())
