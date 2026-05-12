#!/usr/bin/env python3
"""Collect state-action-observation trajectories v3 — trained agent policies.

Uses Path B kickstarted LSTM checkpoints (miner, aligner, scrambler) instead of
random/biased-move policy. Produces higher-quality data for MAML / in-context
meta-learning.

Changes from v2:
- Trained LSTM policies replace biased_move_policy
- Agent counts: n=4, n=8 only (skip n=2 to keep all 3 roles present)
- Role assignment maps per agent count
- 100 episodes per variant (configurable)
- Metadata includes checkpoint info and role assignments

Usage (on AWS):
    python collect_trajectories_v3.py \
        --miner-checkpoint train_dir/177368621007/model_012208.pt \
        --aligner-checkpoint train_dir/177369502719/model_012208.pt \
        --scrambler-checkpoint train_dir/177376078024/model_012208.pt \
        --episodes 100 \
        --output ./trajectory_data_v3
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
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
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulator
from mettagrid.util.stats_writer import NoopStatsWriter


# ---------------------------------------------------------------------------
# Role assignment maps
# ---------------------------------------------------------------------------

ROLE_MAPS = {
    4: {0: "miner", 1: "aligner", 2: "scrambler", 3: "scrambler"},
    8: {
        0: "miner", 1: "miner",
        2: "aligner", 3: "aligner", 4: "aligner",
        5: "scrambler", 6: "scrambler", 7: "scrambler",
    },
}


# ---------------------------------------------------------------------------
# Environment variant grid
# ---------------------------------------------------------------------------

def build_env_configs():
    """Build diverse environment configurations with EnergizedVariant."""
    configs = []

    sites = [
        ("arena", COGSGUARD_ARENA),
        ("machina1", COGSGUARD_MACHINA_1),
    ]

    agent_counts = [4, 8]  # Skip n=2 — need all 3 roles present

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
                    variants = [diff_variant, EnergizedVariant()]
                    if biome_variant is not None:
                        variants.append(biome_variant)

                    max_steps = 500 if site_name == "arena" else 1000

                    mission = CvCMission(
                        name=config_name,
                        description=f"Data collection v3: {config_name}",
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
# Policy wrapper — handles raw numpy obs + LSTM state management
# ---------------------------------------------------------------------------

class TrainedRolePolicy:
    """Wraps a mettagrid LSTMPolicyNet checkpoint for raw-obs stepping with state."""

    def __init__(self, checkpoint_path, pei, device="cpu"):
        from mettagrid.policy.lstm import LSTMPolicyNet

        self._device = torch.device(device)
        self._action_names = pei.action_names
        self._n_actions = len(self._action_names)
        self._hidden_size = 128  # LSTMPolicyNet default

        # Build LSTMPolicyNet and load checkpoint
        net = LSTMPolicyNet(pei)
        state_dict = torch.load(str(checkpoint_path), map_location=self._device)
        net.load_state_dict(state_dict)
        self._net = net.to(self._device)
        self._net.eval()

        # Per-agent LSTM hidden states: {agent_id: {"lstm_h": tensor, "lstm_c": tensor}}
        self._agent_states = {}

    def reset(self):
        """Clear all agent hidden states for a new episode."""
        self._agent_states = {}

    def _initial_state(self):
        """Create zero-initialized LSTM state dict for one agent."""
        h = torch.zeros(1, self._hidden_size, device=self._device)
        c = torch.zeros(1, self._hidden_size, device=self._device)
        return {"lstm_h": h, "lstm_c": c}

    def get_action(self, agent_id, obs_np):
        """Get action index for one agent given raw obs (200, 3) uint8 array."""
        obs_tensor = torch.as_tensor(
            obs_np, dtype=torch.float32, device=self._device
        ).unsqueeze(0)  # (1, 200, 3)

        # Get or initialize LSTM state for this agent
        if agent_id not in self._agent_states:
            self._agent_states[agent_id] = self._initial_state()

        state_dict = self._agent_states[agent_id]

        with torch.no_grad():
            logits, _ = self._net.forward_eval(obs_tensor, state_dict)
            # state_dict is updated in-place by forward_eval
            dist = torch.distributions.Categorical(logits=logits)
            action_idx = int(dist.sample().item())

        return max(0, min(action_idx, self._n_actions - 1))


def load_trained_policies(pei, miner_ckpt, aligner_ckpt, scrambler_ckpt, device="cpu"):
    """Load 3 LSTM checkpoint policies as TrainedRolePolicy wrappers."""
    policies = {}
    for role, ckpt_path in [("miner", miner_ckpt), ("aligner", aligner_ckpt),
                            ("scrambler", scrambler_ckpt)]:
        policies[role] = TrainedRolePolicy(ckpt_path, pei, device=device)
    return policies


# ---------------------------------------------------------------------------
# Data collection with trained policies
# ---------------------------------------------------------------------------

def collect_episode_trained(env_cfg, n_agents, seed, policies, role_map, pei):
    """Run one episode with trained LSTM policies, return per-step trajectory."""
    sim = Simulator()
    sim.add_event_handler(StatsTracker(NoopStatsWriter()))
    env = MettaGridPufferEnv(sim, env_cfg, seed=seed)

    obs, _ = env.reset()
    for p in policies.values():
        p.reset()

    obs_list = []
    action_list = []
    reward_list = []
    done_list = []

    step = 0
    done_all = False

    while not done_all:
        actions = np.zeros(n_agents, dtype=np.int32)
        for agent_id in range(n_agents):
            role = role_map[agent_id]
            actions[agent_id] = policies[role].get_action(agent_id, obs[agent_id])

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


def collect_variant(config_name, mission, n_agents, n_episodes, output_dir, base_seed,
                    policies, pei):
    """Collect trajectories for one environment variant using trained policies."""
    env_cfg = mission.make_env()
    variant_dir = output_dir / config_name
    variant_dir.mkdir(parents=True, exist_ok=True)

    role_map = ROLE_MAPS[n_agents]
    total_steps = 0
    episode_lengths = []

    for ep in range(n_episodes):
        seed = base_seed + ep

        traj, steps = collect_episode_trained(
            env_cfg, n_agents, seed, policies, role_map, pei
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
        "policy": "kickstarted_heterogeneous",
        "role_map": {str(k): v for k, v in role_map.items()},
        "energized": True,
    }
    with open(variant_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    return total_steps


def main():
    parser = argparse.ArgumentParser(
        description="Collect trajectory data v3 (trained agent policies)"
    )
    parser.add_argument("--miner-checkpoint", type=str, required=True,
                        help="Path to miner LSTM checkpoint (.pt)")
    parser.add_argument("--aligner-checkpoint", type=str, required=True,
                        help="Path to aligner LSTM checkpoint (.pt)")
    parser.add_argument("--scrambler-checkpoint", type=str, required=True,
                        help="Path to scrambler LSTM checkpoint (.pt)")
    parser.add_argument("--episodes", type=int, default=100,
                        help="Episodes per variant (default: 100)")
    parser.add_argument("--output", type=str, default="./trajectory_data_v3",
                        help="Output directory")
    parser.add_argument("--seed", type=int, default=2000, help="Base random seed")
    parser.add_argument("--variants", type=str, default=None,
                        help="Comma-separated variant name prefixes (default: all)")
    parser.add_argument("--device", type=str, default="cpu",
                        help="Torch device for policy inference (cpu or cuda)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    configs = build_env_configs()
    if args.variants:
        prefixes = [p.strip() for p in args.variants.split(",")]
        configs = [(n, m, a) for n, m, a in configs
                   if any(n.startswith(p) for p in prefixes)]

    print(f"Collecting {args.episodes} episodes for {len(configs)} environment variants")
    print(f"Output: {output_dir}")
    print(f"Policy: kickstarted heterogeneous (miner + aligner + scrambler)")
    print(f"Device: {args.device}")
    print(f"Checkpoints:")
    print(f"  miner:     {args.miner_checkpoint}")
    print(f"  aligner:   {args.aligner_checkpoint}")
    print(f"  scrambler: {args.scrambler_checkpoint}")
    print()

    # Load policies once — reused across all variants
    # Use the first config to get PolicyEnvInterface (obs/action specs are the same)
    first_env_cfg = configs[0][1].make_env()
    pei = PolicyEnvInterface.from_mg_cfg(first_env_cfg)

    print("Loading trained policies...", flush=True)
    policies = load_trained_policies(
        pei, args.miner_checkpoint, args.aligner_checkpoint,
        args.scrambler_checkpoint, device=args.device,
    )
    print("Policies loaded.\n")

    grand_total = 0
    for i, (config_name, mission, n_agents) in enumerate(configs):
        t0 = time.time()
        role_desc = "1M+1A+2S" if n_agents == 4 else "2M+3A+3S"
        print(f"[{i+1}/{len(configs)}] {config_name} (n={n_agents}, {role_desc})...",
              end=" ", flush=True)

        steps = collect_variant(
            config_name, mission, n_agents,
            n_episodes=args.episodes,
            output_dir=output_dir,
            base_seed=args.seed + i * 1000,
            policies=policies,
            pei=pei,
        )
        grand_total += steps
        elapsed = time.time() - t0
        print(f"{steps:,} steps in {elapsed:.1f}s ({steps/elapsed:.0f} sps)")

    # Global metadata
    global_meta = {
        "version": 3,
        "total_variants": len(configs),
        "episodes_per_variant": args.episodes,
        "total_steps": grand_total,
        "base_seed": args.seed,
        "energized": True,
        "policy": "kickstarted_heterogeneous",
        "checkpoints": {
            "miner": args.miner_checkpoint,
            "aligner": args.aligner_checkpoint,
            "scrambler": args.scrambler_checkpoint,
        },
        "role_maps": {str(k): {str(ak): av for ak, av in v.items()}
                      for k, v in ROLE_MAPS.items()},
        "agent_counts": [4, 8],
        "difficulties": ["easy", "medium", "hard"],
        "configs": [c[0] for c in configs],
    }
    with open(output_dir / "collection_metadata.json", "w") as f:
        json.dump(global_meta, f, indent=2)

    print(f"\nDone! {grand_total:,} total steps across {len(configs)} variants")
    print(f"Data saved to: {output_dir}")


if __name__ == "__main__":
    main()
