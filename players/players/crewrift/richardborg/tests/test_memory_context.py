from __future__ import annotations

from players.crewrift.richardborg.perception.entities import VoteCandidate, VotingState
from players.crewrift.richardborg.strategy.meeting import (
    MeetingDecision,
    MeetingLLMResult,
)
from players.crewrift.richardborg.types import (
    ActionState,
    Belief,
    PlayerEvent,
    PlayerRecord,
)
from players.crewrift.richardborg.memory.context import (
    serialize_richard_meeting_context,
)
from players.crewrift.richardborg.modes import AttendMeetingMode


class _FakeMeetingClient:
    enabled = True
    disabled_reason = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def decide(self, context: dict, *, trigger: str) -> MeetingLLMResult:
        self.calls.append((trigger, context))
        return MeetingLLMResult(
            decision=MeetingDecision(
                action="send_chat", chat_text="red was with green"
            ),
            model="fake-haiku",
            latency_ms=1.0,
        )


def _belief() -> Belief:
    belief = Belief(
        phase="Voting",
        phase_start_tick=10,
        last_tick=34,
        total_player_count=8,
    )
    belief.voting = VotingState(
        timer_present=True,
        self_marker_color="blue",
        candidates=(
            VoteCandidate(slot=0, color="red", alive=True),
            VoteCandidate(slot=1, color="blue", alive=True),
            VoteCandidate(slot=2, color="green", alive=False),
        ),
        cursor_slot=0,
    )
    belief.roster["red"] = PlayerRecord(
        color="red", life_status="alive", last_seen_tick=20
    )
    belief.roster["red"].events.append(
        PlayerEvent(
            kind="proximity",
            start_tick=12,
            end_tick=20,
            target_color="green",
            min_dist=12,
        )
    )
    belief.roster["blue"] = PlayerRecord(
        color="blue", life_status="alive", last_seen_tick=20
    )
    belief.roster["green"] = PlayerRecord(
        color="green", life_status="dead", death_seen_tick=21, death_source="body"
    )
    belief.suspicion = {"red": 0.91}
    return belief


def test_richard_context_adds_markdown_memory_and_canonical_observations() -> None:
    context = serialize_richard_meeting_context(_belief(), trigger="meeting_start")

    assert "Richardborg meeting memory" in context["memory"]["summary_md"]
    assert "Canonical meeting templates" in context["memory"]["templates_md"]
    assert context["memory"]["vote_recommendation"]["target"] == "red"
    assert any(
        observation["text"] == "I saw red with green shortly before green died."
        for observation in context["memory"]["canonical_observations"]
    )


def test_richard_attend_meeting_passes_memory_context_to_llm() -> None:
    client = _FakeMeetingClient()
    mode = AttendMeetingMode(llm_client=client)

    intent = mode.decide(_belief(), ActionState())

    assert intent.kind == "chat"
    assert client.calls[0][0] == "meeting_start"
    assert "memory" in client.calls[0][1]
