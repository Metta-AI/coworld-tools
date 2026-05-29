import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from server import create_app  # noqa: E402


def _round_start(*, divisions, memberships, tokens=("", "")):
    return {
        "type": "round_start",
        "round_id": "00000000-0000-0000-0000-000000000000",
        "round_number": 1,
        "league": {"id": "00000000-0000-0000-0000-000000000001", "commissioner_config": {}},
        "divisions": divisions,
        "memberships": memberships,
        "recent_results": [],
        "variants": [{"id": "v", "name": "V", "game_config": {"tokens": list(tokens)}}],
        "state": None,
    }


def test_healthz_ok():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_full_round_ranks_by_mean_score():
    app = create_app(strategy="round_robin")
    divisions = [{"id": "d0", "name": "open", "level": 0}]
    memberships = [
        {"id": "m_a", "division_id": "d0", "policy_version_id": "a", "player_id": "pa", "is_champion": False},
        {"id": "m_b", "division_id": "d0", "policy_version_id": "b", "player_id": "pb", "is_champion": False},
    ]

    with TestClient(app).websocket_connect("/round") as ws:
        ws.send_json(_round_start(divisions=divisions, memberships=memberships))

        scheduled = ws.receive_json()
        assert scheduled["type"] == "schedule_episodes"
        episodes = scheduled["episodes"]
        assert len(episodes) == 1  # C(2, 2)

        request_id = episodes[0]["request_id"]
        ws.send_json({"type": "episodes_accepted", "request_ids": [request_id]})
        ws.send_json(
            {
                "type": "episode_result",
                "request_id": request_id,
                "scores": [
                    {"policy_version_id": "a", "player_id": "pa", "score": 1.0},
                    {"policy_version_id": "b", "player_id": "pb", "score": 0.0},
                ],
                "game_results": {},
            }
        )

        done = ws.receive_json()

    assert done["type"] == "round_complete"
    assert done["state"] is None
    rankings = done["results"][0]["rankings"]
    assert [r["policy_version_id"] for r in rankings] == ["a", "b"]
    assert [r["rank"] for r in rankings] == [1, 2]
    assert rankings[0]["score"] == 1.0


def test_division_with_too_few_policies_completes_empty():
    app = create_app()
    divisions = [{"id": "d0", "name": "open", "level": 0}]
    memberships = [
        {"id": "m_a", "division_id": "d0", "policy_version_id": "a", "player_id": "pa", "is_champion": False},
    ]

    with TestClient(app).websocket_connect("/round") as ws:
        ws.send_json(_round_start(divisions=divisions, memberships=memberships))
        done = ws.receive_json()

    assert done["type"] == "round_complete"
    assert done["results"] == []
    assert done["graduation_changes"] == []


def test_percentile_graduation_threads_through_round():
    app = create_app(strategy="round_robin", graduation="percentile", relegate_bottom_pct=50)
    divisions = [
        {"id": "d0", "name": "open", "level": 0},
        {"id": "d1", "name": "pro", "level": 1},
    ]
    memberships = [
        {"id": "m_a", "division_id": "d1", "policy_version_id": "a", "player_id": "pa", "is_champion": False},
        {"id": "m_b", "division_id": "d1", "policy_version_id": "b", "player_id": "pb", "is_champion": False},
    ]

    with TestClient(app).websocket_connect("/round") as ws:
        ws.send_json(_round_start(divisions=divisions, memberships=memberships))
        scheduled = ws.receive_json()
        request_id = scheduled["episodes"][0]["request_id"]
        ws.send_json({"type": "episodes_accepted", "request_ids": [request_id]})
        ws.send_json(
            {
                "type": "episode_result",
                "request_id": request_id,
                "scores": [
                    {"policy_version_id": "a", "player_id": "pa", "score": 1.0},
                    {"policy_version_id": "b", "player_id": "pb", "score": 0.0},
                ],
                "game_results": {},
            }
        )
        done = ws.receive_json()

    # Bottom 50% of the d1 ranking (policy "b") relegates to d0.
    changes = done["graduation_changes"]
    assert {"membership_id": "m_b", "to_division_id": "d0", "reason": "relegated (bottom 50%)"} in changes
