from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from cogames_rl_researcher.actor_critic import ActorCriticReport
from cogames_rl_researcher.json_io import read_model, write_json


class SwarmConfig(BaseModel):
    workers: int = Field(default=3, ge=1)
    timeout_seconds: int = Field(default=900, ge=1)
    max_tasks_per_worker: int = Field(default=1, ge=1)


class SwarmWorker(BaseModel):
    worker_id: str
    role: str
    timeout_seconds: int
    max_tasks: int


class SwarmTask(BaseModel):
    rank: int
    worker_id: str
    role: str
    instruction: str
    source_category: str


class SwarmPlan(BaseModel):
    generated_at: datetime
    source_run_id: str
    verdict: str
    workers: list[SwarmWorker]
    tasks: list[SwarmTask]


_ROLE_BY_CATEGORY = {
    "friction": "cli-debugger",
    "reliability": "reaper-operator",
    "performance": "profiler",
    "coverage": "submission-operator",
    "none": "optimizer",
}


def _worker_roles(config: SwarmConfig) -> list[str]:
    base = [
        "optimizer",
        "cli-debugger",
        "reaper-operator",
        "profiler",
        "submission-operator",
    ]
    if config.workers <= len(base):
        return base[: config.workers]
    extra = ["generalist" for _ in range(config.workers - len(base))]
    return base + extra


def build_swarm_plan(report: ActorCriticReport, config: SwarmConfig) -> SwarmPlan:
    roles = _worker_roles(config)
    workers = [
        SwarmWorker(
            worker_id=f"worker-{idx + 1}",
            role=role,
            timeout_seconds=config.timeout_seconds,
            max_tasks=config.max_tasks_per_worker,
        )
        for idx, role in enumerate(roles)
    ]

    total_capacity = config.workers * config.max_tasks_per_worker
    limited_bottlenecks = report.critic.bottlenecks[:total_capacity]

    tasks: list[SwarmTask] = []
    worker_task_counts = {worker.worker_id: 0 for worker in workers}

    for bottleneck in limited_bottlenecks:
        preferred_role = _ROLE_BY_CATEGORY.get(bottleneck.category, "optimizer")

        target_worker = None
        for worker in workers:
            if worker.role == preferred_role and worker_task_counts[worker.worker_id] < worker.max_tasks:
                target_worker = worker
                break

        if target_worker is None:
            for worker in workers:
                if worker_task_counts[worker.worker_id] < worker.max_tasks:
                    target_worker = worker
                    break

        if target_worker is None:
            break

        worker_task_counts[target_worker.worker_id] += 1
        tasks.append(
            SwarmTask(
                rank=bottleneck.rank,
                worker_id=target_worker.worker_id,
                role=target_worker.role,
                instruction=f"Investigate [{bottleneck.category}] {bottleneck.evidence} then apply: {bottleneck.fix}",
                source_category=bottleneck.category,
            )
        )

    return SwarmPlan(
        generated_at=datetime.now(UTC),
        source_run_id=report.current_run_id,
        verdict=report.critic.verdict,
        workers=workers,
        tasks=tasks,
    )


def write_swarm_plan(
    *,
    actor_critic_report_path: Path,
    output_path: Path,
    config: SwarmConfig,
) -> SwarmPlan:
    report = read_model(actor_critic_report_path, ActorCriticReport)
    plan = build_swarm_plan(report, config)
    write_json(output_path, plan)
    return plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build optional swarm task plan from actor/critic report")
    parser.add_argument("--actor-critic-report", required=True, help="Path to actor_critic_report.json")
    parser.add_argument("--output", required=True, help="Output path for swarm plan JSON")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--max-tasks-per-worker", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    plan = write_swarm_plan(
        actor_critic_report_path=Path(args.actor_critic_report),
        output_path=Path(args.output),
        config=SwarmConfig(
            workers=args.workers,
            timeout_seconds=args.timeout_seconds,
            max_tasks_per_worker=args.max_tasks_per_worker,
        ),
    )

    print(f"workers={len(plan.workers)}")
    print(f"tasks={len(plan.tasks)}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
