#!/usr/bin/env python3
"""Scout kickstart v2: proper cross-entropy loss kickstarting on top of v8 rewards.

v8 result: 170 scout / 20 eps (6.5x random). SUCCESS with pure PPO.
Now adding scripted teacher with cross-entropy loss to see if we can push further.

Teacher logic:
- If agent has scout gear → noop (don't interfere with PPO)
- If c:scout station visible → navigate toward it
- Fallback → move north (toward center where c:scout typically is)

Key differences from failed post-hoc kickstarting:
- CE loss directly shapes policy distribution (not reward shaping)
- Teacher noops after gear obtained (doesn't pollute late-episode signal)
- North fallback is more reasonable than "go east" (c:scout is near center)

KL coef: 1.0, annealed linearly to 0 over first 50% of training.
"""

import numpy as np
import torch
import pufferlib.vector as pvector
from pufferlib import pufferl
from pufferlib.pufferlib import set_buffers

from cogames.cogs_vs_clips.clip_difficulty import EASY
from cogames.cogs_vs_clips.cog import CogTeam
from cogames.cogs_vs_clips.mission import CvCMission
from cogames.cogs_vs_clips.sites import COGSGUARD_ARENA
from cogames.core import CoGameMissionVariant
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.game_value import stat
from mettagrid.config.reward_config import reward
from mettagrid.envs.early_reset_handler import EarlyResetHandler
from mettagrid.envs.mettagrid_puffer_env import MettaGridPufferEnv
from mettagrid.envs.stats_tracker import StatsTracker
from mettagrid.mapgen.mapgen import MapGen
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulator
from mettagrid.util.stats_writer import NoopStatsWriter


# ============================================================
# Scripted Scout Teacher
# ============================================================

TAG_FEAT = 7          # feature index for "tag"
CSCOUT_TAG = 13       # tag value for c:scout station
INV_SCOUT_FEAT = 37   # feature index for inv:scout
CENTER_ROW = 6        # center of 13x13 observation grid
CENTER_COL = 6
COORD_EMPTY = 255     # no more tokens
COORD_GLOBAL = 254    # global (non-spatial) token

# Actions: 0=noop, 1=north, 2=south, 3=west, 4=east
ACT_NOOP = 0
ACT_NORTH = 1
ACT_SOUTH = 2
ACT_WEST = 3
ACT_EAST = 4


def _teacher_action(tokens):
    """Compute teacher action for a single observation.

    Args:
        tokens: [200, 3] int array — (coord, feature_id, value)

    Returns:
        int action index
    """
    has_scout = False
    scout_row, scout_col = None, None

    for t in range(tokens.shape[0]):
        coord, feat, val = tokens[t, 0], tokens[t, 1], tokens[t, 2]
        if coord == COORD_EMPTY:
            break
        if coord == COORD_GLOBAL:
            continue

        row = (coord >> 4) & 0x0F
        col = coord & 0x0F

        # Check if agent already has scout gear at center (self) position
        if feat == INV_SCOUT_FEAT and row == CENTER_ROW and col == CENTER_COL and val > 0:
            has_scout = True

        # Find c:scout station location
        if feat == TAG_FEAT and val == CSCOUT_TAG:
            scout_row, scout_col = row, col

    # If agent already has gear, don't interfere — let PPO handle
    if has_scout:
        return ACT_NOOP

    # If c:scout station is visible, navigate toward it
    if scout_row is not None:
        dr = scout_row - CENTER_ROW
        dc = scout_col - CENTER_COL

        if dr == 0 and dc == 0:
            return ACT_NOOP  # already on it

        # Move in dominant direction (same logic as StarterPolicy._move_toward)
        if abs(dr) >= abs(dc):
            return ACT_SOUTH if dr > 0 else ACT_NORTH
        else:
            return ACT_EAST if dc > 0 else ACT_WEST

    # Fallback: move north (toward center of map where c:scout typically is)
    return ACT_NORTH


def compute_teacher_actions(observations, device):
    """Compute teacher actions for all stored observations.

    Args:
        observations: [segments, horizon, 200, 3] tensor
        device: torch device

    Returns:
        [segments, horizon] long tensor of action indices
    """
    S, H = observations.shape[:2]
    actions = torch.zeros(S, H, dtype=torch.long, device=device)
    obs_np = observations.cpu().numpy().astype(np.int32)

    for s in range(S):
        for h in range(H):
            actions[s, h] = _teacher_action(obs_np[s, h])

    return actions


# ============================================================
# Environment Setup (same as v8)
# ============================================================

class ScoutDominantReward(CoGameMissionVariant):
    """scout_gained=10.0 dominant, heart.gained=0.1 as stabilizer only."""
    name: str = "scout_dominant_reward"
    description: str = "scout_gained=10.0, heart.gained=0.1"

    def modify_env(self, mission: CvCMission, env: MettaGridConfig) -> None:
        for agent_cfg in env.game.agents:
            agent_cfg.rewards = {
                "scout_gained": reward(stat("scout.gained"), weight=10.0),
                "heart_gained": reward(stat("heart.gained"), weight=0.1),
            }


NUM_AGENTS = 4
MAX_STEPS = 1000
SEED = 42
TOTAL_TIMESTEPS = 10_000_000

mission = CvCMission(
    name="scout_kickstart_v2",
    description="Scout kickstart v2: v8 rewards + CE teacher loss.",
    site=COGSGUARD_ARENA,
    num_cogs=NUM_AGENTS,
    max_steps=MAX_STEPS,
    teams={"cogs": CogTeam(name="cogs", num_agents=NUM_AGENTS, wealth=3, initial_hearts=0)},
    variants=[
        EASY,
        ScoutDominantReward(),
    ],
)

env_cfg: MettaGridConfig = mission.make_env()
print("Rewards: scout_gained=10.0, heart_gained=0.1 (100:1 ratio)")
print("Kickstarting: CE loss, ks_coef=0.1, anneal over 30%")


def make_env(buf=None, seed=None):
    cfg = env_cfg.model_copy(deep=True)
    map_builder = cfg.game.map_builder
    if isinstance(map_builder, MapGen.Config) and seed is not None:
        map_builder.seed = SEED + seed

    simulator = Simulator()
    simulator.add_event_handler(StatsTracker(NoopStatsWriter()))
    simulator.add_event_handler(EarlyResetHandler())
    env = MettaGridPufferEnv(simulator, cfg, buf=buf, seed=seed or 0)
    set_buffers(env, buf)
    return env


driver_env = make_env(seed=0)
policy_env_info = PolicyEnvInterface.from_mg_cfg(driver_env.env_cfg)
print("Actions:", policy_env_info.action_names)
driver_env.close()

from cogames.policy.tutorial_policy import TutorialPolicyNet

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print("Device:", DEVICE)

net = TutorialPolicyNet(policy_env_info).to(DEVICE)
print("Params:", sum(p.numel() for p in net.parameters()))

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
    total_timesteps=max(TOTAL_TIMESTEPS, BATCH_SIZE),
    batch_size=BATCH_SIZE,
    minibatch_size=MINIBATCH_SIZE,
    bptt_horizon=BPTT_HORIZON,
    seed=SEED,
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
    checkpoint_interval=50,
    max_minibatch_size=32768,
    # Kickstarting params (v2b: reduced from 1.0→0.1 — 1.0 caused entropy collapse)
    ks_coef=0.1,           # CE loss coefficient (gentle nudge, not BC)
    ks_anneal_frac=0.3,    # Anneal to 0 over first 30% of training
)

print("Steps:", TOTAL_TIMESTEPS)
print("KS coef:", train_config["ks_coef"], "anneal frac:", train_config["ks_anneal_frac"])

trainer = pufferl.PuffeRL(train_config, vecenv, net)

# Initialize teacher_actions buffer (must match self.actions shape)
trainer.teacher_actions = None

step_count = 0
while trainer.global_step < train_config["total_timesteps"]:
    trainer.evaluate()

    # Compute teacher actions on collected observations
    trainer.teacher_actions = compute_teacher_actions(trainer.observations, DEVICE)

    trainer.train()
    step_count += 1
    if step_count % 10 == 0:
        trainer.print_dashboard()
        # Log kickstarting progress
        progress = trainer.global_step / train_config["total_timesteps"]
        anneal_frac = train_config["ks_anneal_frac"]
        effective_ks = train_config["ks_coef"] * max(0, 1.0 - progress / anneal_frac)
        print(f"  KS: progress={progress:.1%}, effective_coef={effective_ks:.3f}")

trainer.close()
print("Training complete. Steps:", trainer.global_step)
