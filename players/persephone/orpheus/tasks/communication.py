"""Chat packet task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from orpheus.task import ActCommand, Task
from orpheus.types import View

WHISPER_CHAT_COOLDOWN_TICKS = 48
GLOBAL_CHAT_COOLDOWN_TICKS = 240


@dataclass(frozen=True)
class SendMessageTask(Task):
    """Send a chat packet when channel assertions and cooldown allow it."""

    text: str
    channel: str = "auto"

    valid_views: ClassVar[frozenset[View]] = frozenset(
        {View.WHISPER, View.GLOBAL_CHAT, View.PLAYING}
    )

    def select_action(self, belief_state, action_memory) -> ActCommand:
        del action_memory

        cooldowns = getattr(belief_state, "cooldowns", {})
        if cooldowns.get("chat", 0) > 0:
            return ActCommand()

        in_whisper = bool(getattr(belief_state, "in_whisper", False))
        if self.channel == "chatroom" and not in_whisper:
            return ActCommand()
        if self.channel == "global" and in_whisper:
            return ActCommand()

        # Intentional task-layer exception: chat cooldown is a local transport
        # throttle, so the task writes it after emitting a PACKET_CHAT command.
        cooldowns["chat"] = (
            WHISPER_CHAT_COOLDOWN_TICKS
            if in_whisper
            else GLOBAL_CHAT_COOLDOWN_TICKS
        )
        belief_state.cooldowns = cooldowns
        return ActCommand(buttons=0, chat_text=self.text)


__all__ = [
    "WHISPER_CHAT_COOLDOWN_TICKS",
    "GLOBAL_CHAT_COOLDOWN_TICKS",
    "SendMessageTask",
]
