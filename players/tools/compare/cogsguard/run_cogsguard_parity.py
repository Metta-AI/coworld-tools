#!/usr/bin/env -S uv run
"""Compare action/move parity between two CoGsGuard policies."""

from __future__ import annotations

import argparse
import importlib
from collections import Counter
from typing import Any, Optional

from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.parity_metrics import (
    diff_action_counts,
    move_success_rate,
    update_action_counts,
    update_move_stats,
)

from mettagrid.policy.loader import initialize_or_load_policy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.policy.prepare_policy_spec import prefer_installed_package_code
from mettagrid.simulator.rollout import Rollout
from mettagrid.util.uri_resolvers.schemes import policy_spec_from_uri


class RecordingPolicy:
    def __init__(self, policy: Any) -> None:
        self._policy = policy
        self.last_action_name: Optional[str] = None

    def reset(self, simulation: Optional[Any] = None) -> None:
        if simulation is None:
            self._policy.reset()
            return
        self._policy.reset(simulation)

    def step(self, obs: Any) -> Any:
        action = self._policy.step(obs)
        self.last_action_name = action if isinstance(action, str) else action.name
        return action

    def __getattr__(self, name: str) -> Any:
        return getattr(self._policy, name)


def _load_multi_policy(policy_env_info: PolicyEnvInterface, policy_uri: str) -> Any:
    # Local audit tools already imported repo code; prefer that code over bundle-local copies.
    with prefer_installed_package_code():
        policy_spec = policy_spec_from_uri(policy_uri)
        return initialize_or_load_policy(policy_env_info, policy_spec)


def _run_policy(
    *,
    recipe_module: str,
    policy_uri: str,
    num_agents: int,
    max_steps: int,
    steps: int,
    seed: int,
) -> dict[str, object]:
    recipe = importlib.import_module(recipe_module)
    make_env = recipe.make_env
    env_cfg = make_env(num_agents=num_agents, max_steps=max_steps)
    policy_env_info = PolicyEnvInterface.from_mg_cfg(env_cfg)
    multi_policy = _load_multi_policy(policy_env_info, policy_uri)
    agent_policies = [RecordingPolicy(multi_policy.agent_policy(i)) for i in range(num_agents)]
    rollout = Rollout(config=env_cfg, policies=agent_policies, render_mode=None, seed=seed)

    action_counts: Counter[str] = Counter()
    move_stats = {"attempts": 0, "success": 0, "fail": 0}

    for _ in range(steps):
        rollout.step()
        sim = rollout._sim
        action_names = sim.action_names
        for idx, agent in enumerate(rollout._agents):
            action_name = agent_policies[idx].last_action_name
            if action_name is not None:
                update_move_stats(move_stats, action_name, agent.last_action_success)
            last_action_id = agent.global_observations.get("last_action")
            if last_action_id is None:
                continue
            action_id = int(last_action_id)
            if action_id < 0 or action_id >= len(action_names):
                continue
            executed_action_name = action_names[action_id]
            update_action_counts(action_counts, executed_action_name)

    return {"policy_uri": policy_uri, "action_counts": action_counts, "move_stats": move_stats}


def _print_summary(label: str, stats: dict[str, object], top_actions: int) -> None:
    policy_uri = stats["policy_uri"]
    action_counts: Counter[str] = stats["action_counts"]
    move_stats = stats["move_stats"]
    total_actions = sum(action_counts.values())
    success_rate = move_success_rate(move_stats)

    print(f"{label}")
    print(f"- policy_uri: {policy_uri}")
    print(f"- total_actions: {total_actions}")
    print(
        f"- move_attempts: {move_stats['attempts']} "
        f"move_success: {move_stats['success']} "
        f"move_fail: {move_stats['fail']} "
        f"move_success_rate: {success_rate:.3f}"
    )
    if action_counts:
        top = action_counts.most_common(top_actions)
        formatted = ", ".join(f"{name}:{count}" for name, count in top)
        print(f"- top_actions: {formatted}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--agents", type=int, default=10)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--recipe", default="recipes.experiment.cogsguard")
    parser.add_argument("--policy-a", default="metta://policy/role_nim")
    parser.add_argument("--policy-b", default="metta://policy/role")
    parser.add_argument("--top-actions", type=int, default=5)
    parser.add_argument("--top-deltas", type=int, default=5)
    args = parser.parse_args()

    stats_a = _run_policy(
        recipe_module=args.recipe,
        policy_uri=args.policy_a,
        num_agents=args.agents,
        max_steps=args.max_steps,
        steps=args.steps,
        seed=args.seed,
    )
    stats_b = _run_policy(
        recipe_module=args.recipe,
        policy_uri=args.policy_b,
        num_agents=args.agents,
        max_steps=args.max_steps,
        steps=args.steps,
        seed=args.seed,
    )

    print("Cogsguard parity summary")
    _print_summary("Policy A", stats_a, args.top_actions)
    _print_summary("Policy B", stats_b, args.top_actions)

    deltas = diff_action_counts(
        stats_a["action_counts"],
        stats_b["action_counts"],
        top_n=args.top_deltas,
    )
    if deltas:
        formatted = ", ".join(f"{name}:{delta:+d}" for name, delta in deltas)
        print(f"- top_action_deltas (A-B): {formatted}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
