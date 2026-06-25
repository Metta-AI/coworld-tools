"""Run a short headless episode to confirm the mission is playable end-to-end."""

from __future__ import annotations

from mettagrid.simulator.simulator import Simulator

import cogony  # noqa: F401
from cogony.mission import CogonyMission


def test_cogony_runs_ten_ticks() -> None:
    mission = CogonyMission()
    mission.max_steps = 10
    env = mission.make_env()

    simulator = Simulator()
    sim = simulator.new_simulation(env, seed=42)

    ticks = 0
    while not sim.is_done() and ticks < 10:
        for i in range(sim.num_agents):
            sim.agent(i).set_action("noop")
        sim.step()
        ticks += 1

    assert ticks == 10
