"""Attend Meeting / Report Body / Flee mode tests (design §7.1)."""

from __future__ import annotations

from players.crewrift.crewborg.modes import AttendMeetingMode, FleeMode, ReportBodyMode
from players.crewrift.crewborg.perception.entities import VoteCandidate, VotingState
from players.crewrift.crewborg.strategy.meeting import (
    MeetingDecision,
    MeetingLLMResult,
    MeetingParams,
    read_meeting_params_from_env,
)
from players.crewrift.crewborg.strategy.meeting.llm import (
    DEFAULT_BEDROCK_MODEL,
    DEFAULT_MEETING_MODEL,
    build_meeting_client,
)
from players.crewrift.crewborg.types import ActionState, Belief, BodyEntry, ChatEvent, PlayerRecord


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


class _FailingMeetingClient:
    """An ``enabled`` client whose every call raises, like an ungated/404 model."""

    enabled = True
    disabled_reason = None

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def decide(self, context: dict, *, trigger: str) -> MeetingLLMResult:
        self.calls += 1
        raise self.exc


class _NotFoundError(Exception):
    status_code = 404


def _meeting_belief(*, tick: int = 0, start_tick: int = 0) -> Belief:
    belief = Belief(phase="Voting", phase_start_tick=start_tick, last_tick=tick, total_player_count=2)
    belief.voting = VotingState(
        timer_present=True,
        self_marker_color="blue",
        candidates=(
            VoteCandidate(slot=0, color="red", alive=True),
            VoteCandidate(slot=1, color="blue", alive=True),
        ),
        cursor_slot=0,
    )
    belief.roster["red"] = PlayerRecord(color="red", life_status="alive", last_seen_tick=1)
    belief.roster["blue"] = PlayerRecord(color="blue", life_status="alive", last_seen_tick=1)
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
            MeetingDecision(action="send_chat", chat_text="red, where were you?", vote_target="red"),
            MeetingDecision(action="send_chat", chat_text="that route does not clear red"),
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


def test_attend_meeting_llm_tentative_vote_auto_submits_near_deadline() -> None:
    client = _FakeMeetingClient([MeetingDecision(action="set_tentative_vote", vote_target="red")])
    mode = AttendMeetingMode(llm_client=client)

    assert mode.decide(_meeting_belief(tick=0), ActionState()).kind == "idle"

    vote = mode.decide(_meeting_belief(tick=193), ActionState())
    assert vote.kind == "vote"
    assert vote.target_color == "red"


def test_attend_meeting_llm_can_submit_vote_early() -> None:
    client = _FakeMeetingClient([MeetingDecision(action="submit_vote", vote_target="red")])
    mode = AttendMeetingMode(llm_client=client)

    vote = mode.decide(_meeting_belief(tick=0), ActionState())
    assert vote.kind == "vote"
    assert vote.target_color == "red"


def test_attend_meeting_invalid_llm_decision_falls_back_to_canned_chat() -> None:
    client = _FakeMeetingClient([MeetingDecision(action="send_chat", chat_text="vote green", vote_target="green")])
    mode = AttendMeetingMode(llm_client=client)

    intent = mode.decide(_meeting_belief(tick=0), ActionState())
    assert intent.kind == "chat"
    assert intent.text == "no read, skipping"


def test_attend_meeting_votes_when_enabled_llm_permanently_fails() -> None:
    # A 404/ungated model that reports enabled must not cost us our vote: the
    # mode latches onto the deterministic chat->vote fallback after the first
    # permanent error rather than idling out the meeting without voting.
    client = _FailingMeetingClient(_NotFoundError("model use case not submitted"))
    mode = AttendMeetingMode(llm_client=client)

    first = mode.decide(_meeting_belief(tick=0), ActionState())
    assert first.kind == "chat"  # meeting_start failed -> deterministic opener
    assert mode._llm_disabled_for_episode is True

    second = mode.decide(_meeting_belief(tick=1), ActionState())
    assert second.kind == "vote"
    assert second.target_color == "red"  # the top suspect


def test_attend_meeting_keeps_voting_in_later_meetings_after_llm_failure() -> None:
    client = _FailingMeetingClient(_NotFoundError("ungated"))
    mode = AttendMeetingMode(llm_client=client)

    mode.decide(_meeting_belief(tick=0), ActionState())  # meeting 1 opener (+ latch)
    mode.decide(_meeting_belief(tick=1), ActionState())  # meeting 1 vote

    # A new meeting (new phase_start_tick) stays on the deterministic fallback
    # without ever calling the broken client again.
    calls_after_meeting_one = client.calls
    opener = mode.decide(_meeting_belief(tick=300, start_tick=300), ActionState())
    assert opener.kind == "chat"
    vote = mode.decide(_meeting_belief(tick=301, start_tick=300), ActionState())
    assert vote.kind == "vote" and vote.target_color == "red"
    assert client.calls == calls_after_meeting_one  # no further LLM calls


def test_attend_meeting_votes_after_repeated_transient_llm_failures() -> None:
    # A transient error (no status_code) latches only after the failure
    # threshold, but still ends in a vote rather than an unvoted meeting.
    client = _FailingMeetingClient(RuntimeError("timeout"))
    mode = AttendMeetingMode(llm_client=client)

    first = mode.decide(_meeting_belief(tick=0), ActionState())  # failure #1 -> chat
    assert first.kind == "chat"
    assert mode._llm_disabled_for_episode is False

    belief = _meeting_belief(tick=13)
    belief.chat_log = [ChatEvent(tick=5, speaker_color="red", text="i was nav")]
    mode.decide(belief, ActionState())  # new_chat trigger -> failure #2 -> latched
    assert mode._llm_disabled_for_episode is True

    vote = mode.decide(_meeting_belief(tick=14), ActionState())
    assert vote.kind == "vote" and vote.target_color == "red"


def test_read_meeting_params_from_env_enables_llm_only_with_key() -> None:
    enabled = read_meeting_params_from_env({"CREWBORG_LLM_MEETINGS": "1", "ANTHROPIC_API_KEY": "secret"})
    assert enabled.use_llm is True

    missing_key = read_meeting_params_from_env({"CREWBORG_LLM_MEETINGS": "1"})
    assert missing_key.use_llm is False


def test_read_meeting_params_from_env_parses_tuning_and_trace() -> None:
    params = read_meeting_params_from_env(
        {
            "CREWBORG_LLM_MEETINGS": "yes",
            "ANTHROPIC_API_KEY": "secret",
            "CREWBORG_LLM_MODEL": "claude-test",
            "CREWBORG_LLM_MAX_TOKENS": "123",
            "CREWBORG_LLM_TEMPERATURE": "0.7",
            "CREWBORG_LLM_TIMEOUT_SECONDS": "9.5",
            "CREWBORG_TRACE": "debug",
        }
    )

    assert params == MeetingParams(
        use_llm=True,
        model="claude-test",
        max_tokens=123,
        temperature=0.7,
        timeout_seconds=9.5,
        trace_raw=True,
    )


def test_attend_meeting_builds_client_from_params() -> None:
    disabled = AttendMeetingMode(MeetingParams(use_llm=False))
    assert disabled._llm_client.enabled is False

    enabled = AttendMeetingMode(MeetingParams(use_llm=True, model="claude-test"))
    assert enabled._llm_client.enabled is True
    assert enabled._llm_client.config.model == "claude-test"


def test_bedrock_flag_enables_llm_without_anthropic_key() -> None:
    # Bedrock authenticates through AWS, so no ANTHROPIC_API_KEY is required, and
    # the flag implies meetings are on without a separate CREWBORG_LLM_MEETINGS.
    params = read_meeting_params_from_env({"USE_BEDROCK": "1"})
    assert params.use_llm is True
    assert params.use_bedrock is True
    assert params.model == DEFAULT_BEDROCK_MODEL


def test_bedrock_flag_aliases_are_accepted() -> None:
    for flag in ("USE_BEDROCK", "CREWBORG_USE_BEDROCK", "CLAUDE_CODE_USE_BEDROCK"):
        params = read_meeting_params_from_env({flag: "true"})
        assert params.use_bedrock is True, flag


def test_explicit_model_overrides_bedrock_default() -> None:
    params = read_meeting_params_from_env({"USE_BEDROCK": "1", "CREWBORG_LLM_MODEL": "custom-profile"})
    assert params.model == "custom-profile"


def test_direct_path_keeps_anthropic_key_requirement() -> None:
    # Without Bedrock, the direct Anthropic backend still needs a key, and the
    # direct model default is used.
    params = read_meeting_params_from_env({"CREWBORG_LLM_MEETINGS": "1", "ANTHROPIC_API_KEY": "secret"})
    assert params.use_bedrock is False
    assert params.model == DEFAULT_MEETING_MODEL


def test_build_meeting_client_propagates_bedrock_flag() -> None:
    client = build_meeting_client(MeetingParams(use_llm=True, use_bedrock=True, model="profile"))
    assert client.enabled is True
    assert client.config.use_bedrock is True
    assert client.config.model == "profile"


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
