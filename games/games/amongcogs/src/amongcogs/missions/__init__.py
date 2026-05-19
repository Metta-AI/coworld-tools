"""Among Us mission definitions."""

from amongcogs.missions.mission import AmongUsGame


def make_basic_mission(num_agents: int = 12, max_steps: int = 400) -> AmongUsGame:
    return AmongUsGame.create(num_agents=num_agents, max_steps=max_steps)


__all__ = ["AmongUsGame", "make_basic_mission"]
