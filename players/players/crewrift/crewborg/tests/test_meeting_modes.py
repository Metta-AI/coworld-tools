"""Attend Meeting / Report Body / Flee mode tests (design §7.1)."""

from __future__ import annotations

from players.crewrift.crewborg.modes import AttendMeetingMode, FleeMode, ReportBodyMode
from players.crewrift.crewborg.types import ActionState, Belief, BodyEntry, PlayerRecord


def test_attend_meeting_chats_once_then_votes() -> None:
    mode = AttendMeetingMode()
    first = mode.decide(Belief(phase="Voting"), ActionState())
    assert first.kind == "chat" and first.text

    second = mode.decide(Belief(phase="Voting"), ActionState())
    assert second.kind == "vote"
    # Stays on vote thereafter (default skip policy).
    assert mode.decide(Belief(phase="Voting"), ActionState()).kind == "vote"


def test_report_body_targets_nearest_visible_body() -> None:
    belief = Belief(self_world_x=100, self_world_y=100, visible_body_ids={2001, 2005})
    belief.bodies[2001] = BodyEntry(object_id=2001, color="red", world_x=400, world_y=400, first_seen_tick=1)
    belief.bodies[2005] = BodyEntry(object_id=2005, color="blue", world_x=110, world_y=100, first_seen_tick=1)
    intent = ReportBodyMode().decide(belief, ActionState())
    assert intent.kind == "report" and intent.target_id == 2005  # the nearer body


def test_report_body_idles_with_no_body_in_view() -> None:
    assert ReportBodyMode().decide(Belief(), ActionState()).kind == "idle"


def test_flee_targets_believed_imposter_and_is_dormant_when_empty() -> None:
    belief = Belief(self_world_x=100, self_world_y=100)
    belief.roster["red"] = PlayerRecord(
        object_id=1004, color="red", facing="left", world_x=120, world_y=100, last_seen_tick=1,
        life_status="alive",
    )
    # Empty evidence stub ⇒ dormant.
    assert FleeMode().decide(belief, ActionState()).kind == "idle"
    # Once a believed imposter exists, flee from it.
    belief.believed_imposters = {"red"}
    intent = FleeMode().decide(belief, ActionState())
    assert intent.kind == "flee_from" and intent.target_color == "red"
