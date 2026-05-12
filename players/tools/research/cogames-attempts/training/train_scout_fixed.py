#!/usr/bin/env python3
"""Scout training v5: original tutorial design (ARENA map + scout_gained=10.0).

The scout tutorial was originally designed for:
  - COGSGUARD_ARENA (50x50) — NOT MACHINA_1 (88x88)
  - scout_gained=10.0 — NOT 2.0 (was nerfed in commit fe0772fb8f)

Recent changes (Feb 25) broke it by switching to a 3x larger map AND
reducing the reward 5x. This run restores the original design.
"""

import torch
import pufferlib.vector as pvector
from pufferlib import pufferl
from pufferlib.pufferlib import set_buffers

from cogames.cogs_vs_clips.clip_difficulty import EASY
from cogames.cogs_vs_clips.cog import CogConfig, CogTeam
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


class OriginalScoutRewards(CoGameMissionVariant):
    """Original scout rewards with scout_gained=10.0 (pre-nerf)."""
    name: str = "original_scout_rewards"
    description: str = "Scout rewards with original scout_gained=10.0."

    def modify_env(self, mission: CvCMission, env: MettaGridConfig) -> None:
        for agent_cfg in env.game.agents:
            rewards = dict(agent_cfg.rewards)
            # Original weights from commit ddfa0204b7 (Feb 6)
            rewards["scout_gained"] = reward(stat("scout.gained"), weight=10.0)
            rewards["scout_lost"] = reward(stat("scout.lost"), weight=-10.0)
            rewards["cell_visited"] = reward(stat("cell.visited"), weight=0.00001)
            for other_role in ("miner", "scrambler", "aligner"):
                rewards[f"{other_role}_gained"] = reward(stat(f"{other_role}.gained"), weight=-1.0)
            agent_cfg.rewards = rewards


NUM_AGENTS = 4
MAX_STEPS = 1000
SEED = 42
TOTAL_TIMESTEPS = 10_000_000  # Same as tutorial scripts

mission = CvCMission(
    name="scout_tutorial_v5",
    description="Original scout tutorial: ARENA map + scout_gained=10.0.",
    site=COGSGUARD_ARENA,  # 50x50 (original), NOT MACHINA_1 (88x88)
    num_cogs=NUM_AGENTS,
    max_steps=MAX_STEPS,
    teams={"cogs": CogTeam(name="cogs", num_agents=NUM_AGENTS, wealth=3, initial_hearts=0)},
    variants=[
        EASY,
        OriginalScoutRewards(),
    ],
)

env_cfg: MettaGridConfig = mission.make_env()

print(f"Site: COGSGUARD_ARENA (50x50)")
print(f"Map builder: {type(env_cfg.game.map_builder).__name__}")
print(f"Max steps: {env_cfg.game.max_steps}")
print(f"Num agents: {env_cfg.game.num_agents}")
print(f"Events: {list(env_cfg.game.events.keys())[:5]}...")


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
    ent_coef=0.01,
    vtrace_rho_clip=1.0,
    vtrace_c_clip=1.0,
    prio_alpha=0.8,
    prio_beta0=0.2,
    data_dir="./train_dir",
    checkpoint_interval=50,
    max_minibatch_size=32768,
)

print(f"\nStarting training: {TOTAL_TIMESTEPS:,} steps")
print(f"Batch size: {BATCH_SIZE}, Minibatch: {MINIBATCH_SIZE}")

trainer = pufferl.PuffeRL(train_config, vecenv, net)

while trainer.global_step < train_config["total_timesteps"]:
    trainer.evaluate()
    trainer.train()
    if trainer.global_step % (BATCH_SIZE * 10) == 0:
        trainer.print_dashboard()

trainer.close()
print(f"\nTraining complete. Steps: {trainer.global_step}")
print(f"Checkpoints in: ./train_dir/")
