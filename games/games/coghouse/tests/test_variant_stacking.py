"""Stack public variants on the default mission and confirm they compose."""

from __future__ import annotations

import cogame  # noqa: F401
from cogame.game import MyMission


def test_easy_plus_big_map_composes() -> None:
    mission = MyMission.create(num_agents=2, max_steps=200).with_variants(["easy", "big_map"])
    env = mission.make_env()

    # big_map scales num_agents to 4; easy bumps each agent's HP initial to 5.
    assert env.game.num_agents == 4
    assert len(env.game.agents) == 4
    for agent in env.game.agents:
        assert agent.inventory.initial["hp"] == 5

    # The env label is stamped from the mission name; variants are applied but
    # don't rename the mission. Still, confirm the label exists.
    assert env.label is not None


def test_hard_halves_max_steps() -> None:
    mission = MyMission.create(num_agents=2, max_steps=200).with_variants(["hard"])
    env = mission.make_env()
    assert env.game.max_steps == 100
