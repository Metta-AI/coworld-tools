from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from cogony import cli as cogony_cli
from cogony.episode_runner import EpisodeRunner, EpisodeRunnerConfig
from cogony.runner_support import _start_toolsy_coworld_processes
from cogony.web.server import WebRenderer


def test_episode_runner_exposes_coworld_play_session_links_and_artifacts(tmp_path: Path) -> None:
    renderers = []
    ready_statuses = []
    workspace = tmp_path / "coworld-play-session"

    class FakeMission:
        max_steps = 10000
        num_agents = 2

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.render_calls = 0
            self.status_provider = None
            renderers.append(self)

        @property
        def session_id(self):
            return "session-1"

        def set_status_provider(self, provider):
            self.status_provider = provider

        def admin_state(self):
            return {"ok": True, "port": self.kwargs["port"], "playing": False, "step": 0}

        def render(self) -> None:
            self.render_calls += 1

        def apply_deferred_user_actions(self) -> None:
            return None

        def wait_until_step_allowed(self) -> bool:
            return False

    class FakeSimulator:
        def add_event_handler(self, handler) -> None:
            self.handler = handler

        def new_simulation(self, env, seed):
            return FakeSim()

    class FakeAgent:
        def set_action(self, action_name) -> None:
            self.action_name = action_name

    class FakeSim:
        config = object()
        num_agents = 2

        def __init__(self) -> None:
            self._context = {}
            self.current_step = 0
            self.agents = {agent_id: FakeAgent() for agent_id in range(self.num_agents)}

        def agent(self, agent_id: int) -> FakeAgent:
            return self.agents[agent_id]

        def observations(self):
            return [f"obs-{agent_id}-{self.current_step}" for agent_id in range(self.num_agents)]

        def is_done(self) -> bool:
            return self.current_step >= 1

        def step(self) -> None:
            self.current_step += 1

    runner = EpisodeRunner(
        EpisodeRunnerConfig(
            policy="noop",
            render="gui",
            port=8999,
            wasm_dir=tmp_path,
            artifact_workspace=workspace,
        ),
        mission_factory=FakeMission,
        simulator_factory=FakeSimulator,
        web_renderer_factory=FakeRenderer,
        policy_env_info_factory=lambda config: SimpleNamespace(),
        decode_observation_tokens=lambda obs, pei, step: ({}, {}, None),
        on_ready=ready_statuses.append,
    )

    runner.run()

    status = runner.status()
    assert status["runner"] == "coworld_episode_runner"
    assert status["artifacts"]["workspace"] == str(workspace)
    assert Path(status["artifacts"]["results"]).is_file()
    assert Path(status["artifacts"]["replay"]).is_file()
    assert status["client_urls"]["global"] == "http://127.0.0.1:8999/global"
    assert status["client_urls"]["admin"] == "http://127.0.0.1:8999/admin"
    assert len(status["client_urls"]["players"]) == 2
    assert renderers[0].kwargs["log_dir"] == workspace / "logs"
    assert renderers[0].kwargs["player_tokens"] == [
        parse_qs(urlparse(url).query)["token"][0] for url in status["client_urls"]["players"]
    ]
    assert "/player?slot=0&token=" in status["client_urls"]["players"][0]
    assert ready_statuses[0]["client_urls"]["global"] == "http://127.0.0.1:8999/global"


def test_web_renderer_binds_coworld_player_urls_to_authenticated_slots(tmp_path: Path) -> None:
    renderer = WebRenderer(
        wasm_dir=_wasm_dir(tmp_path),
        port=8899,
        tick_rate=20,
        player_tokens=["slot-zero", "slot-one"],
    )

    assert renderer._player_agent_id_from_query({"slot": "1", "token": "slot-one"}) == 1
    assert renderer._player_agent_id_from_query({"slot": "1", "token": "bad"}) is None
    assert renderer._player_agent_id_from_query({"slot": "2", "token": "slot-one"}) is None
    assert renderer.policy_ws_url(1) == "ws://127.0.0.1:8899/policy/1"


def test_toolsy_coworld_processes_use_policy_client_stream(monkeypatch) -> None:
    captured_urls = []

    class FakeManager:
        def __init__(self, websocket_urls: list[str]):
            captured_urls.append(websocket_urls)

    class FakeRenderer:
        def policy_ws_url(self, agent_id: int) -> str:
            return f"ws://game/policy/{agent_id}"

        def agent_ws_url(self, agent_id: int) -> str:
            raise AssertionError(f"debug stream should not be used for policy client {agent_id}")

    monkeypatch.setattr("toolsy_policy.coworld.ToolsyCoworldProcessManager", FakeManager)

    _start_toolsy_coworld_processes(FakeRenderer(), 2)

    assert captured_urls == [["ws://game/policy/0", "ws://game/policy/1"]]


def test_player_client_uses_authenticated_player_websocket(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert "const PLAYER_CLIENT_MODE = window.location.pathname === '/player';" in response.text
    assert "const AGENT_CLIENT_MODE = POLICY_DEBUGGER_MODE || PLAYER_CLIENT_MODE;" in response.text
    assert "const PANEL_IDS = AGENT_CLIENT_MODE ? ['agent'] : ['game'];" in response.text
    assert "document.body.classList.toggle('policy-client-mode', AGENT_CLIENT_MODE);" in response.text
    assert "PLAYER_CLIENT_MODE ? 'Cogony Player Client' : 'Cogony Policy Debugger'" in response.text
    assert "function playerWsUrl()" in response.text
    assert "return wsUrlWithCurrentQuery('/player');" in response.text
    assert "function connectPlayerStream(generation = agentPanelGeneration)" in response.text
    assert (
        "if (PLAYER_CLIENT_MODE) connectPlayerStream(); else if (POLICY_DEBUGGER_MODE) "
        "connectPolicyDebugStream(); else connectGlobalStream();"
    ) in response.text
    assert "return wsUrl('/global');" in response.text
    assert "connectPolicyStream" not in response.text


def test_cli_prints_coworld_play_session_links(capsys) -> None:
    cogony_cli._print_client_urls(
        {
            "artifacts": {
                "workspace": "/tmp/coworld-play-test",
                "results": "/tmp/coworld-play-test/results.json",
                "replay": "/tmp/coworld-play-test/replay.json",
                "logs": "/tmp/coworld-play-test/logs",
            },
            "client_urls": {
                "players": [
                    "http://127.0.0.1:8999/player?slot=0&token=abc",
                    "http://127.0.0.1:8999/player?slot=1&token=def",
                ],
                "global": "http://127.0.0.1:8999/global",
                "admin": "http://127.0.0.1:8999/admin",
            },
        }
    )

    assert capsys.readouterr().out.splitlines() == [
        "Artifacts: /tmp/coworld-play-test",
        "Player clients:",
        "  0: http://127.0.0.1:8999/player?slot=0&token=abc",
        "  1: http://127.0.0.1:8999/player?slot=1&token=def",
        "Global client: http://127.0.0.1:8999/global",
        "Admin client: http://127.0.0.1:8999/admin",
        "Waiting for the game to exit...",
    ]


def _wasm_dir(tmp_path: Path) -> Path:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text(
        '<html><head></head><body></body><script async type="text/javascript" src="mettascope.js"></script></html>'
    )
    return wasm_dir
