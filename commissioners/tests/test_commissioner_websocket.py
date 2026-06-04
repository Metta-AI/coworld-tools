from __future__ import annotations

from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from commissioners.common.protocol import (
    CommissionerMessage,
    DivisionInfo,
    EpisodeCompletedResponse,
    EpisodeRequest,
    EpisodeScore,
    LeagueInfo,
    MembershipInfo,
    RoundInfo,
    RoundStart,
    VariantInfo,
)
app = import_module("commissioners.default.default_commissioner.default_commissioner").app


def _round_start_json() -> tuple[dict, list[str]]:
    division_id = uuid4()
    policy_version_ids = [uuid4() for _ in range(2)]
    round_start = RoundStart(
        round_id=uuid4(),
        round_number=1,
        league=LeagueInfo(id=uuid4(), commissioner_config={"num_episodes": 1}),
        divisions=[DivisionInfo(id=division_id, name="Bronze", level=0)],
        memberships=[
            MembershipInfo(id=uuid4(), division_id=division_id, policy_version_id=policy_version_id, is_champion=True)
            for policy_version_id in policy_version_ids
        ],
        recent_results=[],
        variants=[VariantInfo(id="default", name="Default", game_config={"num_agents": 2}, num_agents=2)],
    )
    return round_start.to_json(), [str(policy_version_id) for policy_version_id in policy_version_ids]


def test_healthz() -> None:
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_round_websocket_schedules_and_completes() -> None:
    client = TestClient(app)
    round_start, policy_version_ids = _round_start_json()

    with client.websocket_connect("/round") as websocket:
        websocket.send_json(round_start)
        schedule = websocket.receive_json()
        assert schedule["type"] == "schedule_episodes"
        assert len(schedule["episodes"]) == 1
        assert schedule["episodes"][0]["policy_version_ids"] == policy_version_ids

        websocket.send_json(
            {
                "type": "episode_result",
                "request_id": schedule["episodes"][0]["request_id"],
                "scores": [
                    EpisodeScore(policy_version_id=policy_version_ids[0], score=1.0).model_dump(mode="json"),
                    EpisodeScore(policy_version_id=policy_version_ids[1], score=2.0).model_dump(mode="json"),
                ],
            }
        )
        complete = websocket.receive_json()

    assert complete["type"] == "round_complete"
    rankings = complete["results"][0]["rankings"]
    assert [ranking["policy_version_id"] for ranking in rankings] == [policy_version_ids[1], policy_version_ids[0]]
    assert [ranking["rank"] for ranking in rankings] == [1, 2]


def test_round_websocket_completes_with_zero_counts_when_all_episodes_fail() -> None:
    client = TestClient(app)
    round_start, policy_version_ids = _round_start_json()

    with client.websocket_connect("/round") as websocket:
        websocket.send_json(round_start)
        schedule = websocket.receive_json()
        websocket.send_json(
            {
                "type": "episode_failed",
                "request_id": schedule["episodes"][0]["request_id"],
                "error": "container exited",
            }
        )
        complete = websocket.receive_json()

    assert complete["type"] == "round_complete"
    rankings = complete["results"][0]["rankings"]
    assert [ranking["policy_version_id"] for ranking in rankings] == policy_version_ids
    assert [ranking["score"] for ranking in rankings] == [0.0, 0.0]
    assert [ranking["result_metadata"]["completed_episode_count"] for ranking in rankings] == [0, 0]


def test_round_websocket_deactivates_all_failed_qualifier_memberships() -> None:
    client = TestClient(app)
    qualifier_id = uuid4()
    competition_id = uuid4()
    membership_ids = [uuid4(), uuid4()]
    policy_version_ids = [uuid4(), uuid4()]
    round_start = RoundStart(
        round_id=uuid4(),
        round_number=1,
        league=LeagueInfo(
            id=uuid4(),
            commissioner_config={
                "qualifiers_division_name": "Qualifiers",
                "minimum_champions": 1,
                "qualifiers_minimum_champions": 1,
            },
        ),
        divisions=[
            DivisionInfo(id=qualifier_id, name="Qualifiers", level=-99, type="staging"),
            DivisionInfo(id=competition_id, name="Daily", level=0, type="competition"),
        ],
        memberships=[
            MembershipInfo(id=membership_id, division_id=qualifier_id, policy_version_id=policy_version_id)
            for membership_id, policy_version_id in zip(membership_ids, policy_version_ids, strict=True)
        ],
        recent_results=[],
        variants=[VariantInfo(id="default", name="Default", game_config={"num_agents": 2}, num_agents=2)],
    ).to_json()

    with client.websocket_connect("/round") as websocket:
        websocket.send_json(round_start)
        schedule = websocket.receive_json()
        for episode in schedule["episodes"]:
            websocket.send_json(
                {
                    "type": "episode_failed",
                    "request_id": episode["request_id"],
                    "error": "container exited",
                }
            )
        complete = websocket.receive_json()

    assert complete["type"] == "round_complete"
    changes_by_membership_id = {change["membership_id"]: change for change in complete["membership_changes"]}
    assert set(changes_by_membership_id) == {str(membership_id) for membership_id in membership_ids}
    assert [change["is_active"] for change in changes_by_membership_id.values()] == [False, False]
    assert [change["to_division_id"] for change in changes_by_membership_id.values()] == [None, None]


def test_round_websocket_completes_when_one_episode_fails() -> None:
    client = TestClient(app)
    round_start, policy_version_ids = _round_start_json()
    round_start["league"]["commissioner_config"]["num_episodes"] = 2

    with client.websocket_connect("/round") as websocket:
        websocket.send_json(round_start)
        schedule = websocket.receive_json()
        assert schedule["type"] == "schedule_episodes"
        assert len(schedule["episodes"]) == 2

        websocket.send_json(
            {
                "type": "episode_failed",
                "request_id": schedule["episodes"][0]["request_id"],
                "error": "container exited",
            }
        )
        websocket.send_json(
            {
                "type": "episode_result",
                "request_id": schedule["episodes"][1]["request_id"],
                "scores": [
                    EpisodeScore(policy_version_id=policy_version_ids[0], score=3.0).model_dump(mode="json"),
                    EpisodeScore(policy_version_id=policy_version_ids[1], score=1.0).model_dump(mode="json"),
                ],
            }
        )
        complete = websocket.receive_json()

    assert complete["type"] == "round_complete"
    rankings = complete["results"][0]["rankings"]
    assert [ranking["policy_version_id"] for ranking in rankings] == [policy_version_ids[0], policy_version_ids[1]]
    assert [ranking["result_metadata"]["completed_episode_count"] for ranking in rankings] == [1, 1]


def test_round_websocket_rejects_unknown_episode_result_request_id() -> None:
    client = TestClient(app)
    round_start, _policy_version_ids = _round_start_json()

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/round") as websocket:
            websocket.send_json(round_start)
            websocket.receive_json()
            websocket.send_json(
                {
                    "type": "episode_result",
                    "request_id": "not-scheduled",
                    "scores": [],
                }
            )
            websocket.receive_json()

    assert exc_info.value.code == 1008
    assert "unknown episode request id" in exc_info.value.reason


def test_protocol_accepts_prefixed_round_public_id_and_episode_completed_response() -> None:
    round_info = RoundInfo(
        id=uuid4(),
        public_id="round_abc123",
        division_id=uuid4(),
        round_number=1,
        status="completed",
    )
    parsed = CommissionerMessage.from_json(
        {
            "type": "episode_completed_response",
            "episodes": [
                {
                    "request_id": "retry-1",
                    "variant_id": "default",
                    "policy_version_ids": [str(uuid4()), str(uuid4())],
                }
            ],
        }
    )

    assert round_info.public_id == "round_abc123"
    assert isinstance(parsed, EpisodeCompletedResponse)
    assert isinstance(parsed.episodes[0], EpisodeRequest)
