#!/usr/bin/env python3
"""Train Cortex (Ag,A,S) policy on CogsGuard with scripted teacher kickstarting.

Uses a scripted economy-chain teacher (dinky-style: half miners, half aligners)
to provide kickstarting signal. No LSTM intermediary — train Cortex directly.

The episode-reset patch (patch_pufferl_v2.py) MUST be applied before running.
Without it, Cortex state corrupts across episode boundaries.

Usage:
    # Train Cortex with scripted teacher kickstarting (default)
    python scripts/training/train_cortex.py --steps 50000000

    # Train without kickstarting (ablation)
    python scripts/training/train_cortex.py --steps 50000000 --no-kickstart

    # Custom Cortex config (Axon-only)
    python scripts/training/train_cortex.py --d-hidden 128 --preset axon --steps 50000000
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import pufferlib.vector as pvector
from pufferlib import pufferl
from pufferlib.pufferlib import set_buffers

from cogames.cogs_vs_clips.clip_difficulty import EASY
from cogames.cogs_vs_clips.cog import CogTeam
from cogames.cogs_vs_clips.mission import CvCMission
from cogames.cogs_vs_clips.reward_variants import apply_reward_variants
from cogames.cogs_vs_clips.sites import COGSGUARD_ARENA
from mettagrid.envs.early_reset_handler import EarlyResetHandler
from mettagrid.envs.mettagrid_puffer_env import MettaGridPufferEnv
from mettagrid.envs.stats_tracker import StatsTracker
from mettagrid.mapgen.mapgen import MapGen
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulator
from mettagrid.util.stats_writer import NoopStatsWriter

# Add scripts/ to path so we can import cortex_policy and scripted_teacher
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "policy"))
from cortex_policy import CortexPolicyNet
from scripted_teacher import compute_teacher_actions


def parse_args():
    p = argparse.ArgumentParser(description="Train Cortex policy on CogsGuard")
    p.add_argument("--steps", type=int, default=50_000_000, help="Total timesteps")
    p.add_argument("--d-hidden", type=int, default=128, help="Cortex hidden dimension (native LSTM uses 128)")
    p.add_argument("--num-layers", type=int, default=1, help="Cortex stack layers (native LSTM uses 1)")
    p.add_argument(
        "--preset", type=str, default="lstm",
        choices=["lstm", "lstm2", "axon", "agas", "agas2"],
        help="Architecture preset: lstm (1-layer), lstm2 (2-layer), axon, agas (1-layer), agas2 (2-layer)",
    )
    p.add_argument("--num-agents", type=int, default=8, help="Agents per env")
    p.add_argument("--num-envs", type=int, default=4, help="Parallel environments")
    p.add_argument("--ent-coef", type=float, default=0.03, help="Entropy coefficient")
    p.add_argument("--update-epochs", type=int, default=3, help="PPO update epochs per batch")
    p.add_argument("--lr", type=float, default=0.00092, help="Learning rate")
    p.add_argument(
        "--variant", type=str, default="milestones",
        help="Reward variant (milestones, credit, etc.)",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--checkpoint-interval", type=int, default=200,
        help="Checkpoint every N updates",
    )
    # Kickstarting
    p.add_argument(
        "--no-kickstart", action="store_true",
        help="Disable scripted teacher kickstarting (ablation)",
    )
    p.add_argument("--ks-coef", type=float, default=0.1, help="Kickstarting CE coefficient")
    p.add_argument(
        "--ks-anneal-frac", type=float, default=0.5,
        help="Fraction of training to anneal kickstarting to 0",
    )
    return p.parse_args()


def verify_episode_reset_patch():
    """Check that the episode-reset patch is applied to pufferl.py."""
    import pufferlib.pufferl as mod
    src = Path(mod.__file__).read_text()
    if "PATCH: zero LSTM state" not in src:
        print("ERROR: Episode-reset patch not applied to pufferl.py!")
        print("Run: python scripts/utils/patch_pufferl_v2.py")
        sys.exit(1)
    print("Episode-reset patch: OK")


def make_mission(args):
    mission = CvCMission(
        name=f"cortex_{args.preset}",
        description=f"Cortex {args.preset} d={args.d_hidden} l={args.num_layers}",
        site=COGSGUARD_ARENA,
        num_cogs=args.num_agents,
        max_steps=1000,
        teams={
            "cogs": CogTeam(
                name="cogs", num_agents=args.num_agents, wealth=3, initial_hearts=0
            )
        },
        variants=[EASY],
    )
    env_cfg = mission.make_env()
    apply_reward_variants(env_cfg, variants=[args.variant])
    return mission, env_cfg


def make_env_fn(env_cfg, seed_base):
    def make_env(buf=None, seed=None):
        cfg = env_cfg.model_copy(deep=True)
        map_builder = cfg.game.map_builder
        if isinstance(map_builder, MapGen.Config) and seed is not None:
            map_builder.seed = seed_base + seed
        simulator = Simulator()
        simulator.add_event_handler(StatsTracker(NoopStatsWriter()))
        simulator.add_event_handler(EarlyResetHandler())
        env = MettaGridPufferEnv(simulator, cfg, buf=buf, seed=seed or 0)
        set_buffers(env, buf)
        return env
    return make_env


def make_train_config(args, vecenv, use_kickstarting=False):
    bptt_horizon = 64
    batch_size = max(4096, vecenv.num_agents * bptt_horizon)
    minibatch_size = min(4096, batch_size)

    config = dict(
        env="cogames.cogs_vs_clips",
        device="cuda" if torch.cuda.is_available() else "cpu",
        total_timesteps=max(args.steps, batch_size),
        batch_size=batch_size,
        minibatch_size=minibatch_size,
        bptt_horizon=bptt_horizon,
        seed=args.seed,
        use_rnn=True,
        torch_deterministic=True,
        cpu_offload=False,
        compile=False,
        optimizer="adam",
        learning_rate=args.lr,
        anneal_lr=True,
        min_lr_ratio=0.0,
        adam_beta1=0.95,
        adam_beta2=0.999,
        adam_eps=1e-8,
        precision="float32",
        gamma=0.995,
        gae_lambda=0.90,
        update_epochs=args.update_epochs,
        clip_coef=0.2,
        vf_coef=2.0,
        vf_clip_coef=0.2,
        max_grad_norm=1.5,
        ent_coef=args.ent_coef,
        vtrace_rho_clip=1.0,
        vtrace_c_clip=1.0,
        prio_alpha=0.8,
        prio_beta0=0.2,
        data_dir="./train_dir",
        checkpoint_interval=args.checkpoint_interval,
        max_minibatch_size=32768,
    )

    if use_kickstarting:
        config["ks_coef"] = args.ks_coef
        config["ks_anneal_frac"] = args.ks_anneal_frac

    return config


def train(args, net, vecenv, config, use_kickstarting=False):
    """Run training loop with optional scripted teacher kickstarting."""
    device = config["device"]
    n_params = sum(p.numel() for p in net.parameters())

    label = f"Cortex ({args.preset}, d={args.d_hidden})"
    if use_kickstarting:
        label += " + scripted teacher kickstarting"
    else:
        label += " (no kickstarting)"

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"Parameters: {n_params:,}")
    print(f"Training: {args.steps:,} steps")
    print(f"Batch: {config['batch_size']}, BPTT: {config['bptt_horizon']}")
    print(f"Entropy coef: {args.ent_coef}, LR: {args.lr}")
    if use_kickstarting:
        print(f"Kickstarting: ks_coef={args.ks_coef}, anneal_frac={args.ks_anneal_frac}")
    print()

    trainer = pufferl.PuffeRL(config, vecenv, net)

    step_count = 0
    while trainer.global_step < config["total_timesteps"]:
        trainer.evaluate()

        if use_kickstarting:
            trainer.teacher_actions = compute_teacher_actions(
                trainer.observations, device, step=trainer.global_step
            )

        trainer.train()
        step_count += 1
        if step_count % 10 == 0:
            trainer.print_dashboard()
            # Per-component gradient norms (literature: heterogeneous cells
            # may have mismatched gradient scales — RLBenchNet 2025)
            gnorms = net.gradient_norms()
            parts = [f"{k}={v:.4f}" for k, v in gnorms.items()]
            print(f"  Grad norms: {', '.join(parts)}")
            if use_kickstarting:
                progress = trainer.global_step / config["total_timesteps"]
                eff_ks = args.ks_coef * max(0, 1.0 - progress / args.ks_anneal_frac)
                print(f"  KS: progress={progress:.1%}, effective_coef={eff_ks:.3f}")

    trainer.close()
    print(f"\n{label} complete. Steps: {trainer.global_step:,}")
    return trainer


def main():
    args = parse_args()

    # Verify episode-reset patch
    verify_episode_reset_patch()

    # Build environment
    mission, env_cfg = make_mission(args)
    make_env = make_env_fn(env_cfg, args.seed)

    driver_env = make_env(seed=0)
    policy_env_info = PolicyEnvInterface.from_mg_cfg(driver_env.env_cfg)
    print(f"Actions: {policy_env_info.action_names}")
    print(f"Obs shape: {policy_env_info.observation_space.shape}")
    driver_env.close()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    vecenv = pvector.make(
        make_env,
        num_envs=args.num_envs,
        num_workers=1,
        batch_size=args.num_envs,
        backend=pvector.Serial,
    )

    use_kickstarting = not args.no_kickstart

    net = CortexPolicyNet(
        policy_env_info,
        d_hidden=args.d_hidden,
        num_layers=args.num_layers,
        preset=args.preset,
    ).to(device)

    config = make_train_config(args, vecenv, use_kickstarting=use_kickstarting)
    config["data_dir"] = f"./train_dir/cortex_{args.preset}_{'ks' if use_kickstarting else 'noks'}"

    train(args, net, vecenv, config, use_kickstarting=use_kickstarting)


if __name__ == "__main__":
    main()
