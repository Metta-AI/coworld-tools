"""Agent configuration and scripted policy for the Hunger game."""

from hungercog.agent.hunger_agent.policy import HungerPolicy  # noqa: F401 — registers via metaclass

__all__ = ["HungerPolicy"]
