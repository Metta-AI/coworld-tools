"""`run_scenario` — drive a Scenario through the mettagrid rollout path.

Builds a MettaGridConfig from the mission registry, applies
mission/variant overrides and the scenario's config-level setup hook,
then invokes `mettagrid.runner.rollout.run_episode_local` with a
PolicySpec for CvCPolicy. The policy's `record_dir` kwarg writes
events.json on episode end; we add result.json.
"""

from __future__ import annotations

import dataclasses
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mettagrid.policy.loader import initialize_or_load_policy
from mettagrid.policy.policy import PolicySpec
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.runner.rollout import resolve_env_for_seed, single_episode_rollout

from cvc_policy.scenarios import Scenario
from cvc_policy.scenarios._run import Run
from cvc_policy.viewer.render import render as render_report


def _build_machina_1(cogs: int | None) -> Any:
    from cogames.games.cogs_vs_clips.missions.machina_1 import make_machina1_mission

    if cogs is not None:
        return make_machina1_mission(num_agents=cogs)
    return make_machina1_mission()


def _build_tutorial(role: str, cogs: int | None) -> Any:
    from cogames.games.cogs_vs_clips.missions.tutorial import make_tutorial_mission

    mission = make_tutorial_mission()
    if cogs is not None:
        mission = mission.model_copy(update={"num_agents": cogs, "num_cogs": cogs})
    return mission.with_variants([role])


# Mission registry — the single source of truth for resolve_mission.
# Fails loud on unknown names; see
# docs/plans/2026-04-15-diagnostic-framework-design.md §7a for rationale.
_KNOWN_MISSIONS: dict[str, Callable[[int | None], Any]] = {
    "machina_1": _build_machina_1,
    "tutorial.aligner": lambda cogs: _build_tutorial("aligner", cogs),
    "tutorial.miner": lambda cogs: _build_tutorial("miner", cogs),
    "tutorial.scrambler": lambda cogs: _build_tutorial("scrambler", cogs),
    "tutorial.scout": lambda cogs: _build_tutorial("scout", cogs),
}

# CvCPolicy kwargs we pass through to PolicySpec.init_kwargs. Validated
# in the harness so typos fail at scenario-construction time instead of
# deep inside the runner.
_ALLOWED_POLICY_KWARGS: frozenset[str] = frozenset(
    {"device", "programs", "log", "log_py", "log_llm", "game_id", "record_dir"}
)


def resolve_mission(name: str, *, cogs: int | None = None) -> Any:
    """Build a mission object from a registry name."""
    builder = _KNOWN_MISSIONS.get(name)
    if builder is None:
        valid = ", ".join(sorted(_KNOWN_MISSIONS))
        raise KeyError(f"unknown mission: {name!r}. Valid: {valid}")
    return builder(cogs)


def _validate_policy_kwargs(policy_kwargs: dict[str, Any]) -> None:
    bad = [k for k in policy_kwargs if k not in _ALLOWED_POLICY_KWARGS]
    if bad:
        raise ValueError(
            f"unknown CvCPolicy kwarg(s): {sorted(bad)}. "
            f"Allowed: {sorted(_ALLOWED_POLICY_KWARGS)}"
        )


def _drive_rollout(*, env_cfg: Any, spec: PolicySpec, run_dir: Path, seed: int) -> int:  # pragma: no cover
    """Run one episode. Returns steps executed.

    Inlines the `run_episode_local` flow so we can call
    `CvCPolicy._on_episode_end` synchronously after rollout (to flush
    events.json before assertion code reads it). Atexit-only flush
    would not fire until interpreter shutdown.

    Not unit-testable without a real mettagrid env; exercised by the
    scenario-marked tests (tests/scenarios/).
    """
    env_for_rollout = resolve_env_for_seed(env_cfg, seed)
    env_interface = PolicyEnvInterface.from_mg_cfg(env_for_rollout)
    policy = initialize_or_load_policy(env_interface, spec)
    assignments = [0] * env_for_rollout.game.num_agents

    result, replay = single_episode_rollout(
        [policy],
        assignments,
        env_for_rollout,
        seed=seed,
        max_action_time_ms=30_000,
        render_mode="none",
        autostart=False,
        capture_replay=True,
    )
    if replay is not None:
        replay.write_replay((run_dir / "replay.json.z").resolve().as_uri())
    end = getattr(policy, "_on_episode_end", None)
    if callable(end):
        end()
    return result.steps


def _make_run_id(scenario_name: str) -> str:
    return f"{scenario_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _write_result_json(
    run_dir: Path,
    scenario: Scenario,
    assertion_results: list[Any],
    *,
    started_at: str,
    duration_s: float,
    steps: int,
    status: str,
) -> None:
    body = {
        "run_id": run_dir.name,
        "scenario": scenario.name,
        "started_at": started_at,
        "duration_s": duration_s,
        "steps": steps,
        "cogs": scenario.cogs,
        "mission": scenario.mission,
        "variants": list(scenario.variants),
        "seed": scenario.seed,
        "policy_kwargs": dict(scenario.policy_kwargs),
        "status": status,
        "assertions": [dataclasses.asdict(r) for r in assertion_results],
    }
    (run_dir / "result.json").write_text(json.dumps(body, indent=2))


def run_scenario(
    scenario: Scenario,
    *,
    steps_override: int | None = None,
    runs_root: Path | None = None,
    skip_assertions: bool = False,
) -> Run:
    """Run a scenario and return the Run view."""
    _validate_policy_kwargs(scenario.policy_kwargs)
    runs_root = Path(runs_root) if runs_root is not None else Path("runs")
    run_id = _make_run_id(scenario.name)
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Build + configure the mission.
    mission = resolve_mission(scenario.mission, cogs=scenario.cogs)
    if scenario.variants:
        mission = mission.with_variants(list(scenario.variants))
    if scenario.mission_overrides:
        mission = mission.model_copy(update=scenario.mission_overrides)
    for vname, patches in scenario.variant_overrides.items():
        variant = mission._base_variants[vname]
        for k, v in patches.items():
            setattr(variant, k, v)

    # Materialize env config and apply setup hook (config-level).
    env_cfg = mission.make_env()
    steps = steps_override if steps_override is not None else scenario.steps
    env_cfg.game.max_steps = steps
    if scenario.setup is not None:
        scenario.setup(env_cfg)

    # Run one episode via the mettagrid library driver.
    spec = PolicySpec(
        class_path="cvc_policy.cogamer_policy.CvCPolicy",
        init_kwargs={"record_dir": str(run_dir), **scenario.policy_kwargs},
    )
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    if scenario.tps > 0:
        spec = PolicySpec(
            class_path=spec.class_path,
            init_kwargs={**spec.init_kwargs, "tps": scenario.tps},
        )
    steps_run = _drive_rollout(env_cfg=env_cfg, spec=spec, run_dir=run_dir, seed=scenario.seed)
    duration_s = time.time() - t0

    # Load Run, evaluate assertions.
    run = Run(run_dir)
    assertion_results: list[Any] = []
    status = "passed"
    if not skip_assertions:
        for assertion in scenario.assertions:
            ar = assertion(run)
            assertion_results.append(ar)
            if not ar.passed:
                status = "failed"
    _write_result_json(
        run_dir,
        scenario,
        assertion_results,
        started_at=started_at,
        duration_s=duration_s,
        steps=steps_run,
        status=status,
    )
    # Auto-render the HTML report so users don't need a separate `cgp view`
    # step. result.json is already on disk, so a render crash doesn't lose
    # assertion results — we let it propagate (no try/except masking).
    render_report(run_dir)
    # Re-load Run so callers see the freshly-written result.json.
    return Run(run_dir)


__all__ = ["run_scenario", "resolve_mission"]
