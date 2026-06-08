from players.crewrift.crewriftstarter import llm_meeting


def _context() -> dict:
    return {
        "constraints": {"valid_vote_targets": ["red", "blue", "skip"]},
        "state": {"fallback_vote": "skip"},
    }


def test_disabled_helper_returns_wait(monkeypatch):
    for name in (
        "CREWRIFTSTARTER_LLM_MEETINGS",
        "USE_BEDROCK",
        "CLAUDE_CODE_USE_BEDROCK",
    ):
        monkeypatch.delenv(name, raising=False)

    decision = llm_meeting.decide(_context())

    assert decision["action"] == "wait"
    assert decision["vote_target"] == ""


def test_validate_accepts_legal_vote_target():
    decision = llm_meeting._validate_decision(
        {
            "action": "submit_vote",
            "chat_text": "I saw red near body",
            "vote_target": "red",
            "reason": "body evidence",
            "confidence": 0.8,
        },
        _context(),
    )

    assert decision == {
        "schema_version": 1,
        "action": "submit_vote",
        "chat_text": "I saw red near body",
        "vote_target": "red",
        "reason": "body evidence",
        "confidence": 0.8,
    }


def test_validate_demotes_low_confidence_submit_vote():
    decision = llm_meeting._validate_decision(
        {
            "action": "submit_vote",
            "vote_target": "red",
            "reason": "weak evidence",
            "confidence": 0.4,
        },
        _context(),
    )

    assert decision["action"] == "set_tentative_vote"
    assert decision["vote_target"] == "red"


def test_validate_demotes_submit_vote_without_confidence():
    decision = llm_meeting._validate_decision(
        {
            "action": "submit_vote",
            "vote_target": "red",
            "reason": "missing confidence",
        },
        _context(),
    )

    assert decision["action"] == "set_tentative_vote"
    assert decision["vote_target"] == "red"


def test_validate_rejects_illegal_vote_target():
    decision = llm_meeting._validate_decision(
        {
            "action": "submit_vote",
            "vote_target": "green",
            "reason": "made up",
            "confidence": 0.9,
        },
        _context(),
    )

    assert decision["action"] == "wait"
    assert decision["vote_target"] == ""
