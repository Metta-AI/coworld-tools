from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from cogames_rl_researcher.json_io import write_json
from cogames_rl_researcher.startup import _run_command

PickupStatus = Literal["success", "failed", "stall_timeout", "wall_timeout"]


class PickupConfig(BaseModel):
    policy: str
    pool: list[str] = Field(min_length=1)
    mission: str = "machina_1"
    cogs: int = Field(default=4, ge=1)
    episodes: int = Field(default=1, ge=1)
    steps: int = Field(default=1000, ge=1)
    seed: int = Field(default=50, ge=0)
    map_seed: int | None = Field(default=None, ge=0)
    action_timeout_ms: int = Field(default=250, ge=1)
    output_root: Path = Path("./artifacts/ai_researcher")
    cogames_bin: str = "cogames"
    detect_idle_seconds: int = Field(default=600, ge=1)
    max_step_seconds: int = Field(default=1800, ge=1)


class PickupResult(BaseModel):
    run_id: str
    status: PickupStatus
    started_at: datetime
    ended_at: datetime
    run_dir: str
    replay_dir: str
    command: list[str]
    return_code: int | None
    stdout_log: str
    stderr_log: str
    stdout_tail: str = ""
    stderr_tail: str = ""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def run_pickup(config: PickupConfig) -> PickupResult:
    started_at = _utc_now()
    run_id = f"{started_at.strftime('%Y%m%d_%H%M%S')}_pickup"
    run_dir = config.output_root / run_id
    steps_dir = run_dir / "steps"
    replay_dir = run_dir / "replays"
    steps_dir.mkdir(parents=True, exist_ok=True)
    replay_dir.mkdir(parents=True, exist_ok=True)

    command = [
        config.cogames_bin,
        "pickup",
        "--policy",
        config.policy,
        "--mission",
        config.mission,
        "--cogs",
        str(config.cogs),
        "--episodes",
        str(config.episodes),
        "--steps",
        str(config.steps),
        "--seed",
        str(config.seed),
        "--action-timeout-ms",
        str(config.action_timeout_ms),
        "--save-replay-dir",
        str(replay_dir),
    ]
    if config.map_seed is not None:
        command.extend(["--map-seed", str(config.map_seed)])
    for pool_policy in config.pool:
        command.extend(["--pool", pool_policy])
    result = _run_command(
        step_name="pickup_eval",
        attempt=1,
        command=command,
        steps_dir=steps_dir,
        detect_idle_seconds=config.detect_idle_seconds,
        max_step_seconds=config.max_step_seconds,
        env=dict(os.environ),
    )

    ended_at = _utc_now()
    status: PickupStatus = (
        result.status if result.status in {"success", "failed", "stall_timeout", "wall_timeout"} else "failed"
    )
    pickup_result = PickupResult(
        run_id=run_id,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        run_dir=str(run_dir),
        replay_dir=str(replay_dir),
        command=command,
        return_code=result.return_code,
        stdout_log=result.stdout_log,
        stderr_log=result.stderr_log,
        stdout_tail=result.stdout_tail,
        stderr_tail=result.stderr_tail,
    )

    write_json(run_dir / "pickup_config.json", config)
    write_json(run_dir / "pickup_result.json", pickup_result)
    (run_dir / "pickup_diagnosis.md").write_text(
        "\n".join(
            [
                f"# Pickup Diagnosis ({pickup_result.run_id})",
                "",
                f"- status: {pickup_result.status}",
                f"- mission: {config.mission}",
                f"- policy: {config.policy}",
                f"- pool_size: {len(config.pool)}",
                f"- replay_dir: {pickup_result.replay_dir}",
                f"- command: `{' '.join(pickup_result.command)}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return pickup_result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AI researcher pickup workflow (diagnose/scrimmage shadow)")
    parser.add_argument("--policy", required=True, help="Candidate policy spec")
    parser.add_argument("--pool", action="append", required=True, help="Pool policy spec (repeatable)")
    parser.add_argument("--mission", default="machina_1")
    parser.add_argument("--cogs", type=int, default=4)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=50)
    parser.add_argument("--map-seed", type=int, default=None)
    parser.add_argument("--action-timeout-ms", type=int, default=250)
    parser.add_argument("--output-root", default="./artifacts/ai_researcher")
    parser.add_argument("--cogames-bin", default="cogames")
    parser.add_argument("--detect-idle-seconds", type=int, default=600)
    parser.add_argument("--max-step-seconds", type=int, default=1800)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    result = run_pickup(
        PickupConfig(
            policy=args.policy,
            pool=args.pool,
            mission=args.mission,
            cogs=args.cogs,
            episodes=args.episodes,
            steps=args.steps,
            seed=args.seed,
            map_seed=args.map_seed,
            action_timeout_ms=args.action_timeout_ms,
            output_root=Path(args.output_root),
            cogames_bin=args.cogames_bin,
            detect_idle_seconds=args.detect_idle_seconds,
            max_step_seconds=args.max_step_seconds,
        )
    )

    print(f"run_dir={result.run_dir}")
    print(f"status={result.status}")
    print(f"replay_dir={result.replay_dir}")
    print(f"result={Path(result.run_dir) / 'pickup_result.json'}")
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
