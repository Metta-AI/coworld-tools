#!/usr/bin/env python3
"""Machina_1 kickstarting: train roles with built-in scripted teacher CE loss.

Usage:
    python train_machina1_kickstart.py --role miner --ks-coef 0.3 --ks-anneal 0.5
    python train_machina1_kickstart.py --role aligner --ks-coef 0.3 --ks-anneal 0.5
    python train_machina1_kickstart.py --role scrambler --ks-coef 0.3 --ks-anneal 0.5

Requires pufferl.py CE patch (patch_pufferl.py) already applied on AWS.

Teacher logic replicates StarterCogPolicyImpl with preferred_gear, operating
directly on raw [200,3] observation tensors for efficiency.
"""

import argparse
import numpy as np
import torch
import pufferlib.vector as pvector
from pufferlib import pufferl
from pufferlib.pufferlib import set_buffers

from cogames.cogs_vs_clips.clip_difficulty import EASY
from cogames.cogs_vs_clips.cog import CogTeam
from cogames.cogs_vs_clips.mission import CvCMission
from cogames.cogs_vs_clips.sites import COGSGUARD_MACHINA_1
from cogames.cogs_vs_clips.reward_variants import apply_reward_variants
from cogames.core import CoGameMissionVariant
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.envs.early_reset_handler import EarlyResetHandler
from mettagrid.envs.mettagrid_puffer_env import MettaGridPufferEnv
from mettagrid.envs.stats_tracker import StatsTracker
from mettagrid.mapgen.mapgen import MapGen
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulator
from mettagrid.util.stats_writer import NoopStatsWriter


# ============================================================
# Observation Feature IDs (from PolicyEnvInterface dump)
# Verified for cogames 0.18.x — assert at startup
# ============================================================

FEAT_TAG = 7              # "tag" feature
FEAT_INV_HEART = 17       # "inv:heart"
FEAT_INV_ALIGNER = 31     # "inv:aligner"
FEAT_INV_SCRAMBLER = 33   # "inv:scrambler"
FEAT_INV_MINER = 35       # "inv:miner"

# Tag IDs (from PolicyEnvInterface.tags)
TAG_C_ALIGNER = 11        # "type:c:aligner"
TAG_C_MINER = 12          # "type:c:miner"
TAG_C_SCRAMBLER = 14      # "type:c:scrambler"
TAG_HUB = 17              # "type:hub"
TAG_JUNCTION = 18         # "type:junction"
TAG_CARBON_EXT = 15       # "type:carbon_extractor"
TAG_GERMANIUM_EXT = 16    # "type:germanium_extractor"
TAG_OXYGEN_EXT = 19       # "type:oxygen_extractor"
TAG_SILICON_EXT = 21      # "type:silicon_extractor"

EXTRACTOR_TAGS = {TAG_CARBON_EXT, TAG_GERMANIUM_EXT, TAG_OXYGEN_EXT, TAG_SILICON_EXT}
JUNCTION_TAGS = {TAG_JUNCTION}
HEART_SOURCE_TAGS = {TAG_HUB}

ROLE_GEAR_STATION = {
    "miner": {TAG_C_MINER},
    "aligner": {TAG_C_ALIGNER},
    "scrambler": {TAG_C_SCRAMBLER},
}

ROLE_INV_FEAT = {
    "miner": FEAT_INV_MINER,
    "aligner": FEAT_INV_ALIGNER,
    "scrambler": FEAT_INV_SCRAMBLER,
}

COORD_EMPTY = 255
COORD_GLOBAL = 254

# Actions
ACT_NOOP = 0
ACT_NORTH = 1
ACT_SOUTH = 2
ACT_WEST = 3
ACT_EAST = 4

# Wander pattern (rotating directions)
WANDER_DIRS = [ACT_EAST, ACT_SOUTH, ACT_WEST, ACT_NORTH]
WANDER_STEPS = 8


def verify_feature_ids(pei):
    """Assert that hardcoded feature IDs match the environment."""
    assert pei.obs_features[FEAT_TAG].name == "tag", f"Expected tag at {FEAT_TAG}, got {pei.obs_features[FEAT_TAG].name}"
    assert pei.obs_features[FEAT_INV_HEART].name == "inv:heart", f"Expected inv:heart at {FEAT_INV_HEART}"
    assert pei.obs_features[FEAT_INV_ALIGNER].name == "inv:aligner", f"Expected inv:aligner at {FEAT_INV_ALIGNER}"
    assert pei.obs_features[FEAT_INV_SCRAMBLER].name == "inv:scrambler", f"Expected inv:scrambler at {FEAT_INV_SCRAMBLER}"
    assert pei.obs_features[FEAT_INV_MINER].name == "inv:miner", f"Expected inv:miner at {FEAT_INV_MINER}"
    assert pei.tags[TAG_C_ALIGNER] == "type:c:aligner", f"Expected type:c:aligner at {TAG_C_ALIGNER}"
    assert pei.tags[TAG_C_MINER] == "type:c:miner", f"Expected type:c:miner at {TAG_C_MINER}"
    assert pei.tags[TAG_C_SCRAMBLER] == "type:c:scrambler", f"Expected type:c:scrambler at {TAG_C_SCRAMBLER}"
    assert pei.tags[TAG_HUB] == "type:hub", f"Expected type:hub at {TAG_HUB}"
    assert pei.tags[TAG_JUNCTION] == "type:junction", f"Expected type:junction at {TAG_JUNCTION}"
    print("Feature ID verification passed.")


# ============================================================
# Scripted Role Teacher
# ============================================================

class RoleTeacher:
    """Scripted teacher that replicates StarterCogPolicyImpl logic on raw tensors."""

    def __init__(self, role, center_row, center_col):
        self.role = role
        self.center_row = center_row
        self.center_col = center_col
        self.gear_station_tags = ROLE_GEAR_STATION[role]
        self.inv_feat = ROLE_INV_FEAT[role]

        # Per-agent wander state: (direction_index, steps_remaining)
        self._wander = {}

    def _get_wander_action(self, agent_key):
        if agent_key not in self._wander:
            self._wander[agent_key] = [agent_key % len(WANDER_DIRS), WANDER_STEPS]
        state = self._wander[agent_key]
        if state[1] <= 0:
            state[0] = (state[0] + 1) % len(WANDER_DIRS)
            state[1] = WANDER_STEPS
        action = WANDER_DIRS[state[0]]
        state[1] -= 1
        return action

    def _move_toward(self, row, col, agent_key):
        dr = row - self.center_row
        dc = col - self.center_col
        if dr == 0 and dc == 0:
            return ACT_NOOP
        if abs(dr) >= abs(dc):
            return ACT_SOUTH if dr > 0 else ACT_NORTH
        else:
            return ACT_EAST if dc > 0 else ACT_WEST

    def _find_closest_tag(self, tokens, target_tags):
        best_row, best_col = None, None
        best_dist = 999
        for t in range(tokens.shape[0]):
            coord, feat, val = int(tokens[t, 0]), int(tokens[t, 1]), int(tokens[t, 2])
            if coord == COORD_EMPTY:
                break
            if coord == COORD_GLOBAL:
                continue
            if feat != FEAT_TAG:
                continue
            if val not in target_tags:
                continue
            row = (coord >> 4) & 0x0F
            col = coord & 0x0F
            dist = abs(row - self.center_row) + abs(col - self.center_col)
            if dist < best_dist:
                best_dist = dist
                best_row, best_col = row, col
        return best_row, best_col

    def compute_action(self, tokens, agent_key=0):
        """Compute teacher action for one observation.

        Args:
            tokens: [200, 3] int array (coord, feature_id, value)
            agent_key: unique agent identifier for wander state

        Returns:
            int action index
        """
        has_gear = False
        has_heart = False

        for t in range(tokens.shape[0]):
            coord, feat, val = int(tokens[t, 0]), int(tokens[t, 1]), int(tokens[t, 2])
            if coord == COORD_EMPTY:
                break
            if coord == COORD_GLOBAL:
                continue
            row = (coord >> 4) & 0x0F
            col = coord & 0x0F
            if row != self.center_row or col != self.center_col:
                continue
            # Center token = self inventory
            if feat == self.inv_feat and val > 0:
                has_gear = True
            if feat == FEAT_INV_HEART and val > 0:
                has_heart = True

        # Decision logic (mirrors StarterCogPolicyImpl.step_with_state)
        if not has_gear:
            # Go get our role gear
            target_tags = self.gear_station_tags
        elif self.role == "miner":
            # Miner with gear → go to extractors
            target_tags = EXTRACTOR_TAGS
        elif self.role in ("aligner", "scrambler"):
            # Aligner/scrambler with gear → junction if has heart, else hub for heart
            target_tags = JUNCTION_TAGS if has_heart else HEART_SOURCE_TAGS
        else:
            target_tags = set()

        row, col = self._find_closest_tag(tokens, target_tags)
        if row is not None:
            return self._move_toward(row, col, agent_key)
        return self._get_wander_action(agent_key)


def compute_teacher_actions(observations, device, teacher):
    """Compute teacher actions for all stored observations.

    Args:
        observations: [segments, horizon, num_tokens, 3] tensor
        device: torch device
        teacher: RoleTeacher instance

    Returns:
        [segments, horizon] long tensor of action indices
    """
    S, H = observations.shape[:2]
    actions = torch.zeros(S, H, dtype=torch.long, device=device)
    obs_np = observations.cpu().numpy().astype(np.int32)

    for s in range(S):
        for h in range(H):
            actions[s, h] = teacher.compute_action(obs_np[s, h], agent_key=s)

    return actions


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Machina_1 kickstarting with scripted teacher")
    parser.add_argument("--role", required=True, choices=["miner", "aligner", "scrambler"])
    parser.add_argument("--ks-coef", type=float, default=0.3, help="CE loss coefficient")
    parser.add_argument("--ks-anneal", type=float, default=0.5, help="Fraction of training to anneal teacher")
    parser.add_argument("--steps", type=int, default=50_000_000, help="Total training steps")
    parser.add_argument("--num-agents", type=int, default=8, help="Number of agents")
    parser.add_argument("--checkpoint-interval", type=int, default=50, help="Checkpoint every N epochs")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"=== Machina_1 Kickstart: {args.role} ===")
    print(f"ks_coef={args.ks_coef}, ks_anneal={args.ks_anneal}, steps={args.steps}")

    # ---- Mission setup ----
    mission = CvCMission(
        name=f"{args.role}_machina1_ks",
        description=f"Machina_1 {args.role} training with kickstarting",
        site=COGSGUARD_MACHINA_1,
        num_cogs=args.num_agents,
        max_steps=10000,
        teams={"cogs": CogTeam(name="cogs", num_agents=args.num_agents, wealth=1)},
        variants=[EASY],
    )
    env_cfg: MettaGridConfig = mission.make_env()

    # Apply role-specific reward variant
    apply_reward_variants(env_cfg, variants=[args.role])
    print(f"Rewards configured for role: {args.role}")

    # ---- Env factory ----
    def make_env(buf=None, seed=None):
        cfg = env_cfg.model_copy(deep=True)
        map_builder = cfg.game.map_builder
        if isinstance(map_builder, MapGen.Config) and seed is not None:
            map_builder.seed = args.seed + seed
        simulator = Simulator()
        simulator.add_event_handler(StatsTracker(NoopStatsWriter()))
        simulator.add_event_handler(EarlyResetHandler())
        env = MettaGridPufferEnv(simulator, cfg, buf=buf, seed=seed or 0)
        set_buffers(env, buf)
        return env

    # ---- Policy env info + verification ----
    driver_env = make_env(seed=0)
    pei = PolicyEnvInterface.from_mg_cfg(driver_env.env_cfg)
    verify_feature_ids(pei)
    center_row = pei.obs_height // 2
    center_col = pei.obs_width // 2
    print(f"Obs grid: {pei.obs_height}x{pei.obs_width}, center: ({center_row},{center_col})")
    print(f"Actions: {pei.action_names}")
    driver_env.close()

    # ---- Teacher ----
    teacher = RoleTeacher(args.role, center_row, center_col)
    print(f"Teacher: {args.role} (gear station tags={teacher.gear_station_tags})")

    # ---- Student network ----
    # Use LSTMPolicy (same as cogames train default: class=lstm)
    from mettagrid.policy.lstm import LSTMPolicy

    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {DEVICE}")

    student_policy = LSTMPolicy(pei, device=DEVICE)
    net = student_policy.network()
    net.to(DEVICE)
    print(f"Params: {sum(p.numel() for p in net.parameters()):,}")

    # ---- Vectorized env ----
    NUM_ENVS = 4
    vecenv = pvector.make(
        make_env, num_envs=NUM_ENVS, num_workers=1, batch_size=NUM_ENVS,
        backend=pvector.Serial,
    )

    BPTT_HORIZON = 64
    BATCH_SIZE = max(4096, vecenv.num_agents * BPTT_HORIZON)
    MINIBATCH_SIZE = min(4096, BATCH_SIZE)

    train_config = dict(
        env="cogames.cogs_vs_clips",
        device=DEVICE,
        total_timesteps=max(args.steps, BATCH_SIZE),
        batch_size=BATCH_SIZE,
        minibatch_size=MINIBATCH_SIZE,
        bptt_horizon=BPTT_HORIZON,
        seed=args.seed,
        use_rnn=True,
        torch_deterministic=True,
        cpu_offload=False,
        compile=False,
        optimizer="adam",
        learning_rate=0.00092,
        anneal_lr=True,
        min_lr_ratio=0.0,
        adam_beta1=0.95,
        adam_beta2=0.999,
        adam_eps=1e-8,
        precision="float32",
        gamma=0.995,
        gae_lambda=0.90,
        update_epochs=1,
        clip_coef=0.2,
        vf_coef=2.0,
        vf_clip_coef=0.2,
        max_grad_norm=1.5,
        ent_coef=0.05,
        vtrace_rho_clip=1.0,
        vtrace_c_clip=1.0,
        prio_alpha=0.8,
        prio_beta0=0.2,
        data_dir="./train_dir",
        checkpoint_interval=args.checkpoint_interval,
        max_minibatch_size=32768,
        # Kickstarting params
        ks_coef=args.ks_coef,
        ks_anneal_frac=args.ks_anneal,
    )

    # ---- Training loop ----
    trainer = pufferl.PuffeRL(train_config, vecenv, net)
    trainer.teacher_actions = None

    print(f"\nStarting training: {args.steps:,} steps")
    print(f"KS: coef={args.ks_coef}, anneal_frac={args.ks_anneal}")

    step_count = 0
    while trainer.global_step < train_config["total_timesteps"]:
        trainer.evaluate()
        trainer.teacher_actions = compute_teacher_actions(trainer.observations, DEVICE, teacher)
        trainer.train()

        step_count += 1
        if step_count % 10 == 0:
            trainer.print_dashboard()
            progress = trainer.global_step / train_config["total_timesteps"]
            effective_ks = args.ks_coef * max(0, 1.0 - progress / args.ks_anneal)
            print(f"  KS: progress={progress:.1%}, effective_coef={effective_ks:.3f}")

    trainer.close()
    print(f"\nTraining complete. Steps: {trainer.global_step:,}")


if __name__ == "__main__":
    main()
