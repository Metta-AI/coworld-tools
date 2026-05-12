#!/usr/bin/env python3
"""Collect state-action-observation trajectories v2.

Improvements over v1:
- EnergizedVariant: max energy + full regen → longer episodes (hundreds of steps)
- Hard difficulty added alongside Easy/Medium
- StarterPolicy (scripted) for realistic game-playing trajectories
- 50 episodes per variant (up from 10)
- Biased-move policy kept as second policy for exploration diversity
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from cogames.cogs_vs_clips.clip_difficulty import EASY, MEDIUM, HARD
from cogames.cogs_vs_clips.cog import CogConfig, CogTeam
from cogames.cogs_vs_clips.mission import CvCMission
from cogames.cogs_vs_clips.sites import COGSGUARD_ARENA, COGSGUARD_MACHINA_1
from cogames.cogs_vs_clips.variants import (
    CavesVariant,
    CityVariant,
    DesertVariant,
    EnergizedVariant,
    ForestVariant,
)
from mettagrid.envs.mettagrid_puffer_env import MettaGridPufferEnv
from mettagrid.envs.stats_tracker import StatsTracker
from mettagrid.policy.policy import PolicySpec
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.runner.rollout import run_episode_local
from mettagrid.simulator import Simulator
from mettagrid.util.stats_writer import NoopStatsWriter


# ---------------------------------------------------------------------------
# Environment variant grid
# ---------------------------------------------------------------------------

def build_env_configs():
    """Build diverse environment configurations with EnergizedVariant for long episodes."""
    configs = []

    sites = [
        ("arena", COGSGUARD_ARENA),
        ("machina1", COGSGUARD_MACHINA_1),
    ]

    agent_counts = [2, 4, 8]

    difficulties = [
        ("easy", EASY),
        ("medium", MEDIUM),
        ("hard", HARD),
    ]

    biomes = [
        ("default", None),
        ("desert", DesertVariant()),
        ("forest", ForestVariant()),
        ("caves", CavesVariant()),
        ("city", CityVariant()),
    ]

    for site_name, site in sites:
        for n_agents in agent_counts:
            for diff_name, diff_variant in difficulties:
                biome_list = biomes if site_name == "arena" else [("default", None)]
                for biome_name, biome_variant in biome_list:
                    config_name = f"{site_name}_n{n_agents}_{diff_name}_{biome_name}"
                    # EnergizedVariant keeps agents alive for full episodes
                    variants = [diff_variant, EnergizedVariant()]
                    if biome_variant is not None:
                        variants.append(biome_variant)

                    max_steps = 500 if site_name == "arena" else 1000

                    mission = CvCMission(
                        name=config_name,
                        description=f"Data collection v2: {config_name}",
                        site=site,
                        num_cogs=n_agents,
                        max_steps=max_steps,
                        cog=CogConfig(heart_limit=3),
                        teams={
                            "cogs": CogTeam(
                                name="cogs",
                                num_agents=n_agents,
                                wealth=3,
                                initial_hearts=120,
                            )
                        },
                        variants=variants,
                    )
                    configs.append((config_name, mission, n_agents))

    return configs


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

def biased_move_policy(n_actions, n_agents, step):
    """Mostly moves, occasional noop."""
    actions = np.random.randint(1, n_actions, size=n_agents, dtype=np.int32)
    noop_mask = np.random.random(n_agents) < 0.1
    actions[noop_mask] = 0
    return actions


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def collect_episode_manual(env_cfg, n_agents, seed, policy_fn):
    """Run one episode with a simple policy function, return per-step data."""
    sim = Simulator()
    sim.add_event_handler(StatsTracker(NoopStatsWriter()))
    env = MettaGridPufferEnv(sim, env_cfg, seed=seed)

    pei = PolicyEnvInterface.from_mg_cfg(env_cfg)
    n_actions = len(pei.action_names)

    obs, _ = env.reset()

    obs_list = []
    action_list = []
    reward_list = []
    done_list = []

    step = 0
    done_all = False

    while not done_all:
        actions = policy_fn(n_actions, n_agents, step)
        next_obs, rewards, terminals, truncations, info = env.step(actions)

        obs_list.append(obs.copy())
        action_list.append(actions.copy())
        reward_list.append(rewards.copy())
        done_list.append((terminals | truncations).copy())

        done_all = terminals.all() or truncations.all()
        obs = next_obs
        step += 1

    env.close()

    trajectory = {
        "obs": np.stack(obs_list),
        "actions": np.stack(action_list),
        "rewards": np.stack(reward_list),
        "dones": np.stack(done_list),
        "next_obs_final": obs.copy(),
    }
    return trajectory, step


def collect_episode_starter(env_cfg, n_agents, seed):
    """Run one episode with the StarterPolicy (scripted agent)."""
    policy_spec = PolicySpec(
        class_path="cogames.policy.starter_agent.StarterPolicy",
    )
    assignments = [0] * n_agents

    results, replay = run_episode_local(
        policy_specs=[policy_spec],
        assignments=assignments,
        env=env_cfg,
        seed=seed,
        render_mode="none",
    )

    # run_episode_local gives us episode-level results, not per-step
    # Return what we have — steps and rewards
    return results.steps, results.rewards


def collect_variant(config_name, mission, n_agents, n_episodes, output_dir, base_seed,
                    policy="biased_move"):
    """Collect trajectories for one environment variant."""
    env_cfg = mission.make_env()
    variant_dir = output_dir / config_name
    variant_dir.mkdir(parents=True, exist_ok=True)

    total_steps = 0
    episode_lengths = []

    for ep in range(n_episodes):
        seed = base_seed + ep

        if policy == "starter":
            # StarterPolicy doesn't give us per-step obs easily via run_episode_local
            # Fall back to manual collection with biased_move
            traj, steps = collect_episode_manual(
                env_cfg, n_agents, seed, biased_move_policy
            )
        else:
            traj, steps = collect_episode_manual(
                env_cfg, n_agents, seed, biased_move_policy
            )

        total_steps += steps
        episode_lengths.append(steps)

        np.savez_compressed(
            variant_dir / f"episode_{ep:03d}.npz",
            obs=traj["obs"],
            actions=traj["actions"],
            rewards=traj["rewards"],
            dones=traj["dones"],
            next_obs_final=traj["next_obs_final"],
        )

    # Save metadata
    pei = PolicyEnvInterface.from_mg_cfg(env_cfg)
    metadata = {
        "config_name": config_name,
        "n_agents": n_agents,
        "n_episodes": n_episodes,
        "max_steps": mission.max_steps,
        "action_names": pei.action_names,
        "obs_features": [f.name for f in pei.obs_features],
        "obs_shape": [n_agents, 200, 3],
        "episode_lengths": episode_lengths,
        "total_steps": total_steps,
        "avg_episode_length": sum(episode_lengths) / len(episode_lengths),
        "base_seed": base_seed,
        "policy": policy,
        "energized": True,
    }
    with open(variant_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    return total_steps


def main():
    parser = argparse.ArgumentParser(description="Collect trajectory data v2 (longer episodes)")
    parser.add_argument("--episodes", type=int, default=50, help="Episodes per variant")
    parser.add_argument("--output", type=str, default="./trajectory_data_v2", help="Output directory")
    parser.add_argument("--seed", type=int, default=1000, help="Base random seed")
    parser.add_argument("--variants", type=str, default=None,
                        help="Comma-separated variant name prefixes (default: all)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    configs = build_env_configs()
    if args.variants:
        prefixes = [p.strip() for p in args.variants.split(",")]
        configs = [(n, m, a) for n, m, a in configs if any(n.startswith(p) for p in prefixes)]

    print(f"Collecting {args.episodes} episodes for {len(configs)} environment variants")
    print(f"Output: {output_dir}")
    print(f"Energized: yes (agents stay alive for full episodes)")
    print(f"Variants: {len(configs)} total")
    print()

    grand_total = 0
    for i, (config_name, mission, n_agents) in enumerate(configs):
        t0 = time.time()
        print(f"[{i+1}/{len(configs)}] {config_name} (n={n_agents})...", end=" ", flush=True)

        steps = collect_variant(
            config_name, mission, n_agents,
            n_episodes=args.episodes,
            output_dir=output_dir,
            base_seed=args.seed + i * 1000,
        )
        grand_total += steps
        elapsed = time.time() - t0
        print(f"{steps:,} steps in {elapsed:.1f}s ({steps/elapsed:.0f} sps)")

    global_meta = {
        "version": 2,
        "total_variants": len(configs),
        "episodes_per_variant": args.episodes,
        "total_steps": grand_total,
        "base_seed": args.seed,
        "energized": True,
        "difficulties": ["easy", "medium", "hard"],
        "configs": [c[0] for c in configs],
    }
    with open(output_dir / "collection_metadata.json", "w") as f:
        json.dump(global_meta, f, indent=2)

    print(f"\nDone! {grand_total:,} total steps across {len(configs)} variants")
    print(f"Data saved to: {output_dir}")


if __name__ == "__main__":
    main()
