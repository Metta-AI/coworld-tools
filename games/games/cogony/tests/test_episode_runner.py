from __future__ import annotations

from types import SimpleNamespace

from cogony.episode_runner import EpisodeRunner, EpisodeRunnerConfig


def test_episode_runner_starts_components_and_exposes_status(tmp_path) -> None:
    renderers = []
    simulations = []
    policies = []
    ready_statuses = []

    class FakeMission:
        max_steps = 10000

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
            return {"ok": True, "port": self.kwargs["port"], "playing": self.kwargs["autoplay"], "step": 1}

        def agent_ws_url(self, agent_id: int) -> str:
            return f"ws://127.0.0.1:{self.kwargs['port']}/agent/{agent_id}"

        def apply_deferred_user_actions(self) -> None:
            return None

        def render(self) -> None:
            self.render_calls += 1

        def wait_until_step_allowed(self) -> bool:
            return self.render_calls < 2

    class FakeSimulator:
        def add_event_handler(self, handler) -> None:
            self.handler = handler

        def new_simulation(self, env, seed):
            sim = FakeSim()
            simulations.append(sim)
            return sim

    class FakeAgent:
        def set_action(self, action_name) -> None:
            self.action_name = action_name

    class FakeSim:
        config = object()
        num_agents = 1

        def __init__(self) -> None:
            self._context = {}
            self.current_step = 0
            self.agent_obj = FakeAgent()

        def agent(self, agent_id: int) -> FakeAgent:
            return self.agent_obj

        def observations(self):
            return [f"obs-{self.current_step}"]

        def is_done(self) -> bool:
            return self.current_step >= 1

        def step(self) -> None:
            self.current_step += 1

    class FakeAgentPolicy:
        infos = {"goal": "test"}

        def step(self, obs):
            return SimpleNamespace(name="move_east")

    class FakePolicy:
        def __init__(self) -> None:
            policies.append(self)
            self.agent = FakeAgentPolicy()

        def agent_policy(self, agent_id: int):
            return self.agent

    runner = EpisodeRunner(
        EpisodeRunnerConfig(policy="baseline", render="gui", port=8999, autoplay=True, wasm_dir=tmp_path),
        mission_factory=FakeMission,
        simulator_factory=FakeSimulator,
        web_renderer_factory=FakeRenderer,
        policy_env_info_factory=lambda config: SimpleNamespace(),
        make_policy=lambda name, pei, **kwargs: FakePolicy(),
        decode_observation_tokens=lambda obs, pei, step: ({}, {}, [step, step]),
        on_ready=ready_statuses.append,
    )

    ticks = runner.run()

    status = runner.status()
    assert ticks == 1
    assert renderers[0].status_provider is not None
    assert renderers[0].status_provider()["components"][0]["name"] == "server"
    assert simulations[0]._context["policy_infos"][0]["goal"] == "test"
    assert status["components"] == [
        {"name": "server", "state": "running", "detail": "http://localhost:8999"},
        {"name": "game", "state": "done", "detail": "step 1 / 10000"},
        {"name": "policies", "state": "in-process", "detail": "baseline x1"},
    ]
    assert status["endpoints"]["global"] == "ws://127.0.0.1:8999/global"
    assert status["endpoints"]["agent_template"] == "ws://127.0.0.1:8999/agent/{id}"
    assert status["client_urls"]["admin"] == "http://127.0.0.1:8999/admin"
    assert status["client_urls"]["global"] == "http://127.0.0.1:8999/global"
    assert len(status["client_urls"]["players"]) == 1
    assert status["client_urls"]["global-client"] == "http://localhost:8999/global-client"
    assert status["client_urls"]["policy-debugger?agent=0"] == "http://localhost:8999/policy-debugger?agent=0"
    assert status["admin"]["port"] == 8999
    assert policies
    assert ready_statuses[0]["client_urls"]["policy-debugger?agent=0"] == (
        "http://localhost:8999/policy-debugger?agent=0"
    )


def test_episode_runner_status_reports_coworld_policy_mode(tmp_path) -> None:
    class FakeRenderer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        @property
        def session_id(self):
            return "session-2"

        def set_status_provider(self, provider):
            self.status_provider = provider

        def admin_state(self):
            return {"ok": True, "port": self.kwargs["port"], "playing": False, "step": 0}

        def agent_ws_url(self, agent_id: int) -> str:
            return f"ws://127.0.0.1:{self.kwargs['port']}/agent/{agent_id}"

        def render(self) -> None:
            return None

        def wait_until_step_allowed(self) -> bool:
            return False

        def apply_deferred_user_actions(self) -> None:
            return None

    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    class FakeSimulator:
        def add_event_handler(self, handler) -> None:
            return None

        def new_simulation(self, env, seed):
            return FakeSim()

    class FakeAgent:
        def set_action(self, action_name) -> None:
            self.action_name = action_name

    class FakeSim:
        config = object()
        num_agents = 2

        def __init__(self) -> None:
            self.current_step = 0
            self._context = {}
            self.agents = {agent_id: FakeAgent() for agent_id in range(self.num_agents)}

        def agent(self, agent_id: int):
            return self.agents[agent_id]

        def observations(self):
            return [f"obs-{agent_id}-{self.current_step}" for agent_id in range(self.num_agents)]

        def step(self) -> None:
            self.current_step += 1

        def is_done(self) -> bool:
            return self.current_step >= 1

    class FakeCoworldProcesses:
        def __init__(self):
            self.started = False
            self.shutdown_called = False

        def start(self) -> None:
            self.started = True

        def shutdown(self) -> None:
            self.shutdown_called = True

    processes = FakeCoworldProcesses()
    runner = EpisodeRunner(
        EpisodeRunnerConfig(policy="toolsy", render="gui", port=9001, wasm_dir=tmp_path),
        mission_factory=FakeMission,
        simulator_factory=FakeSimulator,
        web_renderer_factory=FakeRenderer,
        policy_env_info_factory=lambda config: SimpleNamespace(),
        start_coworld_processes=lambda renderer, num_agents: processes,
        decode_observation_tokens=lambda obs, pei, step: ({}, {}, None),
    )

    runner.run()

    assert processes.started is True
    assert processes.shutdown_called is True
    assert runner.status()["components"][2] == {
        "name": "policies",
        "state": "coworld",
        "detail": "toolsy x2",
    }
