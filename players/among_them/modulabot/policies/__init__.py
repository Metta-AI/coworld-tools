"""Policy modules.

Each policy is a single class with a ``decide(bot) -> int`` entrypoint that
returns a BitWorld action index. The orchestrator in :mod:`modulabot.bot`
picks which one to call based on ``Bot.role`` and ``Perception.phase``.

Policies are deliberately stateless objects — all state lives on the
:class:`~modulabot.state.Bot`. This lets the same policy instance handle
any number of agents (shared fake-task tuning, shared chat templates, ...),
and makes swapping policies a one-line change in
:class:`~modulabot.bot.BotCore`.
"""

from .crewmate import CrewmatePolicy
from .imposter import ImposterPolicy
from .voting import VotingPolicy

__all__ = ["CrewmatePolicy", "ImposterPolicy", "VotingPolicy"]
