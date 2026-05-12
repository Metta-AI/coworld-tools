#!/usr/bin/env python3
"""Evaluate a scout checkpoint: per-agent scout gear tracking via observations.

Usage: python eval_scout.py [checkpoint_path]
If no checkpoint, runs with random policy.

IMPORTANT: game/cogs/scout.amount is the HUB's scout inventory (always 0).
We track per-agent scout gear via observation tokens: inv:scout (feat 37) at
self position (6,6).
"""

import sys
import numpy as np
import torch
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
from mettagrid.policy.policy_env_interface import PolicyEnvInterface


class ScoutSurvivalReward(CoGameMissionVariant):
    name: str = "scout_survival_reward"
    description: str = "scout_gained=10.0 + heart.gained=1.0"

    def modify_env(self, mission, env):
        for ac in env.game.agents:
            ac.rewards = {
                "scout_gained": reward(stat("scout.gained"), weight=10.0),
                "heart_gained": reward(stat("heart.gained"), weight=1.0),
            }


NUM_AGENTS = 4
NUM_EPISODES = 5
MAX_STEPS = 1000

# Observation feature indices
FEAT_TAG = 7
FEAT_INV_SCOUT = 37
TAG_C_SCOUT = 13
CENTER_ROW = 6
CENTER_COL = 6
COORD_GLOBAL = 254
COORD_EMPTY = 255


def check_scout_gear(obs, agent_idx):
    """Check if agent has scout gear from observation tokens."""
    o = obs[agent_idx]
    for t in range(o.shape[0]):
        coord = int(o[t, 0])
        feat = int(o[t, 1])
        val = int(o[t, 2])
        if coord == COORD_EMPTY:
            break
        if coord == COORD_GLOBAL:
            continue
        row = (coord >> 4) & 0x0F
        col = coord & 0x0F
        if feat == FEAT_INV_SCOUT and row == CENTER_ROW and col == CENTER_COL:
            return val
    return 0


def main():
    checkpoint_path = sys.argv[1] if len(sys.argv) > 1 else None

    mission = CvCMission(
        name="scout_eval",
        description="Scout evaluation.",
        site=COGSGUARD_ARENA,
        num_cogs=NUM_AGENTS,
        max_steps=MAX_STEPS,
        teams={"cogs": CogTeam(name="cogs", num_agents=NUM_AGENTS, wealth=3, initial_hearts=0)},
        variants=[EASY, ScoutSurvivalReward()],
    )
    cfg = mission.make_env()

    # Load policy if checkpoint provided
    policy = None
    pei = None
    if checkpoint_path:
        sim = Simulator()
        sim.add_event_handler(StatsTracker(NoopStatsWriter()))
        sim.add_event_handler(EarlyResetHandler())
        tmp_env = MettaGridPufferEnv(sim, cfg.model_copy(deep=True), buf=None, seed=0)
        pei = PolicyEnvInterface.from_mg_cfg(tmp_env.env_cfg)
        tmp_env.close()

        from cogames.policy.tutorial_policy import TutorialPolicyNet
        device = "cuda" if torch.cuda.is_available() else "cpu"
        policy = TutorialPolicyNet(pei).to(device)
        ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
        if "model_state_dict" in ckpt:
            policy.load_state_dict(ckpt["model_state_dict"])
        elif "agent_state_dict" in ckpt:
            policy.load_state_dict(ckpt["agent_state_dict"])
        else:
            policy.load_state_dict(ckpt)
        policy.eval()
        print("Loaded checkpoint:", checkpoint_path)
        print("Device:", device)
    else:
        print("No checkpoint — running random policy")

    print("=" * 60)
    print("Episodes: {}, Max steps: {}, Agents: {}".format(NUM_EPISODES, MAX_STEPS, NUM_AGENTS))
    print("=" * 60)

    all_scout_gained = []
    all_total_reward = []
    all_survival = []

    for ep in range(NUM_EPISODES):
        sim = Simulator()
        sim.add_event_handler(StatsTracker(NoopStatsWriter()))
        sim.add_event_handler(EarlyResetHandler())
        env = MettaGridPufferEnv(sim, cfg.model_copy(deep=True), buf=None, seed=ep)
        obs, info = env.reset()

        scout_gained = [0] * NUM_AGENTS
        had_scout = [False] * NUM_AGENTS
        total_reward = np.zeros(NUM_AGENTS)
        steps = 0
        device = next(policy.parameters()).device if policy else "cpu"
        # Initialize LSTM state as dict (in-place updated by forward)
        state = {
            "lstm_h": torch.zeros(NUM_AGENTS, 1, 512, device=device),
            "lstm_c": torch.zeros(NUM_AGENTS, 1, 512, device=device),
        } if policy else None

        for step in range(MAX_STEPS):
            if policy is not None:
                with torch.no_grad():
                    obs_t = torch.tensor(obs, dtype=torch.float32).to(device)
                    logits, values = policy(obs_t, state)
                    probs = torch.softmax(logits, dim=-1)
                    actions = torch.multinomial(probs, 1).squeeze(-1).cpu().numpy()
            else:
                actions = np.random.randint(0, 5, size=NUM_AGENTS)

            obs, rewards, dones, truncs, infos = env.step(actions)
            total_reward += rewards
            steps += 1

            # Track per-agent scout gear acquisition
            for a in range(NUM_AGENTS):
                has_now = check_scout_gear(obs, a) > 0
                if has_now and not had_scout[a]:
                    scout_gained[a] += 1
                    had_scout[a] = True
                elif not has_now:
                    had_scout[a] = False

            if all(dones) or all(truncs):
                break

        all_scout_gained.append(scout_gained)
        all_total_reward.append(total_reward.copy())
        all_survival.append(steps)

        print("Ep {}: steps={}, scout_gained={}, total_reward={}".format(
            ep, steps, scout_gained,
            ["%.2f" % r for r in total_reward]
        ))

        env.close()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    sg = np.array(all_scout_gained)
    tr = np.array(all_total_reward)
    print("Mean scout gained per agent: {}".format(sg.mean(axis=0)))
    print("Total scout gained (all eps): {}".format(sg.sum()))
    print("Mean reward per agent: {}".format(tr.mean(axis=0).round(2)))
    print("Mean survival (steps): {:.1f}".format(np.mean(all_survival)))

    if sg.sum() > 0:
        print("\n*** SUCCESS: Agents acquired scout gear! ***")
    else:
        print("\n*** FAILURE: No scout gear acquired ***")


if __name__ == "__main__":
    main()
