"""Runtime smoke: the assembled idle agent steps cleanly (design §1)."""

from __future__ import annotations

import numpy as np
import pytest

import players.crewrift.crewborg as crewborg
from players.crewrift.crewborg.agent_tracking import build_occupancy_substrate
from players.crewrift.crewborg.coworld.scene import SceneState
from players.crewrift.crewborg.map import MapData, MapPoint, MapRect, PrebakedMap
from players.crewrift.crewborg.nav import NavGraph
from players.crewrift.crewborg.tests import sprite_wire as w
from players.crewrift.crewborg.types import Observation
from players.player_sdk.trace import ListMetricsSink, ListTraceSink


def _tiny_map() -> MapData:
    return MapData(
        width=2,
        height=2,
        tasks=(),
        vents=(),
        rooms=(),
        button=MapRect(x=0, y=0, w=1, h=1),
        home=MapPoint(x=0, y=0),
    )


def _tiny_nav() -> NavGraph:
    return NavGraph(
        walkability=np.ones((2, 2), dtype=bool),
        cell_size=1,
        rows=2,
        cols=2,
        node_point={(0, 0): (0, 0)},
        adjacency={(0, 0): []},
        reachable={(0, 0)},
        button_anchor=(0, 0),
    )


def test_idle_runtime_holds_neutral_mask_and_tracks_ticks() -> None:
    trace = ListTraceSink()
    runtime = crewborg.build_runtime(trace_sink=trace)
    scene = SceneState()

    last = None
    for tick in range(1, 6):
        scene.apply(w.clear_objects() + w.tick_marker(tick))
        last = runtime.step(Observation(scene=scene, tick=scene.tick))

    assert runtime.active_mode_name == "idle"
    assert last is not None and last.held_mask == 0
    assert runtime.belief.ticks_observed == 5
    assert runtime.belief.messages_applied == 5
    assert runtime.belief.map is not None  # baked at startup
    assert runtime.belief.nav is not None  # prebuilt at startup
    assert runtime.belief.agent_tracking.substrate is not None  # prebuilt at startup
    runtime.close()


def test_idle_runtime_emits_canonical_trace_events() -> None:
    trace = ListTraceSink()
    metrics = ListMetricsSink()
    runtime = crewborg.build_runtime(trace_sink=trace, metrics_sink=metrics)
    scene = SceneState()
    scene.apply(w.clear_objects() + w.tick_marker(1))
    runtime.step(Observation(scene=scene, tick=scene.tick))
    runtime.close()

    names = set(trace.names())
    # Every per-tick boundary the SDK traces should appear for a healthy loop,
    # including the strategy seam: build_runtime must thread the sinks into the
    # SynchronousStrategyRunner so its telemetry is not silently dropped.
    assert {
        "perception",
        "belief_updated",
        "action_intent",
        "act_command",
        "strategy_evaluated",
    } <= names
    assert any(sample.name == "cyborg.strategy.decide_ms" for sample in metrics.samples)


def test_build_runtime_uses_prebaked_map_and_nav_by_default(monkeypatch) -> None:
    map_data = _tiny_map()
    nav = _tiny_nav()
    substrate = build_occupancy_substrate(nav, map_data)

    monkeypatch.setattr(
        crewborg,
        "load_croatoan_prebaked",
        lambda: PrebakedMap(
            map_data=map_data,
            nav=nav,
            tracking_substrate=substrate,
            metadata={},
        ),
    )

    runtime = crewborg.build_runtime()
    assert runtime.belief.map is map_data
    assert runtime.belief.nav is nav
    assert runtime.belief.agent_tracking.substrate is substrate
    runtime.close()


def test_runtime_does_not_rebuild_nav_when_prebaked_nav_exists(monkeypatch) -> None:
    map_data = _tiny_map()
    nav = _tiny_nav()

    def fail_build_nav_graph(*_args: object, **_kwargs: object) -> NavGraph:
        raise AssertionError("runtime should keep the prebuilt nav graph")

    monkeypatch.setattr("players.crewrift.crewborg.types.build_nav_graph", fail_build_nav_graph)

    runtime = crewborg.build_runtime(map_data=map_data, nav=nav)
    try:
        scene = SceneState()
        scene.apply(w.walkability_sprite(1, [[True, True], [True, True]]) + w.tick_marker(1))
        runtime.step(Observation(scene=scene, tick=scene.tick))

        assert runtime.belief.nav is nav
        assert runtime.belief.nav_walkability_checked
    finally:
        runtime.close()


def test_runtime_rejects_prebaked_nav_that_does_not_match_streamed_map() -> None:
    runtime = crewborg.build_runtime(map_data=_tiny_map(), nav=_tiny_nav())
    try:
        scene = SceneState()
        scene.apply(w.walkability_sprite(1, [[True, True], [True, False]]) + w.tick_marker(1))

        with pytest.raises(ValueError, match="prebaked nav walkability mask"):
            runtime.step(Observation(scene=scene, tick=scene.tick))
    finally:
        runtime.close()
