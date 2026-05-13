"""Concrete Orpheus task implementations.

Stage 4 tasks use frozen dataclass subclasses of :class:`orpheus.task.Task`.
Parameters are dataclass fields, while ``valid_views`` remains a ``ClassVar``
so task identity is structural and ActionMemory stays task-private.
"""

from __future__ import annotations

from orpheus.idle import IdleTask
from orpheus.tasks.chatroom import (
    CancelEntryTask,
    CreateWhisperTask,
    ExitWhisperTask,
    GrantEntryTask,
    InitiateWhisperTask,
    MoveAndInitiateWhisperTask,
    RendezvousEntrySweepTask,
    RequestEntryTask,
)
from orpheus.tasks.communication import SendMessageTask
from orpheus.tasks.exchange import (
    AcceptColorExchangeTask,
    AcceptRoleExchangeTask,
    OfferColorExchangeTask,
    OfferRoleExchangeTask,
    RevealRoleTask,
    WithdrawColorOfferTask,
    WithdrawRoleOfferTask,
)
from orpheus.tasks.hostage import SelectHostagesTask
from orpheus.tasks.leadership import (
    PassLeadershipTask,
    TakeLeadershipTask,
    VoteUsurpTask,
)
from orpheus.tasks.movement import FollowTask, MoveToTask, WanderTask
from orpheus.tasks.view_management import (
    CloseViewTask,
    OpenGlobalChatTask,
    OpenInfoScreenTask,
)

__all__ = [
    "IdleTask",
    "MoveToTask",
    "FollowTask",
    "WanderTask",
    "OpenGlobalChatTask",
    "OpenInfoScreenTask",
    "CloseViewTask",
    "CreateWhisperTask",
    "InitiateWhisperTask",
    "MoveAndInitiateWhisperTask",
    "RendezvousEntrySweepTask",
    "RequestEntryTask",
    "CancelEntryTask",
    "ExitWhisperTask",
    "GrantEntryTask",
    "OfferColorExchangeTask",
    "AcceptColorExchangeTask",
    "WithdrawColorOfferTask",
    "OfferRoleExchangeTask",
    "AcceptRoleExchangeTask",
    "WithdrawRoleOfferTask",
    "RevealRoleTask",
    "PassLeadershipTask",
    "TakeLeadershipTask",
    "VoteUsurpTask",
    "SelectHostagesTask",
    "SendMessageTask",
]
