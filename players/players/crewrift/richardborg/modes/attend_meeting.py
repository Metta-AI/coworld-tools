"""Richardborg meeting mode with observation-summary context."""

from __future__ import annotations

from players.crewrift.crewborg.modes.attend_meeting import (
    AttendMeetingMode as CrewborgAttendMeetingMode,
)
from players.crewrift.crewborg.strategy.meeting import MeetingLLMClient
from players.crewrift.richardborg.memory.context import (
    serialize_richard_meeting_context,
)


class AttendMeetingMode(CrewborgAttendMeetingMode):
    name = "attend_meeting"

    def __init__(
        self, params=None, *, llm_client: MeetingLLMClient | None = None
    ) -> None:
        super().__init__(
            params,
            llm_client=llm_client,
            context_serializer=serialize_richard_meeting_context,
        )
