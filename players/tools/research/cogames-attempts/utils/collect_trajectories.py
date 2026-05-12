#!/usr/bin/env python3
"""Collect state-action-observation trajectories across environment variants.

For meta-learning world models: generates (obs_t, action_t, obs_{t+1}, reward_t, done_t)
tuples from diverse environment configurations.

Runs on CPU alongside GPU training without interference.
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
    ForestVariant,
    ForcedRoleVibesVariant,
    NumCogsVariant,
)
from mettagrid.envs.early_reset_handler import EarlyResetHandler
from mettagrid.envs.mettagrid_puffer_env import MettaGridPufferEnv
from mettagrid.envs.stats_tracker import StatsTracker
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulator
from mettagrid.util.stats_writer import NoopStatsWriter


# ---------------------------------------------------------------------------
# Environment variant grid
# ---------------------------------------------------------------------------

def build_env_configs():
    """Build a diverse set of environment configurations for meta-learning."""
    configs = []

    # Axis 1: Map site
    sites = [
        ("arena", COGSGUARD_ARENA),
        ("machina1", COGSGUARD_MACHINA_1),
    ]

    # Axis 2: Agent counts
    agent_counts = [2, 4, 8]

    # Axis 3: Difficulty
    difficulties = [
        ("easy", EASY),
        ("medium", MEDIUM),
    ]

    # Axis 4: Biomes (Arena only — Machina uses its own layout)
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
                    variants = [diff_variant]
                    if biome_variant is not None:
                        variants.append(biome_variant)

                    max_steps = 500 if site_name == "arena" else 1000

                    mission = CvCMission(
                        name=config_name,
                        description=f"Data collection: {config_name}",
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
# Simple policies for data collection
# ---------------------------------------------------------------------------

def random_policy(n_actions, n_agents):
    """Uniform random actions."""
    return np.random.randint(0, n_actions, size=n_agents, dtype=np.int32)


def biased_move_policy(n_actions, n_agents, step):
    """Mostly moves, occasional noop. Covers more state space than pure random."""
    actions = np.random.randint(1, n_actions, size=n_agents, dtype=np.int32)  # skip noop
    # 10% chance of noop
    noop_mask = np.random.random(n_agents) < 0.1
    actions[noop_mask] = 0
    return actions


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def collect_episode(env_cfg, n_agents, seed, policy_fn):
    """Run one episode, return per-step trajectory data."""
    sim = Simulator()
    sim.add_event_handler(StatsTracker(NoopStatsWriter()))
    sim.add_event_handler(EarlyResetHandler())
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

    # Stack into arrays
    trajectory = {
        "obs": np.stack(obs_list),          # (T, n_agents, 200, 3) uint8
        "actions": np.stack(action_list),    # (T, n_agents) int32
        "rewards": np.stack(reward_list),    # (T, n_agents) float32
        "dones": np.stack(done_list),        # (T, n_agents) bool
        "next_obs_final": obs.copy(),        # final observation
    }
    return trajectory, step


def collect_variant(config_name, mission, n_agents, n_episodes, output_dir, base_seed):
    """Collect trajectories for one environment variant."""
    env_cfg = mission.make_env()
    variant_dir = output_dir / config_name
    variant_dir.mkdir(parents=True, exist_ok=True)

    total_steps = 0
    episode_lengths = []

    for ep in range(n_episodes):
        seed = base_seed + ep
        traj, steps = collect_episode(
            env_cfg, n_agents, seed,
            policy_fn=biased_move_policy,
        )
        total_steps += steps
        episode_lengths.append(steps)

        # Save compressed
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
        "base_seed": base_seed,
        "policy": "biased_move",
    }
    with open(variant_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    return total_steps


def main():
    parser = argparse.ArgumentParser(description="Collect trajectory data for meta-learning")
    parser.add_argument("--episodes", type=int, default=10, help="Episodes per variant")
    parser.add_argument("--output", type=str, default="./trajectory_data", help="Output directory")
    parser.add_argument("--seed", type=int, default=42, help="Base random seed")
    parser.add_argument("--variants", type=str, default=None,
                        help="Comma-separated list of variant name prefixes to collect (default: all)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    configs = build_env_configs()
    if args.variants:
        prefixes = [p.strip() for p in args.variants.split(",")]
        configs = [(n, m, a) for n, m, a in configs if any(n.startswith(p) for p in prefixes)]

    print(f"Collecting {args.episodes} episodes for {len(configs)} environment variants")
    print(f"Output: {output_dir}")
    print(f"Variants: {[c[0] for c in configs]}")
    print()

    grand_total = 0
    for i, (config_name, mission, n_agents) in enumerate(configs):
        t0 = time.time()
        print(f"[{i+1}/{len(configs)}] {config_name} (n_agents={n_agents})...", end=" ", flush=True)

        steps = collect_variant(
            config_name, mission, n_agents,
            n_episodes=args.episodes,
            output_dir=output_dir,
            base_seed=args.seed + i * 1000,
        )
        grand_total += steps
        elapsed = time.time() - t0
        print(f"{steps:,} steps in {elapsed:.1f}s ({steps/elapsed:.0f} steps/s)")

    # Save global metadata
    global_meta = {
        "total_variants": len(configs),
        "episodes_per_variant": args.episodes,
        "total_steps": grand_total,
        "base_seed": args.seed,
        "configs": [c[0] for c in configs],
    }
    with open(output_dir / "collection_metadata.json", "w") as f:
        json.dump(global_meta, f, indent=2)

    print(f"\nDone! {grand_total:,} total steps across {len(configs)} variants")
    print(f"Data saved to: {output_dir}")


if __name__ == "__main__":
    main()
