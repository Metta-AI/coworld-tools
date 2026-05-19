from __future__ import annotations

from types import SimpleNamespace

import pytest

from cogony import cli as cogony_cli


def test_launch_path_from_client_flags_maps_single_default_and_conflicting_flags() -> None:
    assert cogony_cli._launch_path_from_client_flags(agent=False, global_client=False, admin=False) == "/"
    assert cogony_cli._launch_path_from_client_flags(agent=True, global_client=False, admin=False) == (
        "/policy-debugger?agent=0"
    )
    assert cogony_cli._launch_path_from_client_flags(agent=False, global_client=True, admin=False) == "/global"
    assert cogony_cli._launch_path_from_client_flags(agent=False, global_client=False, admin=True) == "/admin"

    with pytest.raises(cogony_cli.typer.BadParameter, match="Choose only one"):
        cogony_cli._launch_path_from_client_flags(agent=True, global_client=True, admin=False)


@pytest.mark.parametrize(
    ("flag", "launch_path"),
    [
        ({"agent": True}, "/policy-debugger?agent=0"),
        ({"global_client": True}, "/global"),
        ({"admin": True}, "/admin"),
    ],
)
def test_play_launch_target_flags_select_browser_client(monkeypatch, tmp_path, flag, launch_path) -> None:
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
            return True

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
        **flag,
    )

    assert renderers[0].kwargs["launch_path"] == launch_path
