from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

import pytest
import toolsy_policy.coworld as toolsy_coworld
import toolsy_policy.obs as toolsy_obs
import toolsy_policy.policy as toolsy_policy_module
from mettagrid.simulator import Action
from toolsy_policy.coworld import ToolsyCoworldProcessManager, send_action_message
from toolsy_policy.obs import EntityInfo, GameView, WorldMap, decode_view_from_agent_state
from toolsy_policy.policy import AutoPilocy, Noop, ToolBridge, ToolsyAgentPolicy, ToolsyAutopilotAgentPolicy, ToolsyPolicy
from toolsy_policy.tools import ToolResult, _open_dirs, _step_toward_entity, tool_align, tool_collect, tool_goto, tool_mine

MOVE_DELTAS = {
    "move_north": (-1, 0),
    "move_south": (1, 0),
    "move_west": (0, -1),
    "move_east": (0, 1),
}


def _entity(type_name: str, row: int, col: int, agent_pos: tuple[int, int], **inventory: int) -> EntityInfo:
    ar, ac = agent_pos
    dr, dc = row - ar, col - ac
    entity = EntityInfo(
        type_name=type_name,
        dr=dr,
        dc=dc,
        dist=abs(dr) + abs(dc),
        coherence=inventory.pop("coherence", 0),
        creds=inventory.pop("creds", 0),
        inventory=inventory,
    )
    entity.row = row
    entity.col = col
    entity.team = inventory.pop("team", "")
    return entity


def _view(
    *,
    step: int = 1,
    pos: tuple[int, int] = (0, 0),
    entities: list[EntityInfo] | None = None,
    walls: set[tuple[int, int]] | None = None,
    seen: set[tuple[int, int]] | None = None,
    known_entities: dict[tuple[int, int], str] | None = None,
    team: str = "red",
    coherence: int = 10,
    creds: int = 0,
    cargo: dict[str, int] | None = None,
    gear: dict[str, int] | None = None,
    inventory: dict[str, int] | None = None,
) -> GameView:
    world_map = WorldMap()
    world_map.seen.update(seen or {pos})
    world_map.walls.update(walls or set())
    world_map.entities.update(known_entities or {})
    ar, ac = pos
    relative_walls = [(r - ar, c - ac) for r, c in (walls or set())]
    cargo = {
        "carbon": 0,
        "oxygen": 0,
        "germanium": 0,
        "silicon": 0,
        **(cargo or {}),
    }
    gear = {
        "core_a": 0,
        "core_d": 0,
        "os_a": 0,
        "os_d": 0,
        "gen_a": 0,
        "gen_d": 0,
        "storage_a": 0,
        "storage_d": 0,
        **(gear or {}),
    }
    inventory = dict(inventory or {})
    return GameView(
        step=step,
        coherence=coherence,
        energy=0,
        creds=creds,
        heart=0,
        cargo=cargo,
        total_cargo=sum(cargo.values()),
        max_cargo=10,
        gear=gear,
        total_atk=sum(gear.get(k, 0) for k in ["core_a", "os_a", "gen_a", "storage_a"]),
        total_def=sum(gear.get(k, 0) for k in ["core_d", "os_d", "gen_d", "storage_d"]),
        total_gear=sum(gear.values()),
        vibe="default",
        team=team,
        spawn_r=0,
        spawn_c=0,
        world_map=world_map,
        entities=entities or [],
        walls=relative_walls,
        decoded=SimpleNamespace(center_row=ar, center_col=ac, cells_by_location={}),
        inventory=inventory,
    )


def test_goto_uses_known_world_map_entities_when_target_is_not_visible() -> None:
    view = _view(
        pos=(0, 0),
        seen={(0, 0), (0, 1), (0, 2)},
        known_entities={(0, 2): "market_station"},
    )

    action = next(tool_goto(view, "market", max_ticks=5))

    assert action.name == "move_east"


def test_goto_uses_known_path_instead_of_greedy_dead_end() -> None:
    seen = {
        (0, 0), (0, 1), (0, 2), (0, 3), (0, 4),
        (1, 0), (1, 1), (1, 2), (1, 3), (1, 4),
        (2, 1), (2, 2), (2, 3),
    }
    walls = {(0, 3), (1, 2)}
    view = _view(
        pos=(0, 0),
        entities=[_entity("market_station", 0, 4, (0, 0))],
        walls=walls,
        seen=seen,
        known_entities={(0, 4): "market_station"},
    )

    action = next(tool_goto(view, "market", max_ticks=10))

    assert action.name == "move_south"


def test_navigation_treats_adjacent_agents_as_blockers() -> None:
    view = _view(
        pos=(0, 0),
        entities=[
            _entity("agent", -1, 0, (0, 0)),
            _entity("oxygen_extractor", -3, 3, (0, 0), coherence=10),
        ],
    )
    target = view.entities[1]

    assert "move_north" not in _open_dirs(view)
    assert _step_toward_entity(view, target) != "move_north"


def test_mine_refuses_to_attack_when_combat_eval_has_zero_dps() -> None:
    view = _view(
        pos=(0, 0),
        entities=[_entity("carbon_extractor", 0, 1, (0, 0), coherence=10)],
    )

    with pytest.raises(StopIteration) as stopped:
        next(tool_mine(view, "extractor", max_ticks=5))

    result = stopped.value.value
    assert result.success is False
    assert "winnable" in result.message


def test_collect_targets_dead_extractors_instead_of_nearest_live_extractor() -> None:
    view = _view(
        pos=(0, 0),
        entities=[
            _entity("carbon_extractor", 0, 1, (0, 0), coherence=10),
            _entity("oxygen_extractor", 1, 0, (0, 0), coherence=0),
        ],
    )
    collect = tool_collect(view, max_ticks=5)

    assert next(collect).name == "change_vibe_default"
    assert collect.send(view).name == "move_south"


def test_align_keeps_the_disabled_target_instead_of_bumping_nearest_live_match() -> None:
    view = _view(
        pos=(0, 0),
        entities=[
            _entity("junction", 0, 1, (0, 0), coherence=10),
            _entity("junction", 1, 0, (0, 0), coherence=0),
        ],
        team="red",
    )
    align = tool_align(view, "junction", max_ticks=5)

    assert next(align).name == "change_vibe_default"
    assert align.send(view).name == "move_south"


def test_decode_view_from_agent_state_uses_coworld_obs_grid_and_agent_location() -> None:
    view = decode_view_from_agent_state({
        "type": "agent_state",
        "step": 7,
        "agent": {"location": [10, 20]},
        "obs": {
            "0,0": {
                "tags": ["type:agent", "team:cogs_red"],
                "feats": {"inv:coherence": 9, "inv:creds": 3, "inv:max_cargo": 5},
            },
            "0,1": {
                "tags": ["type:market_station"],
                "feats": {"inv:coherence": 4},
            },
        },
    })

    assert view.step == 7
    assert view.coherence == 9
    assert view.creds == 3
    assert view.team == "red"
    assert view.entities[0].type_name == "market_station"
    assert (view.entities[0].row, view.entities[0].col) == (10, 21)


def test_decode_view_from_agent_state_uses_obs_center_for_world_model_memory() -> None:
    world_map = WorldMap()
    base_state = {
        "type": "agent_state",
        "policy_infos": {"obs_center": [3, 5]},
        "obs": {
            "0,0": {
                "tags": ["type:agent"],
                "feats": {"inv:coherence": 9, "inv:max_cargo": 5},
            },
            "0,1": {
                "tags": ["type:market_station"],
                "feats": {"inv:coherence": 4},
            },
        },
    }

    first = {**base_state, "step": 1, "agent": {"location": [116, 118]}}
    second = {**base_state, "step": 2, "agent": {"location": [115, 117]}}

    decode_view_from_agent_state(first, world_map=world_map)
    decode_view_from_agent_state(second, world_map=world_map)

    assert world_map.entities == {(3, 6): "market_station"}


def test_world_map_infers_center_landmarks_from_team_hub() -> None:
    view = decode_view_from_agent_state({
        "type": "agent_state",
        "step": 7,
        "agent": {"location": [0, 0]},
        "obs": {
            "0,0": {
                "tags": ["type:agent"],
                "feats": {"inv:coherence": 9, "inv:max_cargo": 5},
            },
            "0,1": {
                "tags": ["type:hub", "team:cogs_red"],
                "feats": {},
            },
        },
    })

    assert view.world_map.entities[(25, 26)] == "heart_station"
    assert view.world_map.entities[(23, 26)] == "observatory"
    assert view.world_map.entities[(25, 24)] == "observatory"


def test_local_position_from_globals_uses_cumulative_offsets() -> None:
    assert toolsy_obs._local_position_from_globals({}) is None
    assert toolsy_obs._local_position_from_globals({"lp:north": 3}) == (-3, 0)
    assert toolsy_obs._local_position_from_globals({"lp:south": 2, "lp:west": 1}) == (2, -1)


def test_bridge_returns_noop_when_no_fresh_action_is_available() -> None:
    bridge = ToolBridge()
    view = _view()
    yielded_view = []

    thread = threading.Thread(
        target=lambda: yielded_view.append(bridge.yield_action(Action(name="move_east"))),
    )
    thread.start()

    assert bridge.step(view).name == "move_east"
    thread.join(timeout=1)
    assert yielded_view == [view]
    assert bridge.step(view).name == "noop"


def test_set_autopilocy_schedules_named_autopilocy_without_blocking_llm(monkeypatch) -> None:
    def scripted_tool(view: GameView, max_ticks: int = 2):
        for _ in range(max_ticks):
            yield Action(name="move_east")
        return ToolResult(True, "scripted complete", max_ticks)

    monkeypatch.setitem(toolsy_policy_module.BLOCKING_TOOLS, "scripted", scripted_tool)
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=None)
    view = _view()
    result: list[tuple[GameView, str]] = []

    thread = threading.Thread(
        target=lambda: result.append(policy._dispatch_tool("set_autopilocy", {"name": "scripted", "timeout": 2}, view)),
    )
    thread.start()
    thread.join(timeout=0.2)

    try:
        assert not thread.is_alive()
        assert result == [(view, "Set autopilocy scripted for up to 2 ticks.")]
        assert isinstance(policy.current_auto_pilocy, AutoPilocy)
        assert policy.current_auto_pilocy.name == "scripted"
        assert policy.current_auto_pilocy.status() == {
            "name": "scripted",
            "active": True,
            "state": "ready",
            "ticks_used": 0,
            "timeout": 2,
            "remaining": 2,
        }
        assert policy.infos["auto_pilocy"] == {
            "name": "scripted",
            "active": True,
            "state": "ready",
            "ticks_used": 0,
            "timeout": 2,
            "remaining": 2,
        }
        assert policy.infos["current_auto_pilocy"] == "scripted"
        assert policy.step_view(view).name == "move_east"
        assert policy.infos["auto_pilocy"] == {
            "name": "scripted",
            "active": True,
            "state": "running",
            "ticks_used": 1,
            "timeout": 2,
            "remaining": 1,
        }
        assert policy.step_view(view).name == "move_east"
        assert isinstance(policy.current_auto_pilocy, Noop)
        assert policy.infos["auto_pilocy"] == {
            "name": "Noop",
            "active": False,
            "state": "idle",
            "ticks_used": 0,
            "timeout": None,
            "remaining": None,
        }
        assert policy.step_view(view).name == "noop"
    finally:
        policy._bridge.stop()
        thread.join(timeout=1.0)


def test_new_autopilocy_overrides_current_autopilocy(monkeypatch) -> None:
    def move_tool(action_name: str):
        def _tool(view: GameView, max_ticks: int = 5):
            for _ in range(max_ticks):
                yield Action(name=action_name)
            return ToolResult(True, f"{action_name} complete", max_ticks)

        return _tool

    monkeypatch.setitem(toolsy_policy_module.BLOCKING_TOOLS, "move_east_tool", move_tool("move_east"))
    monkeypatch.setitem(toolsy_policy_module.BLOCKING_TOOLS, "move_west_tool", move_tool("move_west"))
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())
    view = _view()
    first_result: list[tuple[GameView, str]] = []
    second_result: list[tuple[GameView, str]] = []

    first_thread = threading.Thread(
        target=lambda: first_result.append(
            policy._dispatch_tool("set_autopilocy", {"name": "move_east_tool", "timeout": 5}, view)
        ),
    )
    first_thread.start()
    first_thread.join(timeout=0.2)

    try:
        assert not first_thread.is_alive()
        assert first_result == [(view, "Set autopilocy move_east_tool for up to 5 ticks.")]
        assert policy._bridge.step(view).name == "move_east"

        second_thread = threading.Thread(
            target=lambda: second_result.append(
                policy._dispatch_tool("set_autopilocy", {"name": "move_west_tool", "timeout": 1}, view)
            ),
        )
        second_thread.start()
        second_thread.join(timeout=0.2)

        assert not second_thread.is_alive()
        assert second_result == [(view, "Set autopilocy move_west_tool for up to 1 ticks.")]
        assert policy._bridge.step(view).name == "move_west"
        assert isinstance(policy.current_auto_pilocy, Noop)
        assert policy._bridge.step(view).name == "noop"
    finally:
        policy._bridge.stop()
        first_thread.join(timeout=1.0)
        if "second_thread" in locals():
            second_thread.join(timeout=1.0)


class _FakeTextBlock:
    type = "text"
    text = "checking"


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, tool_id: str, name: str, input_: dict):
        self.id = tool_id
        self.name = name
        self.input = input_


class _FakeMessages:
    def create(self, **_kwargs):
        return SimpleNamespace(
            content=[
                _FakeTextBlock(),
                _FakeToolUseBlock("toolu_1", "status", {}),
                _FakeToolUseBlock("toolu_2", "gear_cost", {}),
            ]
        )


class _FakeLlm:
    messages = _FakeMessages()


class _CaptureMessages:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                _FakeTextBlock(),
                _FakeToolUseBlock("toolu_status", "status", {}),
            ]
        )


class _CaptureLlm:
    def __init__(self) -> None:
        self.messages = _CaptureMessages()


class _MacroMessages:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                _FakeTextBlock(),
                _FakeToolUseBlock("toolu_scripted", "set_autopilocy", {"name": "scripted", "timeout": 5}),
            ]
        )


class _MacroLlm:
    def __init__(self) -> None:
        self.messages = _MacroMessages()


class _TextOnlyMessages:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[_FakeTextBlock()])


class _TextOnlyLlm:
    def __init__(self) -> None:
        self.messages = _TextOnlyMessages()


class _FailingMessages:
    def __init__(self, exc: Exception) -> None:
        self.calls = []
        self._exc = exc

    def create(self, **kwargs):
        self.calls.append(kwargs)
        raise self._exc


class _FailingLlm:
    def __init__(self, exc: Exception) -> None:
        self.messages = _FailingMessages(exc)


def _wait_until(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_toolsy_policy_creates_toolsy_agent_for_every_agent() -> None:
    policy = ToolsyPolicy(policy_env_info=SimpleNamespace(), llm_client=_FakeLlm())

    agent_0 = policy.agent_policy(0)
    agent_1 = policy.agent_policy(1)

    assert isinstance(agent_0, ToolsyAgentPolicy)
    assert isinstance(agent_1, ToolsyAgentPolicy)
    assert agent_0 is not agent_1


def test_toolsy_policy_uses_autopilot_when_llm_is_disabled() -> None:
    policy = ToolsyPolicy(policy_env_info=SimpleNamespace(), enable_llm=False)

    agent = policy.agent_policy(0)

    assert isinstance(agent, ToolsyAutopilotAgentPolicy)


def test_toolsy_policy_constructs_bounded_anthropic_client(monkeypatch) -> None:
    captured = {}

    class FakeAnthropic:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))

    policy = ToolsyPolicy(policy_env_info=SimpleNamespace())

    assert policy._llm is not None
    assert captured == {
        "api_key": "test-key",
        "timeout": toolsy_policy_module.LLM_REQUEST_TIMEOUT_SECONDS,
        "max_retries": 0,
    }


def test_autopilot_gear_cost_matches_game_curve() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(gear={"core_a": 1}, creds=20)

    assert policy._gear_cost(view) == 8


def test_autopilot_requires_attack_spread_before_leaving_compound() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)

    assert policy._needs_more_attack_spread(_view(gear={"os_a": 4}, creds=44)) is True
    assert policy._needs_more_attack_spread(
        _view(gear={"core_a": 2, "os_a": 2, "gen_a": 2, "storage_a": 2}, creds=44)
    ) is False


def test_autopilot_maps_compound_before_buying_unknown_attack_gear() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        entities=[_entity("hub", 0, 2, (0, 0))],
        seen={(0, 0), (0, 1), (0, 2)},
        team="red",
        creds=100,
        gear={"storage_a": 1},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name == "map_compound"


def test_autopilot_uses_known_attack_gear_station_after_mapping() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        seen={(0, 0), (0, 1), (0, 2)},
        known_entities={(0, 2): "core_a_station"},
        team="red",
        creds=100,
        gear={"storage_a": 1},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name == "buy_core_a_station"


def test_autopilot_defers_buying_stake_until_after_attack_upgrades() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        entities=[_entity("stake_buy_station", 0, 1, (0, 0))],
        seen={(0, 0), (0, 1)},
        team="red",
        creds=100,
        gear={"storage_a": 1},
        inventory={"red_stake": 0},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name != "buy_stake"


def test_autopilot_buys_first_stake_once_basic_attack_has_creds() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        entities=[_entity("stake_buy_station", 0, 1, (0, 0))],
        seen={(0, 0), (0, 1)},
        team="red",
        creds=120,
        gear={"core_a": 2, "os_a": 1, "gen_a": 1, "storage_a": 1},
        inventory={"red_stake": 0},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name == "buy_stake"


def test_autopilot_maps_compound_when_ready_for_stake_but_station_unknown() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        team="red",
        creds=120,
        gear={"core_a": 1, "os_a": 1, "gen_a": 1, "storage_a": 1},
        inventory={"red_stake": 0},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name == "map_compound_for_stake"


def test_autopilot_returns_to_spawn_when_ready_for_stake_away_from_compound() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(30, 30),
        team="red",
        creds=120,
        gear={"core_a": 1, "os_a": 1, "gen_a": 1, "storage_a": 1},
        inventory={"red_stake": 0},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name == "return_for_stake"


def test_autopilot_stops_late_gear_chasing_after_attack_seven() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        step=3000,
        pos=(0, 0),
        team="red",
        creds=300,
        gear={"core_a": 2, "os_a": 2, "gen_a": 2, "storage_a": 1},
        known_entities={(0, 1): "gen_a_station"},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name != "buy_gen_a_station"


def test_autopilot_waits_until_late_game_to_buy_hearts() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        step=toolsy_policy_module.HEART_RUN_STEP - 1,
        pos=(0, 0),
        known_entities={(25, 25): "heart_station"},
        team="red",
        creds=100,
        gear={"core_a": 2, "os_a": 1, "gen_a": 1, "storage_a": 1},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name != "buy_hearts"


def test_autopilot_scouts_past_visible_unwinnable_extractor() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        team="red",
        gear={"core_a": 1},
        entities=[
            _entity("oxygen_extractor", 0, 3, (0, 0), coherence=20, core_d=5),
        ],
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name == "seek_extractors"


def test_autopilot_hacks_visible_nodes_once_attack_six_is_ready() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        team="red",
        gear={"core_a": 2, "os_a": 2, "gen_a": 1, "storage_a": 1},
        inventory={"red_stake": 1},
        entities=[
            _entity("hub", 0, 1, (0, 0), team="red"),
            _entity("junction", 0, 3, (0, 0), coherence=10, os_d=1),
        ],
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name == "hack_junction"


def test_autopilot_does_not_hack_nodes_at_attack_five() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        team="red",
        gear={"core_a": 2, "os_a": 1, "gen_a": 1, "storage_a": 1},
        inventory={"red_stake": 1},
        entities=[
            _entity("hub", 0, 1, (0, 0), team="red"),
            _entity("junction", 0, 3, (0, 0), coherence=10, os_d=1),
        ],
    )

    policy._schedule_next_macro(view)

    assert not policy._macro_name.startswith("hack_")


def test_autopilot_targets_known_network_reachable_node() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        team="red",
        gear={"core_a": 2, "os_a": 2, "gen_a": 1, "storage_a": 1},
        inventory={"red_stake": 1},
        entities=[
            _entity("hub", 0, 1, (0, 0), team="red"),
        ],
        known_entities={(0, 10): "junction"},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name == "hack_junction"


def test_autopilot_keeps_economy_when_heart_is_unknown_at_basic_creds() -> None:
    policy = ToolsyAutopilotAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0)
    view = _view(
        pos=(0, 0),
        team="red",
        creds=100,
        gear={"core_a": 2, "os_a": 1, "gen_a": 1, "storage_a": 1},
    )

    policy._schedule_next_macro(view)

    assert policy._macro_name != "go_center_for_heart"


def test_coworld_process_manager_starts_one_process_per_agent(monkeypatch) -> None:
    created_processes = []

    class FakeProcess:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.started = False
            self.terminated = False
            created_processes.append(self)

        def start(self) -> None:
            self.started = True

        def is_alive(self) -> bool:
            return self.started and not self.terminated

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.terminated = True

        def join(self, timeout: float) -> None:
            return None

    class FakeContext:
        def Process(self, **kwargs):
            return FakeProcess(**kwargs)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("toolsy_policy.coworld.multiprocessing.get_context", lambda method: FakeContext())
    manager = ToolsyCoworldProcessManager([
        "ws://127.0.0.1:8899/agent/0",
        "ws://127.0.0.1:8899/agent/1",
    ])

    manager.start()

    assert [process.kwargs["args"] for process in created_processes] == [
        (0, "ws://127.0.0.1:8899/agent/0"),
        (1, "ws://127.0.0.1:8899/agent/1"),
    ]
    assert [process.kwargs["name"] for process in created_processes] == [
        "toolsy-coworld-a0",
        "toolsy-coworld-a1",
    ]
    assert all(process.started for process in created_processes)

    manager.shutdown()

    assert all(process.terminated for process in created_processes)


def test_coworld_send_action_message_returns_false_when_socket_closes() -> None:
    class ClosedWebsocket:
        def send(self, message: str) -> None:
            raise BrokenPipeError("closed")

    assert send_action_message(ClosedWebsocket(), "noop", {}) is False


def test_coworld_llm_client_is_bounded(monkeypatch) -> None:
    captured = {}

    class FakeAnthropic:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))

    client = toolsy_coworld._make_llm_client()

    assert isinstance(client, FakeAnthropic)
    assert captured == {
        "api_key": "test-key",
        "timeout": toolsy_policy_module.LLM_REQUEST_TIMEOUT_SECONDS,
        "max_retries": 0,
    }


def test_llm_turn_returns_results_for_every_tool_use_block() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())
    view = _view()

    returned_view = policy._do_llm_turn(view)

    assert returned_view is view
    tool_result_messages = [
        message for message in policy._messages
        if message["role"] == "user"
        and isinstance(message["content"], list)
        and any(block.get("type") == "tool_result" for block in message["content"])
    ]
    assert len(tool_result_messages) == 1
    result_ids = [
        block["tool_use_id"]
        for block in tool_result_messages[0]["content"]
        if block.get("type") == "tool_result"
    ]
    assert result_ids == ["toolu_1", "toolu_2"]


def test_llm_turn_uses_bounded_provider_timeout() -> None:
    llm = _CaptureLlm()
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=llm)

    policy._do_llm_turn(_view())

    assert llm.messages.calls[0]["timeout"] == toolsy_policy_module.LLM_REQUEST_TIMEOUT_SECONDS


def test_llm_loop_logs_provider_errors_to_agent_log() -> None:
    policy = ToolsyAgentPolicy(
        policy_env_info=SimpleNamespace(),
        agent_id=0,
        llm_client=_FailingLlm(TimeoutError("provider timed out")),
    )
    thread = threading.Thread(target=policy._llm_loop, daemon=True)
    thread.start()

    try:
        assert policy._bridge.step(_view(step=1)).name == "noop"
        policy.trigger_llm(source="test")
        assert _wait_until(lambda: "llm_error" in policy.infos)
        assert policy.infos["llm_error"] == "provider timed out"
        assert "LLM ERROR TimeoutError: provider timed out" in policy.infos["llm_log"]
    finally:
        policy._bridge.stop()
        thread.join(timeout=1.0)


def test_llm_turn_waits_for_fresh_view_after_scheduling_action_policy(monkeypatch) -> None:
    def scripted_tool(view: GameView, max_ticks: int = 5):
        for _ in range(max_ticks):
            yield Action(name="move_east")
        return ToolResult(True, "scripted complete", max_ticks)

    monkeypatch.setitem(toolsy_policy_module.BLOCKING_TOOLS, "scripted", scripted_tool)
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_MacroLlm())
    first_view = _view(step=1)
    next_view = _view(step=2)
    returned_views: list[GameView] = []
    thread = threading.Thread(target=lambda: returned_views.append(policy._do_llm_turn(first_view)))

    thread.start()
    thread.join(timeout=0.2)

    try:
        assert thread.is_alive()
        assert policy._bridge.step(next_view).name == "move_east"
        time.sleep(0.1)
        assert thread.is_alive()
        for step in range(3, 7):
            assert policy._bridge.step(_view(step=step)).name == "move_east"
        assert policy._bridge.step(_view(step=7)).name == "noop"
        thread.join(timeout=1.0)
        assert [view.step for view in returned_views] == [7]
    finally:
        policy._bridge.stop()
        thread.join(timeout=1.0)


def test_llm_turn_does_not_requery_while_action_policy_is_active(monkeypatch) -> None:
    def scripted_tool(view: GameView, max_ticks: int = 5):
        for _ in range(max_ticks):
            yield Action(name="move_east")
        return ToolResult(True, "scripted complete", max_ticks)

    llm = _MacroLlm()
    monkeypatch.setitem(toolsy_policy_module.BLOCKING_TOOLS, "scripted", scripted_tool)
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=llm)
    returned_views: list[GameView] = []
    thread = threading.Thread(target=lambda: returned_views.append(policy._do_llm_turn(_view(step=1))))

    thread.start()
    try:
        assert _wait_until(lambda: len(llm.messages.calls) == 1)
        assert policy._bridge.step(_view(step=2)).name == "move_east"
        assert policy._bridge.step(_view(step=3)).name == "move_east"
        time.sleep(0.1)
        assert len(llm.messages.calls) == 1
        assert policy._bridge.step(_view(step=4)).name == "move_east"
        assert policy._bridge.step(_view(step=5)).name == "move_east"
        assert policy._bridge.step(_view(step=6)).name == "move_east"
        assert policy._bridge.step(_view(step=7)).name == "noop"
        thread.join(timeout=1.0)
        assert len(llm.messages.calls) == 1
        assert [view.step for view in returned_views] == [7]
    finally:
        policy._bridge.stop()
        thread.join(timeout=1.0)


def test_llm_log_does_not_write_request_content_to_stdout(capsys) -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())

    policy._do_llm_turn(_view(step=1))
    policy._do_llm_turn(_view(step=2))

    stdout = capsys.readouterr().out
    assert stdout == ""
    assert policy._infos["llm_log"].count("Step 1.") == 1
    assert policy._infos["llm_log"].count("Step 2.") == 1


def test_llm_loop_waits_for_explicit_trigger_before_querying_llm() -> None:
    llm = _TextOnlyLlm()
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=llm)
    thread = threading.Thread(target=policy._llm_loop, daemon=True)
    thread.start()

    try:
        assert policy._bridge.step(_view(step=1)).name == "noop"
        time.sleep(0.1)
        assert len(llm.messages.calls) == 0

        trigger_id = policy.trigger_llm(source="widget")

        assert _wait_until(lambda: len(llm.messages.calls) == 1)
        assert policy.infos["llm_brain"]["last_trigger_id"] == trigger_id

        assert policy._bridge.step(_view(step=1)).name == "noop"
        time.sleep(0.1)
        assert len(llm.messages.calls) == 1

        policy.trigger_llm(source="widget")
        assert _wait_until(lambda: len(llm.messages.calls) == 2)
    finally:
        policy._bridge.stop()
        thread.join(timeout=1.0)


def test_step_view_auto_triggers_llm_once_per_new_tick() -> None:
    llm = _TextOnlyLlm()
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=llm)

    try:
        assert policy.step_view(_view(step=1)).name == "noop"
        assert _wait_until(lambda: len(llm.messages.calls) == 1)

        assert policy.step_view(_view(step=1)).name == "noop"
        time.sleep(0.1)
        assert len(llm.messages.calls) == 1

        assert policy.step_view(_view(step=2)).name == "noop"
        assert _wait_until(lambda: len(llm.messages.calls) == 2)
    finally:
        policy._bridge.stop()
        if policy._thread is not None:
            policy._thread.join(timeout=1.0)


def test_coworld_agent_state_trigger_runs_policy_llm_once() -> None:
    assert hasattr(toolsy_coworld, "sync_policy_llm_trigger")

    class TriggerPolicy:
        def __init__(self) -> None:
            self.sources: list[str] = []

        def trigger_llm(self, source: str) -> None:
            self.sources.append(source)

    policy = TriggerPolicy()

    last_trigger_id = toolsy_coworld.sync_policy_llm_trigger(policy, {"llm_trigger_id": 2}, 0)
    assert last_trigger_id == 2
    assert policy.sources == ["ui"]

    same_trigger_id = toolsy_coworld.sync_policy_llm_trigger(policy, {"llm_trigger_id": 2}, last_trigger_id)
    assert same_trigger_id == 2
    assert policy.sources == ["ui"]


def test_current_goals_are_added_to_llm_context_and_tool_list() -> None:
    llm = _CaptureLlm()
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=llm)
    policy.update_current_goals("Capture two junctions before buying hearts.\nSell cargo at market.", source="widget")

    returned_view = policy._do_llm_turn(_view())

    assert returned_view is not None
    call = llm.messages.calls[0]
    add_goal_tool = next(tool for tool in call["tools"] if tool["name"] == "add_goal")
    assert not any(tool["name"] == "goals" for tool in call["tools"])
    goals_schema = add_goal_tool["input_schema"]["properties"]
    assert goals_schema["goals"]["type"] == "array"
    assert goals_schema["goals"]["items"]["type"] == "string"
    assert "prompt" not in goals_schema
    set_autopilocy_tool = next(tool for tool in call["tools"] if tool["name"] == "set_autopilocy")
    set_autopilocy_schema = set_autopilocy_tool["input_schema"]["properties"]
    assert set_autopilocy_schema["name"]["enum"] == list(toolsy_policy_module.BLOCKING_TOOLS)
    assert set_autopilocy_schema["timeout"]["type"] == "integer"
    assert not any(tool["name"] == "explore_compound" for tool in call["tools"])
    assert any(tool["name"] == "complete_goal" for tool in call["tools"])
    assert any(tool["name"] == "update_goal" for tool in call["tools"])
    request_text = "\n".join(
        block["text"] if isinstance(message["content"], list) else message["content"]
        for message in call["messages"]
        for block in (message["content"] if isinstance(message["content"], list) else [{"text": message["content"]}])
        if isinstance(block, dict) and "text" in block
    )
    assert "Active goals updated by widget:\nCapture two junctions before buying hearts.\nSell cargo at market." in request_text
    assert "Re-evaluate goals:" in request_text
    assert 'set_autopilocy(name="explore_compound", timeout=10)' in request_text
    assert "explore_compound(max_ticks=" not in request_text
    assert "add_goal(goals=[...])" in request_text
    assert "goals(goals=[...])" not in request_text
    assert "goals(prompt=" not in request_text
    assert "complete_goal" in request_text
    assert "update_goal" in request_text
    assert "Capture two junctions before buying hearts." in request_text
    assert "Sell cargo at market." in request_text


def test_add_goal_tool_updates_current_goals_for_future_turns() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())
    policy.update_current_goals("Mine carbon", source="widget")

    view, result = policy._dispatch_tool(
        "add_goal",
        {"goals": ["Sell cargo", "Buy attack.", "Mine carbon"]},
        _view(),
    )

    assert view is not None
    assert result == "Goals added."
    assert policy.infos["current_goals"] == "Mine carbon\nSell cargo\nBuy attack."
    assert [task["text"] for task in policy.infos["goal_tasks"] if not task["completed"]] == [
        "Mine carbon", "Sell cargo", "Buy attack.",
    ]


def test_goal_completion_moves_goal_to_diary_and_omits_it_from_future_context() -> None:
    llm = _CaptureLlm()
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=llm)
    policy.update_current_goals("Mine carbon\nSell cargo", source="widget")
    first_goal_id = policy.infos["goal_tasks"][0]["id"]

    view, result = policy._dispatch_tool("complete_goal", {"goal_id": first_goal_id}, _view(step=12))

    assert view is not None
    assert result == "Goal marked complete."
    tasks = policy.infos["goal_tasks"]
    assert tasks[0]["completed"] is True
    assert policy.infos["current_goals"] == "Sell cargo"
    assert any(entry["event"] == "Completed goal: Mine carbon" for entry in policy.infos["diary"])

    policy._do_llm_turn(_view(step=13))
    request_text = "\n".join(
        block["text"] if isinstance(message["content"], list) else message["content"]
        for message in llm.messages.calls[0]["messages"]
        for block in (message["content"] if isinstance(message["content"], list) else [{"text": message["content"]}])
        if isinstance(block, dict) and "text" in block
    )
    assert "Re-evaluate goals:" in request_text
    assert "Sell cargo" in request_text
    assert "Mine carbon" not in request_text


def test_update_goal_tool_edits_active_goal_text() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())
    policy.update_current_goals("Mine carbon\nSell cargo", source="widget")
    second_goal_id = policy.infos["goal_tasks"][1]["id"]

    view, result = policy._dispatch_tool("update_goal", {"goal_id": second_goal_id, "text": "Sell cargo at market"}, _view())

    assert view is not None
    assert result == "Goal updated."
    assert policy.infos["current_goals"] == "Mine carbon\nSell cargo at market"


def test_coworld_agent_state_syncs_current_goals_into_policy() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())

    toolsy_coworld.sync_policy_goals_from_agent_state(
        policy,
        {
            "type": "agent_state",
            "policy_infos": {"current_goals": "Keep 20 creds reserved for stakes."},
        },
    )

    assert policy.infos["current_goals"] == "Keep 20 creds reserved for stakes."


def test_coworld_agent_state_current_goals_does_not_drop_active_goals() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())
    policy.update_current_goals(
        "Explore compound\nJoin team\nUpgrade attack",
        source="widget",
    )

    toolsy_coworld.sync_policy_goals_from_agent_state(
        policy,
        {
            "type": "agent_state",
            "policy_infos": {"current_goals": "Find market\nSell cargo"},
        },
    )

    assert policy.infos["current_goals"] == "Explore compound\nJoin team\nUpgrade attack\nFind market\nSell cargo"
    assert [task["completed"] for task in policy.infos["goal_tasks"]] == [False, False, False, False, False]


def test_coworld_agent_state_empty_goal_tasks_do_not_clear_policy_goals() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())
    policy.update_current_goals(
        "Explore compound\nJoin team\nUpgrade attack",
        source="tool",
    )

    toolsy_coworld.sync_policy_goals_from_agent_state(
        policy,
        {
            "type": "agent_state",
            "policy_infos": {"goal_tasks": []},
        },
    )

    assert policy.infos["current_goals"] == "Explore compound\nJoin team\nUpgrade attack"
    assert [task["text"] for task in policy.infos["goal_tasks"]] == [
        "Explore compound",
        "Join team",
        "Upgrade attack",
    ]


def test_coworld_agent_state_syncs_structured_goal_tasks_into_policy() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())

    toolsy_coworld.sync_policy_goals_from_agent_state(
        policy,
        {
            "type": "agent_state",
            "policy_infos": {
                "goal_tasks": [
                    {"id": "goal-1", "text": "Mine carbon", "completed": True},
                    {"id": "goal-2", "text": "Sell cargo", "completed": False},
                ]
            },
        },
    )

    assert policy.infos["current_goals"] == "Sell cargo"
    assert policy.infos["goal_tasks"] == [
        {"id": "goal-1", "text": "Mine carbon", "completed": True},
        {"id": "goal-2", "text": "Sell cargo", "completed": False},
    ]


def test_toolsy_diary_records_important_events() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())
    policy._record_diary_events(_view(
        pos=(0, 0),
        creds=2,
        cargo={"carbon": 0},
        gear={"core_a": 0},
        inventory={"red_dividends": 5},
        entities=[_entity("junction", 0, 1, (0, 0), coherence=10)],
    ))

    policy._record_diary_events(_view(creds=2, gear={"core_a": 1}))
    policy._record_diary_events(_view(creds=2, cargo={"carbon": 10}, gear={"core_a": 1}))
    policy._record_diary_events(_view(creds=7, cargo={"carbon": 0}, gear={"core_a": 1}))
    policy._record_diary_events(_view(
        creds=7,
        gear={"core_a": 1},
        inventory={"red_dividends": 5},
        entities=[_entity("junction", 0, 1, (0, 0), coherence=10)],
    ))
    policy._record_diary_events(_view(
        creds=7,
        gear={"core_a": 1},
        entities=[_entity("junction", 0, 1, (0, 0), coherence=0)],
    ))
    policy._record_diary_events(_view(
        creds=7,
        gear={"core_a": 1},
        inventory={"red_dividends": 5},
        entities=[_entity("junction", 0, 1, (0, 0), coherence=0, team="red")],
    ))
    policy._record_diary_events(_view(
        creds=12,
        gear={"core_a": 1},
        inventory={"red_dividends": 0},
        entities=[_entity("junction", 0, 1, (0, 0), coherence=0, team="red")],
    ))
    policy._record_diary_events(_view(coherence=0, creds=12, gear={"core_a": 1}))

    diary_text = "\n".join(entry["event"] for entry in policy.infos["diary"])
    assert "Upgraded core_a to 1" in diary_text
    assert "Collected cargo: +10 carbon" in diary_text
    assert "Sold cargo: -10 carbon, +5 creds" in diary_text
    assert "Won fight: disabled junction" in diary_text
    assert "Aligned junction to red" in diary_text
    assert "Claimed dividends: +5 creds from red" in diary_text
    assert "Lost fight: rebooting" in diary_text


def test_toolsy_diary_maintains_full_history() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())

    for index in range(55):
        policy._step_num = index
        policy._add_diary_event(f"event {index}")

    assert len(policy.infos["diary"]) == 55
    assert policy.infos["diary"][0] == {"step": 0, "event": "event 0"}
    assert policy.infos["diary"][-1] == {"step": 54, "event": "event 54"}


def test_toolsy_agent_exposes_diary_policy_widget() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())

    assert policy.policy_widgets == [
        {"id": "toolsy_autopilocy", "module": "toolsy_autopilocy", "title": "AutoPilocy()", "config": {}},
        {"id": "toolsy_goals", "module": "toolsy_goals", "title": "Goals", "config": {}},
        {"id": "toolsy_diary", "module": "toolsy_diary", "title": "Diary", "config": {}},
        {"id": "toolsy_world_model", "module": "toolsy_world_model", "title": "World Model", "config": {}},
    ]


def test_toolsy_agent_includes_policy_widgets_in_coworld_infos() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())

    assert policy.infos["policy_widgets"] == policy.policy_widgets


def test_toolsy_agent_exposes_world_model_snapshot_in_policy_infos() -> None:
    policy = ToolsyAgentPolicy(policy_env_info=SimpleNamespace(), agent_id=0, llm_client=_FakeLlm())
    view = _view(
        pos=(10, 10),
        seen={(10, 10), (10, 11), (9, 10), (8, 8)},
        walls={(9, 10)},
        known_entities={(10, 11): "hub", (8, 8): "junction"},
    )

    policy._update_world_model_info(view)

    assert policy.infos["world_model"] == {
        "center": [10, 10],
        "seen_count": 4,
        "seen_bounds": {
            "min_row": 8,
            "max_row": 10,
            "min_col": 8,
            "max_col": 11,
        },
        "wall_count": 1,
        "walls": [
            {
                "row": 9,
                "col": 10,
                "dr": -1,
                "dc": 0,
                "dist": 1,
            },
        ],
        "entity_count": 2,
        "entities": [
            {
                "type": "hub",
                "row": 10,
                "col": 11,
                "dr": 0,
                "dc": 1,
                "dist": 1,
                "age": 0,
                "level": 0,
                "alignment": "",
            },
            {
                "type": "junction",
                "row": 8,
                "col": 8,
                "dr": -2,
                "dc": -2,
                "dist": 4,
                "age": 0,
                "level": 0,
                "alignment": "",
            },
        ],
    }
