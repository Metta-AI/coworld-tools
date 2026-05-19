"""Run a short headless episode to confirm the mission is playable end-to-end."""

from __future__ import annotations

from mettagrid.simulator.simulator import Simulator

import cogame_euchre  # noqa: F401
from cogame_euchre.game import EuchreMission


def test_default_mission_runs_ten_ticks() -> None:
    mission = EuchreMission.create(max_steps=20)
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
