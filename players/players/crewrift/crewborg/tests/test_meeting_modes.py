"""Attend Meeting / Report Body / Flee mode tests (design §7.1)."""

from __future__ import annotations

from players.crewrift.crewborg.modes import AttendMeetingMode, FleeMode, ReportBodyMode
from players.crewrift.crewborg.perception.entities import VoteCandidate, VotingState
from players.crewrift.crewborg.strategy.meeting import MeetingDecision, MeetingLLMResult
from players.crewrift.crewborg.strategy.meeting.context import serialize_meeting_context
from players.crewrift.crewborg.types import (
    ActionState,
    Belief,
    BodyEntry,
    ChatEvent,
    PlayerRecord,
)


class _FakeMeetingClient:
    enabled = True
    disabled_reason = None

    def __init__(self, decisions: list[MeetingDecision]) -> None:
        self.decisions = list(decisions)
        self.calls: list[tuple[str, dict]] = []

    def decide(self, context: dict, *, trigger: str) -> MeetingLLMResult:
        self.calls.append((trigger, context))
        return MeetingLLMResult(
            decision=self.decisions.pop(0),
            model="fake-haiku",
            latency_ms=1.5,
        )


def _meeting_belief(*, tick: int = 0, start_tick: int = 0) -> Belief:
    belief = Belief(
        phase="Voting",
        phase_start_tick=start_tick,
        last_tick=tick,
        total_player_count=2,
    )
    belief.voting = VotingState(
        timer_present=True,
        self_marker_color="blue",
        candidates=(
            VoteCandidate(slot=0, color="red", alive=True),
            VoteCandidate(slot=1, color="blue", alive=True),
        ),
        cursor_slot=0,
    )
    belief.roster["red"] = PlayerRecord(
        color="red", life_status="alive", last_seen_tick=1
    )
    belief.roster["blue"] = PlayerRecord(
        color="blue", life_status="alive", last_seen_tick=1
    )
    belief.suspicion = {"red": 0.95}
    return belief


def test_attend_meeting_chats_once_then_votes() -> None:
    mode = AttendMeetingMode()
    first = mode.decide(Belief(phase="Voting"), ActionState())
    assert first.kind == "chat" and first.text

    second = mode.decide(Belief(phase="Voting"), ActionState())
    assert second.kind == "vote"
    assert mode.decide(Belief(phase="Voting"), ActionState()).kind == "vote"


def test_attend_meeting_votes_the_top_suspect_when_confident() -> None:
    mode = AttendMeetingMode()
    belief = Belief(phase="Voting")
    belief.suspicion = {"red": 0.95, "blue": 0.2}  # red over the vote bar
    mode.decide(belief, ActionState())  # chat opener
    vote = mode.decide(belief, ActionState())
    assert vote.kind == "vote" and vote.target_color == "red"


def test_attend_meeting_skips_when_no_one_is_suspicious_enough() -> None:
    mode = AttendMeetingMode()
    belief = Belief(phase="Voting")
    belief.suspicion = {"red": 0.4, "blue": 0.2}  # nobody over the vote bar
    mode.decide(belief, ActionState())  # chat opener
    vote = mode.decide(belief, ActionState())
    assert vote.kind == "vote" and vote.target_color is None


def test_attend_meeting_llm_sends_multiple_chats_after_new_chat_and_cooldown() -> None:
    client = _FakeMeetingClient(
        [
            MeetingDecision(
                action="send_chat", chat_text="red, where were you?", vote_target="red"
            ),
            MeetingDecision(
                action="send_chat", chat_text="that route does not clear red"
            ),
        ]
    )
    mode = AttendMeetingMode(llm_client=client)

    first = mode.decide(_meeting_belief(tick=0), ActionState())
    assert first.kind == "chat"
    assert first.text == "red, where were you?"

    belief = _meeting_belief(tick=101)
    belief.chat_log = [ChatEvent(tick=20, speaker_color="red", text="i was nav")]
    second = mode.decide(belief, ActionState())
    assert second.kind == "chat"
    assert second.text == "that route does not clear red"
    assert [trigger for trigger, _ in client.calls] == ["meeting_start", "new_chat"]


def test_attend_meeting_llm_tentative_vote_auto_submits_next_tick() -> None:
    client = _FakeMeetingClient(
        [MeetingDecision(action="set_tentative_vote", vote_target="red")]
    )
    mode = AttendMeetingMode(llm_client=client)

    assert mode.decide(_meeting_belief(tick=0), ActionState()).kind == "idle"

    vote = mode.decide(_meeting_belief(tick=1), ActionState())
    assert vote.kind == "vote"
    assert vote.target_color == "red"


def test_attend_meeting_llm_can_submit_vote_early() -> None:
    client = _FakeMeetingClient(
        [MeetingDecision(action="submit_vote", vote_target="red")]
    )
    mode = AttendMeetingMode(llm_client=client)

    vote = mode.decide(_meeting_belief(tick=0), ActionState())
    assert vote.kind == "vote"
    assert vote.target_color == "red"


def test_attend_meeting_uses_injected_context_serializer() -> None:
    client = _FakeMeetingClient(
        [MeetingDecision(action="send_chat", chat_text="red was with green")]
    )

    def serialize_with_memory(*args, **kwargs):
        context = serialize_meeting_context(*args, **kwargs)
        context["memory"] = {"canonical_observations": ["I saw red with green."]}
        return context

    mode = AttendMeetingMode(
        llm_client=client, context_serializer=serialize_with_memory
    )

    intent = mode.decide(_meeting_belief(tick=0), ActionState())

    assert intent.kind == "chat"
    assert client.calls[0][1]["memory"]["canonical_observations"] == [
        "I saw red with green."
    ]


def test_attend_meeting_llm_keeps_vote_intent_until_action_confirms() -> None:
    client = _FakeMeetingClient(
        [MeetingDecision(action="submit_vote", vote_target="red")]
    )
    mode = AttendMeetingMode(llm_client=client)
    action_state = ActionState()

    first = mode.decide(_meeting_belief(tick=0), action_state)
    assert first.kind == "vote"
    assert first.target_color == "red"

    second = mode.decide(_meeting_belief(tick=1), action_state)
    assert second.kind == "vote"
    assert second.target_color == "red"

    action_state.vote_confirmed = True
    done = mode.decide(_meeting_belief(tick=2), action_state)
    assert done.kind == "idle"


def test_attend_meeting_invalid_llm_decision_falls_back_to_canned_chat() -> None:
    client = _FakeMeetingClient(
        [
            MeetingDecision(
                action="send_chat", chat_text="vote green", vote_target="green"
            )
        ]
    )
    mode = AttendMeetingMode(llm_client=client)

    intent = mode.decide(_meeting_belief(tick=0), ActionState())
    assert intent.kind == "chat"
    assert intent.text == "no read, skipping"


def test_report_body_targets_nearest_visible_body() -> None:
    belief = Belief(self_world_x=100, self_world_y=100, visible_body_ids={2001, 2005})
    belief.bodies[2001] = BodyEntry(
        object_id=2001, color="red", world_x=400, world_y=400, first_seen_tick=1
    )
    belief.bodies[2005] = BodyEntry(
        object_id=2005, color="blue", world_x=110, world_y=100, first_seen_tick=1
    )
    intent = ReportBodyMode().decide(belief, ActionState())
    assert intent.kind == "report" and intent.target_id == 2005  # the nearer body


def test_report_body_idles_with_no_body_in_view() -> None:
    assert ReportBodyMode().decide(Belief(), ActionState()).kind == "idle"


def test_flee_targets_believed_imposter_and_is_dormant_when_empty() -> None:
    belief = Belief(self_world_x=100, self_world_y=100)
    belief.roster["red"] = PlayerRecord(
        object_id=1004,
        color="red",
        facing="left",
        world_x=120,
        world_y=100,
        last_seen_tick=1,
        life_status="alive",
    )
    # Empty evidence stub ⇒ dormant.
    assert FleeMode().decide(belief, ActionState()).kind == "idle"
    # Once a believed imposter exists, flee from it.
    belief.believed_imposters = {"red"}
    intent = FleeMode().decide(belief, ActionState())
    assert intent.kind == "flee_from" and intent.target_color == "red"
