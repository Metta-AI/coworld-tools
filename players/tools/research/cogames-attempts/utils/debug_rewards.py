"""Debug script to track step-by-step rewards around scout gear acquisition."""
import numpy as np
from cogames.cogs_vs_clips.clip_difficulty import EASY
from cogames.cogs_vs_clips.cog import CogTeam
from cogames.cogs_vs_clips.mission import CvCMission
from cogames.cogs_vs_clips.sites import COGSGUARD_ARENA
from cogames.core import CoGameMissionVariant
from mettagrid.config.game_value import stat
from mettagrid.config.reward_config import reward
from mettagrid.envs.mettagrid_puffer_env import MettaGridPufferEnv
from mettagrid.simulator import Simulator
from mettagrid.envs.stats_tracker import StatsTracker
from mettagrid.envs.early_reset_handler import EarlyResetHandler
from mettagrid.util.stats_writer import NoopStatsWriter


class OriginalScoutRewards(CoGameMissionVariant):
    name: str = "osr"
    description: str = "sr"

    def modify_env(self, mission, env):
        for ac in env.game.agents:
            r = dict(ac.rewards)
            r["scout_gained"] = reward(stat("scout.gained"), weight=10.0)
            r["scout_lost"] = reward(stat("scout.lost"), weight=-10.0)
            r["cell_visited"] = reward(stat("cell.visited"), weight=0.00001)
            for role in ("miner", "scrambler", "aligner"):
                r[role + "_gained"] = reward(stat(role + ".gained"), weight=-1.0)
            ac.rewards = r


mission = CvCMission(
    name="rwd_debug",
    description="d",
    site=COGSGUARD_ARENA,
    num_cogs=4,
    max_steps=200,
    teams={"cogs": CogTeam(name="cogs", num_agents=4, wealth=3, initial_hearts=0)},
    variants=[EASY, OriginalScoutRewards()],
)
cfg = mission.make_env()
sim = Simulator()
sim.add_event_handler(StatsTracker(NoopStatsWriter()))
sim.add_event_handler(EarlyResetHandler())
env = MettaGridPufferEnv(sim, cfg, buf=None, seed=42)
obs, info = env.reset()

has_scout = [False] * 4
total_reward = np.zeros(4)
print("Tracking rewards for 200 steps with random actions...")
print("=" * 70)

for step in range(200):
    actions = np.random.randint(0, 5, size=4)
    obs, rewards, dones, truncs, infos = env.step(actions)
    total_reward += rewards

    for a in range(4):
        had = has_scout[a]
        for t in range(obs[a].shape[0]):
            coord = int(obs[a][t, 0])
            feat = int(obs[a][t, 1])
            val = int(obs[a][t, 2])
            if coord == 255:
                break
            if coord == 254:
                continue
            row = (coord >> 4) & 0x0F
            col = coord & 0x0F
            if feat == 37 and row == 6 and col == 6:
                has_scout[a] = val > 0

        if rewards[a] != 0 or (has_scout[a] != had):
            tag = "**SCOUT**" if (has_scout[a] != had) else ""
            print(
                "Step {:3d} Agent {}: reward={:10.6f} scout={} (was {}) {}".format(
                    step, a, rewards[a], has_scout[a], had, tag
                )
            )

print("=" * 70)
print("Total rewards per agent:", total_reward)
print("Final scout gear:", has_scout)
env.close()
