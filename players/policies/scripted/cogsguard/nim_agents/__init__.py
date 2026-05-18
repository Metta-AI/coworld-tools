"""Nim-based agent policies for CoGames."""

from policies.scripted.cogsguard.nim_agents import agents  # noqa: F401

__all__ = [
    "RandomAgentsMultiPolicy",
    "ThinkyAgentsMultiPolicy",
    "RaceCarAgentsMultiPolicy",
    "CogsguardAlignAllAgentsMultiPolicy",
    "NlankyAgentsMultiPolicy",
]

# Re-export the policy classes for convenience
from policies.scripted.cogsguard.nim_agents.agents import (  # noqa: F401
    CogsguardAlignAllAgentsMultiPolicy,
    NlankyAgentsMultiPolicy,
    RaceCarAgentsMultiPolicy,
    RandomAgentsMultiPolicy,
    ThinkyAgentsMultiPolicy,
)
