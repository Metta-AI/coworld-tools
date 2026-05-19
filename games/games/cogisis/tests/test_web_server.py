import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from cogisis.engine import CogisisSimulator
from cogisis.mission import CogisisMission
from cogisis.policies import make_policy
from cogisis.web.server import CogisisWebServer


def test_web_server_exposes_paused_clients_and_manual_step(tmp_path) -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=2, max_steps=3, seed=9).build_world())
    server = CogisisWebServer(
        sim,
        make_policy("noop", seed=9),
        policy_name="noop",
        seed=9,
        max_steps=3,
        port=0,
        autorun=False,
        artifact_workspace=tmp_path / "session",
    )

    server.start()
    try:
        status = _json(f"http://127.0.0.1:{server.port}/status?format=json")
        assert status["components"][1]["state"] == "paused"
        assert status["episode"]["step"] == 0
        assert status["client_urls"]["admin"].endswith("/admin")
        assert status["client_urls"]["global"].endswith("/global")
        assert len(status["client_urls"]["players"]) == 2
        assert "agents" not in status["client_urls"]
        assert "policy-client?agent=0" not in status["client_urls"]

        global_html = _text(f"http://127.0.0.1:{server.port}/global")
        assert "Cogisis global client" in global_html
        assert '"/state.json"' in global_html
        assert "cogLaunchers" in global_html
        assert 'target = "_blank"' in global_html
        assert "window.open" in global_html
        assert "agent client in a new window" in global_html
        assert "player-popup" not in global_html
        assert status["client_urls"]["players"][0] in global_html
        assert _status(f"http://127.0.0.1:{server.port}/assets/nemesis-board.png") == 404
        assert _status(f"http://127.0.0.1:{server.port}/policy-client?agent=0") == 404

        frame = _json(f"http://127.0.0.1:{server.port}/state.json")
        assert frame["player_connections"][0]["connected"] is False
        player_html = _text(status["client_urls"]["players"][0])
        assert "Cogisis player 0" in player_html
        assert "God Mode" not in player_html
        assert "godModeButton" not in player_html
        frame = _json(f"http://127.0.0.1:{server.port}/state.json")
        assert frame["player_connections"][0]["connected"] is True

        stepped = _post_json(f"http://127.0.0.1:{server.port}/admin", {"command": "step"})
        assert stepped["ok"] is True
        assert stepped["status"]["episode"]["step"] == 1
    finally:
        server.stop()


def test_web_server_client_urls_can_use_public_base_url(tmp_path) -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=2, max_steps=3, seed=10).build_world())
    server = CogisisWebServer(
        sim,
        make_policy("noop", seed=10),
        policy_name="noop",
        seed=10,
        max_steps=3,
        port=0,
        autorun=False,
        artifact_workspace=tmp_path / "session",
    )
    server.start()
    try:
        server.set_public_base_url("https://example.trycloudflare.com/")

        urls = server.client_urls()
        endpoints = server.endpoints()

        assert urls["admin"] == "https://example.trycloudflare.com/admin"
        assert urls["global"] == "https://example.trycloudflare.com/global"
        assert urls["players"][0].startswith("https://example.trycloudflare.com/player?slot=0&token=")
        assert urls["global-client"] == "https://example.trycloudflare.com/global-client"
        assert endpoints["state"] == "https://example.trycloudflare.com/state.json"
    finally:
        server.stop()


def test_public_base_url_is_used_by_status_admin_and_client_pages(tmp_path) -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=2, max_steps=3, seed=11).build_world())
    server = CogisisWebServer(
        sim,
        make_policy("noop", seed=11),
        policy_name="noop",
        seed=11,
        max_steps=3,
        port=0,
        autorun=False,
        artifact_workspace=tmp_path / "session",
    )
    server.start()
    try:
        public_root = "https://public-cogisis.trycloudflare.com"
        server.set_public_base_url(public_root)

        status = _json(f"http://127.0.0.1:{server.port}/status?format=json")
        assert status["components"][0]["detail"] == public_root
        assert status["endpoints"]["status"] == f"{public_root}/status"
        assert status["client_urls"]["global"] == f"{public_root}/global"
        assert status["client_urls"]["players"][0].startswith(f"{public_root}/player?slot=0&token=")

        global_html = _text(f"http://127.0.0.1:{server.port}/global")
        assert f"{public_root}/player?slot=0&token=" in global_html
        assert "http://127.0.0.1" not in global_html
        assert '"live_endpoint": "/state.json"' in global_html

        admin_html = _text(f"http://127.0.0.1:{server.port}/admin")
        assert f"{public_root}/global" in admin_html
        assert f"{public_root}/admin" in admin_html
        assert "http://127.0.0.1" not in admin_html

        player_url = status["client_urls"]["players"][0].replace(public_root, f"http://127.0.0.1:{server.port}")
        player_html = _text(player_url)
        assert "http://127.0.0.1" not in player_html
        assert '"/state.json?slot=0&token=' in player_html
    finally:
        server.stop()


def test_tunneled_request_host_drives_links_without_static_public_base(tmp_path) -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=2, max_steps=3, seed=18).build_world())
    server = CogisisWebServer(
        sim,
        make_policy("noop", seed=18),
        policy_name="noop",
        seed=18,
        max_steps=3,
        port=0,
        autorun=False,
        artifact_workspace=tmp_path / "session",
    )
    server.start()
    try:
        headers = {"Host": "dynamic-cogisis.trycloudflare.com", "X-Forwarded-Proto": "https"}
        public_root = "https://dynamic-cogisis.trycloudflare.com"

        status = _json_request(f"http://127.0.0.1:{server.port}/status?format=json", headers)
        assert status["client_urls"]["global"] == f"{public_root}/global"
        assert status["client_urls"]["players"][0].startswith(f"{public_root}/player?slot=0&token=")
        assert status["endpoints"]["state"] == f"{public_root}/state.json"

        global_html = _text_request(f"http://127.0.0.1:{server.port}/global", headers)
        assert f"{public_root}/player?slot=0&token=" in global_html
        assert "http://127.0.0.1" not in global_html

        admin_html = _text_request(f"http://127.0.0.1:{server.port}/admin", headers)
        assert f"{public_root}/global" in admin_html
        assert "http://127.0.0.1" not in admin_html
    finally:
        server.stop()


def test_web_server_accepts_authenticated_player_turn_actions(tmp_path) -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=2, max_steps=3, seed=12).build_world())
    server = CogisisWebServer(
        sim,
        make_policy("noop", seed=12),
        policy_name="noop",
        seed=12,
        max_steps=3,
        port=0,
        autorun=False,
        artifact_workspace=tmp_path / "session",
    )

    server.start()
    try:
        status = _json(f"http://127.0.0.1:{server.port}/status?format=json")
        player0 = _player_auth(status["client_urls"]["players"][0])
        player1 = _player_auth(status["client_urls"]["players"][1])
        action_url = f"http://127.0.0.1:{server.port}/player/action"

        wrong_turn_status, wrong_turn = _post_json_error(action_url, {**player1, "action": "pass"})
        assert wrong_turn_status == 400
        assert "not player 1's turn" in wrong_turn["error"]

        name_set = _post_json(action_url, {**player1, "action": "set-name:Jones"})
        assert name_set["ok"] is True
        assert name_set["frame"]["turn_token"]["holder"] == 0
        assert name_set["frame"]["turn_token"]["actions_remaining"] == 2
        assert name_set["frame"]["players"][1]["display_name"] == "Jones"
        assert name_set["frame"]["global"]["characters"]["1"]["display_name"] == "Jones"
        assert name_set["events"] == [{"type": "name_set", "character_id": 1, "name": "Jones"}]

        invalid_token_status, invalid_token = _post_json_error(
            action_url,
            {"slot": player0["slot"], "token": "bad-token", "action": "pass"},
        )
        assert invalid_token_status == 403
        assert invalid_token["error"] == "invalid player token"

        invalid_action_status, invalid_action = _post_json_error(action_url, {**player0, "action": "move:not_a_room"})
        assert invalid_action_status == 400
        assert "invalid action for player 0" in invalid_action["error"]

        missing_discard_status, missing_discard = _post_json_error(action_url, {**player0, "action": "search"})
        assert missing_discard_status == 400
        assert "requires 1 discarded card" in missing_discard["error"]

        frame = _json(f"http://127.0.0.1:{server.port}/state.json")
        player0_card = frame["players"][0]["observation"]["self"]["action_hand"][0]["id"]
        first = _post_json(action_url, {**player0, "action": "search", "discard": [player0_card]})
        assert first["ok"] is True
        assert first["frame"]["step"] == 0
        assert first["frame"]["turn_token"]["holder"] == 0
        assert first["frame"]["turn_token"]["actions_remaining"] == 1
        assert player0_card in [
            card["id"] for card in first["frame"]["players"][0]["observation"]["self"]["action_discard"]
        ]

        player0_next_card = first["frame"]["players"][0]["observation"]["self"]["action_hand"][0]["id"]
        second = _post_json(action_url, {**player0, "action": "rest", "discard": [player0_next_card]})
        assert second["ok"] is True
        assert second["frame"]["step"] == 0
        assert second["frame"]["turn_token"]["holder"] == 1
        assert second["frame"]["turn_token"]["actions_remaining"] == 2
        assert not any(event["type"] == "time_advanced" for event in second["events"])

        third = _post_json(action_url, {**player1, "action": "pass"})
        assert third["ok"] is True
        assert third["frame"]["step"] == 1
        assert third["frame"]["turn_token"]["holder"] == 0
        assert third["frame"]["turn_token"]["actions_remaining"] == 2
        assert any(event["type"] == "time_advanced" for event in third["events"])
    finally:
        server.stop()


def _json(url: str) -> dict:
    with urlopen(url, timeout=2) as response:
        return json.loads(response.read().decode())


def _json_request(url: str, headers: dict[str, str]) -> dict:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode())


def _text(url: str) -> str:
    with urlopen(url, timeout=2) as response:
        return response.read().decode()


def _text_request(url: str, headers: dict[str, str]) -> str:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=2) as response:
        return response.read().decode()


def _post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode())


def _post_json_error(url: str, payload: dict) -> tuple[int, dict]:
    try:
        _post_json(url, payload)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())
    raise AssertionError("expected HTTPError")


def _status(url: str) -> int:
    try:
        with urlopen(url, timeout=2) as response:
            return response.status
    except HTTPError as exc:
        return exc.code


def _player_auth(url: str) -> dict:
    query = parse_qs(urlparse(url).query)
    return {"slot": int(query["slot"][0]), "token": query["token"][0]}
