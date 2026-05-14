"""Modulabot: a modular scripted agent for cogames Among Them.

Python port of the Nim modulabot architecture. The public entry point for
the cogames tournament loader is :class:`~modulabot.policy.AmongThemPolicy`.

See :mod:`modulabot.state` for the sub-record state layout,
:mod:`modulabot.policies` for the crewmate / imposter / voting decision
trees, and :mod:`modulabot.perception` for observation parsing.
"""

from .policy import AmongThemPolicy

__all__ = ["AmongThemPolicy"]
