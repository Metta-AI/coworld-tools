#!/usr/bin/env python3
"""Scout training v7: scout_gained + heart.gained survival reward.

v6 failed because with ONLY scout_gained=10.0, agents had zero reward signal
(never reached c:scout), causing entropy collapse and a degenerate policy.

v7 adds heart.gained=1.0 as a survival incentive. This keeps agents alive and
exploring the map, increasing the chance of stumbling onto c:scout (which is
only 4 tiles from spawn). The +10.0 scout_gained reward should then bootstrap
deliberate navigation to c:scout.

Changes from v6:
- Added heart.gained=1.0 (survival signal)
- ent_coef=0.05 (higher entropy to prevent collapse)
- 10M steps (same as v6)
"""

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


class ScoutSurvivalReward(CoGameMissionVariant):
    """Scout + survival rewards. No cell_visited, no role penalties."""
    name: str = "scout_survival_reward"
    description: str = "scout_gained=10.0 + heart.gained=1.0 for survival."

    def modify_env(self, mission: CvCMission, env: MettaGridConfig) -> None:
        for agent_cfg in env.game.agents:
            agent_cfg.rewards = {
                "scout_gained": reward(stat("scout.gained"), weight=10.0),
                "heart_gained": reward(stat("heart.gained"), weight=1.0),
            }


NUM_AGENTS = 4
MAX_STEPS = 1000
SEED = 42
TOTAL_TIMESTEPS = 10_000_000

mission = CvCMission(
    name="scout_v7",
    description="Scout v7: scout + survival rewards.",
    site=COGSGUARD_ARENA,
    num_cogs=NUM_AGENTS,
    max_steps=MAX_STEPS,
    teams={"cogs": CogTeam(name="cogs", num_agents=NUM_AGENTS, wealth=3, initial_hearts=0)},
    variants=[
        EASY,
        ScoutSurvivalReward(),
    ],
)

env_cfg: MettaGridConfig = mission.make_env()
print("Site: COGSGUARD_ARENA (50x50)")
print("Rewards: scout_gained=10.0, heart_gained=1.0")


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
print(f"Obs features: {len(policy_env_info.obs_features)}")
print(f"Action names: {policy_env_info.action_names}")
driver_env.close()

from cogames.policy.tutorial_policy import TutorialPolicyNet

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Device: {DEVICE}")

net = TutorialPolicyNet(policy_env_info).to(DEVICE)
print(f"Parameters: {sum(p.numel() for p in net.parameters()):,}")

NUM_ENVS = 4
vecenv = pvector.make(
    make_env,
    num_envs=NUM_ENVS,
    num_workers=1,
    batch_size=NUM_ENVS,
    backend=pvector.Serial,
)

total_agents = vecenv.num_agents
print(f"Total agents: {total_agents}")

BPTT_HORIZON = 64
BATCH_SIZE = max(4096, total_agents * BPTT_HORIZON)
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
    ent_coef=0.05,  # higher to maintain exploration
    vtrace_rho_clip=1.0,
    vtrace_c_clip=1.0,
    prio_alpha=0.8,
    prio_beta0=0.2,
    data_dir="./train_dir",
    checkpoint_interval=50,
    max_minibatch_size=32768,
)

print(f"\nStarting v7 training: {TOTAL_TIMESTEPS:,} steps")
print(f"Batch size: {BATCH_SIZE}, Minibatch: {MINIBATCH_SIZE}")
print(f"ent_coef: {train_config['ent_coef']}")

trainer = pufferl.PuffeRL(train_config, vecenv, net)

while trainer.global_step < train_config["total_timesteps"]:
    trainer.evaluate()
    trainer.train()

    if trainer.global_step % (BATCH_SIZE * 10) == 0:
        trainer.print_dashboard()

trainer.close()
print(f"\nTraining complete. Steps: {trainer.global_step}")
print(f"Checkpoints in: ./train_dir/")
