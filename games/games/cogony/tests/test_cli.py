from __future__ import annotations

import sys
from types import SimpleNamespace

from cogony import cli as cogony_cli


def test_gui_play_exits_when_renderer_wait_reports_shutdown(monkeypatch, tmp_path) -> None:
    renderers = []
    simulations = []

    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.render_calls = 0
            self.wait_calls = 0
            renderers.append(self)

        def render(self) -> None:
            self.render_calls += 1

        def wait_until_step_allowed(self) -> bool:
            self.wait_calls += 1
            return False

        def apply_deferred_user_actions(self) -> None:
            return None

    class FakeSimulator:
        def add_event_handler(self, handler) -> None:
            self.handler = handler

        def new_simulation(self, env, seed):
            sim = FakeSim()
            simulations.append(sim)
            return sim

    class FakeSim:
        config = object()
        num_agents = 0
        current_step = 0

        def __init__(self) -> None:
            self._context = {}
            self.step_calls = 0

        def is_done(self) -> bool:
            return False

        def step(self) -> None:
            self.step_calls += 1

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr(cogony_cli, "_mettascope_wasm_dir", lambda: tmp_path)
    monkeypatch.setattr("cogony.web.server.WebRenderer", FakeRenderer)
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="noop",
        cogs=0,
        render="gui",
        tps=5.0,
        port=8899,
        autoplay=False,
        autostart=False,
    )

    assert renderers[0].render_calls == 2
    assert renderers[0].wait_calls == 1
    assert simulations[0].step_calls == 1


def test_gui_play_defaults_to_ephemeral_web_port(monkeypatch, tmp_path) -> None:
    renderers = []

    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            renderers.append(self)

        def render(self) -> None:
            return None

        def wait_until_step_allowed(self) -> bool:
            return False

        def apply_deferred_user_actions(self) -> None:
            return None

    class FakeSimulator:
        def add_event_handler(self, handler) -> None:
            self.handler = handler

        def new_simulation(self, env, seed):
            return FakeSim()

    class FakeSim:
        config = object()
        num_agents = 0
        current_step = 0

        def __init__(self) -> None:
            self._context = {}

        def is_done(self) -> bool:
            return False

        def step(self) -> None:
            return None

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr(cogony_cli, "_mettascope_wasm_dir", lambda: tmp_path)
    monkeypatch.setattr("cogony.web.server.WebRenderer", FakeRenderer)
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="noop",
        cogs=0,
        render="gui",
        tps=5.0,
        autoplay=False,
        autostart=False,
    )

    assert renderers[0].kwargs["port"] == 0


def test_gui_play_prints_client_urls_when_server_is_ready(monkeypatch, tmp_path) -> None:
    printed = []

    class FakeMission:
        max_steps = 10000

        def with_cogs(self, cogs):
            return self

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def set_status_provider(self, provider):
            self.status_provider = provider

        def admin_state(self):
            return {"ok": True, "port": self.kwargs["port"], "step": 0}

        def render(self) -> None:
            return None

        def wait_until_step_allowed(self) -> bool:
            return False

        def apply_deferred_user_actions(self) -> None:
            return None

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
        num_agents = 1
        current_step = 0

        def __init__(self) -> None:
            self._context = {}
            self.agent_obj = FakeAgent()

        def agent(self, agent_id):
            return self.agent_obj

        def observations(self):
            return ["obs"]

        def step(self) -> None:
            self.current_step += 1

        def is_done(self) -> bool:
            return self.current_step >= 1

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr(cogony_cli, "_mettascope_wasm_dir", lambda: tmp_path)
    monkeypatch.setattr(cogony_cli, "_decode_observation_tokens", lambda obs, pei, step: ({}, {}, None))
    monkeypatch.setattr("cogony.web.server.WebRenderer", FakeRenderer)
    monkeypatch.setattr(cogony_cli.typer, "echo", lambda message: printed.append(message))
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="noop",
        cogs=1,
        render="gui",
        tps=5.0,
        port=8899,
        autoplay=False,
        autostart=False,
    )

    assert printed[0].startswith("Artifacts: ")
    assert printed[1] == "Player clients:"
    assert printed[2].startswith("  0: http://127.0.0.1:8899/player?slot=0&token=")
    assert printed[3] == "Global client: http://127.0.0.1:8899/global"
    assert printed[4] == "Admin client: http://127.0.0.1:8899/admin"
    assert printed[5] == "Waiting for the game to exit..."


def test_gui_play_passes_codex_browser_mode_to_web_renderer(monkeypatch, tmp_path) -> None:
    renderers = []

    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            renderers.append(self)

        def render(self) -> None:
            return None

        def wait_until_step_allowed(self) -> bool:
            return False

        def apply_deferred_user_actions(self) -> None:
            return None

    class FakeSimulator:
        def add_event_handler(self, handler) -> None:
            self.handler = handler

        def new_simulation(self, env, seed):
            return FakeSim()

    class FakeSim:
        config = object()
        num_agents = 0
        current_step = 0

        def __init__(self) -> None:
            self._context = {}

        def is_done(self) -> bool:
            return False

        def step(self) -> None:
            return None

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr(cogony_cli, "_mettascope_wasm_dir", lambda: tmp_path)
    monkeypatch.setattr("cogony.web.server.WebRenderer", FakeRenderer)
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="noop",
        cogs=0,
        render="gui",
        tps=5.0,
        autoplay=False,
        autostart=False,
        codex=True,
    )

    assert renderers[0].kwargs["codex_browser"] is True


def test_play_applies_god_mode_to_mission(monkeypatch) -> None:
    missions = []

    class FakeMission:
        max_steps = 10000

        def __init__(self, god_mode: bool = False):
            self.god_mode = god_mode
            missions.append(self)

        def with_god_mode(self):
            return FakeMission(god_mode=True)

        def make_env(self):
            return object()

    class FakeRenderer:
        def render(self) -> None:
            return None

        def apply_deferred_user_actions(self) -> None:
            return None

    class FakeSimulator:
        def add_event_handler(self, handler) -> None:
            return None

        def new_simulation(self, env, seed):
            return FakeSim()

    class FakeSim:
        config = object()
        num_agents = 0
        current_step = 0

        def __init__(self) -> None:
            self._context = {}

        def is_done(self) -> bool:
            return True

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr("mettagrid.renderer.renderer.create_renderer", lambda *args, **kwargs: FakeRenderer())
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="noop",
        cogs=0,
        render="none",
        tps=5.0,
        port=8899,
        autoplay=True,
        autostart=False,
        god_mode=True,
    )

    assert missions[-1].god_mode is True


def test_gui_play_does_not_render_after_final_step(monkeypatch, tmp_path) -> None:
    renderers = []

    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            self.render_calls = 0
            renderers.append(self)

        def apply_deferred_user_actions(self) -> None:
            return None

        def render(self) -> None:
            self.render_calls += 1

        def wait_until_step_allowed(self) -> bool:
            return True

    class FakeSimulator:
        def add_event_handler(self, handler) -> None:
            self.handler = handler

        def new_simulation(self, env, seed):
            return FakeSim()

    class FakeSim:
        config = object()
        num_agents = 0
        current_step = 0

        def __init__(self) -> None:
            self._context = {}
            self.done = False

        def is_done(self) -> bool:
            return self.done

        def step(self) -> None:
            self.current_step += 1
            self.done = True

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr(cogony_cli, "_mettascope_wasm_dir", lambda: tmp_path)
    monkeypatch.setattr("cogony.web.server.WebRenderer", FakeRenderer)
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="noop",
        cogs=0,
        render="gui",
        tps=5.0,
        port=8899,
        autoplay=True,
        autostart=False,
    )

    assert renderers[0].render_calls == 1


def test_gui_play_refreshes_policy_obs_grid_after_sim_step(monkeypatch, tmp_path) -> None:
    simulations = []

    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            pass

        def apply_deferred_user_actions(self) -> None:
            return None

        def render(self) -> None:
            return None

        def wait_until_step_allowed(self) -> bool:
            return False

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
            return [f"obs-at-{self.current_step}"]

        def is_done(self) -> bool:
            return self.current_step >= 1

        def step(self) -> None:
            self.current_step += 1

    class FakeAgentPolicy:
        infos = {"goal": "move"}

        def step(self, obs):
            assert obs == "obs-at-0"
            return SimpleNamespace(name="move_east")

    class FakePolicy:
        def __init__(self) -> None:
            self.agent = FakeAgentPolicy()

        def agent_policy(self, agent_id: int) -> FakeAgentPolicy:
            return self.agent

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr(cogony_cli, "_mettascope_wasm_dir", lambda: tmp_path)
    monkeypatch.setattr(cogony_cli, "_make_policy", lambda name, pei, **kwargs: FakePolicy())
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )
    monkeypatch.setattr(
        cogony_cli,
        "_decode_observation_tokens",
        lambda obs, pei, step: (
            {"0,1": {"tags": [f"type:{obs}"], "feats": {"step": step}}},
            {"global_step": step},
            [10 + step, 20 + step],
        ),
        raising=False,
    )
    monkeypatch.setattr("cogony.web.server.WebRenderer", FakeRenderer)

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="baseline",
        cogs=0,
        render="gui",
        tps=5.0,
        port=8899,
        autoplay=True,
        autostart=False,
    )

    assert simulations[0]._context["policy_infos"][0]["obs_grid"] == {
        "0,1": {"tags": ["type:obs-at-1"], "feats": {"step": 1}}
    }
    assert simulations[0]._context["policy_infos"][0]["obs_global"] == {"global_step": 1}
    assert simulations[0]._context["policy_infos"][0]["obs_center"] == [11, 21]


def test_obs_grid_and_global_tokens_preserve_zero_values() -> None:
    decoded = SimpleNamespace(
        center_row=5,
        center_col=7,
        cells_by_location={
            (5, 8): SimpleNamespace(
                tags=("type:hub", "team:red"),
                features={"inv:coherence": 10, "inv:cooldown": 0},
            )
        },
        global_features={"episode_progress": 4, "unused": 0},
    )

    assert cogony_cli._obs_grid_from_decoded(decoded) == {
        "0,1": {
            "tags": ["type:hub", "team:red"],
            "feats": {"inv:coherence": 10, "inv:cooldown": 0},
        }
    }
    assert cogony_cli._obs_global_from_decoded(decoded) == {"episode_progress": 4, "unused": 0}


def test_obs_center_from_local_position_tokens_tracks_spawn_coordinate() -> None:
    state: dict = {}
    first = SimpleNamespace(
        center_row=5,
        center_col=7,
        global_features={"lp:north": 2, "lp:east": 3, "last_action_move": 1},
    )
    returned = SimpleNamespace(center_row=5, center_col=7, global_features={"last_action_move": 1})

    assert cogony_cli._obs_center_from_decoded(first, state) == [3, 10]
    assert cogony_cli._obs_center_from_decoded(returned, state) == [5, 7]


def test_gui_play_does_not_add_policy_widget_descriptors_to_policy_infos(monkeypatch, tmp_path) -> None:
    simulations = []

    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            pass

        def apply_deferred_user_actions(self) -> None:
            return None

        def render(self) -> None:
            return None

        def wait_until_step_allowed(self) -> bool:
            return False

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
        current_step = 0

        def __init__(self) -> None:
            self._context = {}
            self.agent_obj = FakeAgent()

        def agent(self, agent_id: int) -> FakeAgent:
            return self.agent_obj

        def observations(self):
            return ["obs"]

        def is_done(self) -> bool:
            return self.current_step >= 1

        def step(self) -> None:
            self.current_step += 1

    class FakeAgentPolicy:
        infos = {"goal": "move"}

        def step(self, obs):
            return SimpleNamespace(name="move_east")

    class FakePolicy:
        policy_widgets = [
            "obs_map",
            {"id": "plan", "module": "plan_view", "title": "Plan", "config": {"lines": 4}},
        ]

        def __init__(self) -> None:
            self.agent = FakeAgentPolicy()

        def agent_policy(self, agent_id: int) -> FakeAgentPolicy:
            return self.agent

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr(cogony_cli, "_mettascope_wasm_dir", lambda: tmp_path)
    monkeypatch.setattr(cogony_cli, "_make_policy", lambda name, pei, **kwargs: FakePolicy())
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )
    monkeypatch.setattr(cogony_cli, "_decode_observation_tokens", lambda obs, pei, step: ({}, {}, None))
    monkeypatch.setattr("cogony.web.server.WebRenderer", FakeRenderer)

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="baseline",
        cogs=0,
        render="gui",
        tps=5.0,
        port=8899,
        autoplay=True,
        autostart=False,
    )

    assert simulations[0]._context["policy_infos"][0]["goal"] == "move"
    assert simulations[0]._context["policy_infos"][0]["__policy_name__"] == "baseline"
    assert "policy_widgets" not in simulations[0]._context["policy_infos"][0]


def test_non_gui_toolsy_policy_runs_in_process(monkeypatch) -> None:
    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)

    policy_names = []

    class FakeRenderer:
        def render(self) -> None:
            return None

        def apply_deferred_user_actions(self) -> None:
            return None

    class FakeSimulator:
        def add_event_handler(self, handler) -> None:
            return None

        def new_simulation(self, env, seed):
            return FakeSim()

    class FakeAgent:
        def set_action(self, action_name) -> None:
            self.action_name = action_name

    class FakePolicy:
        def agent_policy(self, agent_id):
            return SimpleNamespace(step=lambda obs: SimpleNamespace(name="noop"), infos={})

    class FakeSim:
        config = object()
        num_agents = 1
        current_step = 0

        def __init__(self) -> None:
            self._context = {}
            self._agent = FakeAgent()

        def observations(self):
            return ["obs"]

        def agent(self, agent_id):
            return self._agent

        def step(self) -> None:
            self.current_step += 1

        def is_done(self) -> bool:
            return self.current_step >= 1

    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr("mettagrid.renderer.renderer.create_renderer", lambda *args, **kwargs: FakeRenderer())
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )
    monkeypatch.setattr(cogony_cli, "_decode_observation_tokens", lambda obs, pei, step: ({}, {}, None))
    monkeypatch.setattr(cogony_cli, "_make_policy", lambda name, pei, **kwargs: policy_names.append(name) or FakePolicy())

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="toolsy",
        cogs=0,
        render="none",
        tps=5.0,
        port=8899,
        autoplay=True,
        autostart=False,
    )

    assert policy_names == ["toolsy"]


def test_toolsy_autopilot_forces_llm_off(monkeypatch) -> None:
    captured = {}

    class FakeToolsyPolicy:
        def __init__(self, pei, *, enable_llm: bool = True):
            captured["pei"] = pei
            captured["enable_llm"] = enable_llm

    fake_pei = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "toolsy_policy", SimpleNamespace(ToolsyPolicy=FakeToolsyPolicy))

    policy = cogony_cli._make_policy("toolsy-autopilot", fake_pei, enable_llm=True)

    assert isinstance(policy, FakeToolsyPolicy)
    assert captured == {"pei": fake_pei, "enable_llm": False}


def test_gui_play_starts_toolsy_coworld_processes_per_agent(monkeypatch, tmp_path) -> None:
    started_agent_counts = []
    shutdown_calls = []
    make_policy_calls = []

    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            pass

        def agent_ws_url(self, agent_id: int) -> str:
            return f"ws://127.0.0.1:8899/agent/{agent_id}"

        def apply_deferred_user_actions(self) -> None:
            return None

        def render(self) -> None:
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
        num_agents = 3

        def __init__(self) -> None:
            self._context = {}
            self.current_step = 0
            self.agents = {agent_id: FakeAgent() for agent_id in range(self.num_agents)}

        def agent(self, agent_id: int) -> FakeAgent:
            return self.agents[agent_id]

        def observations(self):
            return [f"obs-{agent_id}" for agent_id in range(self.num_agents)]

        def is_done(self) -> bool:
            return self.current_step >= 1

        def step(self) -> None:
            self.current_step += 1

    class FakeToolsyProcesses:
        def __init__(self, websocket_urls: list[str]):
            self.websocket_urls = websocket_urls

        def start(self) -> None:
            started_agent_counts.append(len(self.websocket_urls))

        def shutdown(self) -> None:
            shutdown_calls.append(len(self.websocket_urls))

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr(cogony_cli, "_mettascope_wasm_dir", lambda: tmp_path)
    monkeypatch.setattr(cogony_cli, "_decode_observation_tokens", lambda obs, pei, step: ({}, {}, None))
    monkeypatch.setattr("cogony.web.server.WebRenderer", FakeRenderer)
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )
    monkeypatch.setattr(
        cogony_cli,
        "_start_toolsy_coworld_processes",
        lambda renderer, num_agents: FakeToolsyProcesses(
            [renderer.agent_ws_url(agent_id) for agent_id in range(num_agents)]
        ),
        raising=False,
    )
    monkeypatch.setattr(
        cogony_cli,
        "_make_policy",
        lambda name, pei, **kwargs: make_policy_calls.append(name) or None,
    )

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="toolsy",
        cogs=0,
        render="gui",
        tps=5.0,
        port=8899,
        autoplay=True,
        autostart=False,
    )

    assert started_agent_counts == [3]
    assert shutdown_calls == [3]
    assert make_policy_calls == []


def test_gui_toolsy_autopilot_runs_in_process(monkeypatch, tmp_path) -> None:
    make_policy_calls = []
    simulations = []

    class FakeMission:
        max_steps = 10000

        def make_env(self):
            return object()

    class FakeRenderer:
        def __init__(self, **kwargs):
            pass

        def apply_deferred_user_actions(self) -> None:
            return None

        def render(self) -> None:
            return None

        def wait_until_step_allowed(self) -> bool:
            return False

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
            return [f"obs-at-{self.current_step}"]

        def is_done(self) -> bool:
            return self.current_step >= 1

        def step(self) -> None:
            self.current_step += 1

    class FakeAgentPolicy:
        infos = {"goal": "buy_hearts"}

        def step(self, obs):
            assert obs == "obs-at-0"
            return SimpleNamespace(name="move_east")

    class FakePolicy:
        def __init__(self) -> None:
            self.agent = FakeAgentPolicy()

        def agent_policy(self, agent_id: int) -> FakeAgentPolicy:
            return self.agent

    def fail_coworld(renderer, num_agents):
        raise AssertionError("toolsy-autopilot should not start Coworld")

    def make_policy(name, pei, **kwargs):
        make_policy_calls.append((name, kwargs))
        return FakePolicy()

    monkeypatch.setattr(cogony_cli, "CogonyMission", FakeMission)
    monkeypatch.setattr(cogony_cli, "Simulator", FakeSimulator)
    monkeypatch.setattr(cogony_cli, "_mettascope_wasm_dir", lambda: tmp_path)
    monkeypatch.setattr(cogony_cli, "_decode_observation_tokens", lambda obs, pei, step: ({}, {}, None))
    monkeypatch.setattr(cogony_cli, "_start_toolsy_coworld_processes", fail_coworld)
    monkeypatch.setattr(cogony_cli, "_make_policy", make_policy)
    monkeypatch.setattr("cogony.web.server.WebRenderer", FakeRenderer)
    monkeypatch.setattr(
        "mettagrid.policy.policy_env_interface.PolicyEnvInterface.from_mg_cfg",
        lambda config: SimpleNamespace(),
    )

    cogony_cli.play(
        variant=None,
        max_steps=5,
        seed=42,
        policy="toolsy-autopilot",
        cogs=0,
        render="gui",
        tps=5.0,
        port=8899,
        autoplay=True,
        autostart=False,
    )

    assert make_policy_calls == [("toolsy-autopilot", {"enable_llm": True})]
    assert simulations[0].agent_obj.action_name == "move_east"
