from __future__ import annotations

import asyncio
from pathlib import Path

from cogony.web.server import WebRenderer


def test_world_model_widget_has_merged_object_map(tmp_path: Path) -> None:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text("<!doctype html>")
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "collectWorldObjects(data, context)" in response.text
    assert (
        "function renderWorldObjectMap(objects, container, bounds = {}, context = {}, observedCoords = new Set())"
        in response.text
    )
    assert "world-object-map-host" in response.text
    assert "world-object-cell object" in response.text
    assert "availableWidth / Math.max(1, cols)" in response.text
    assert "availableHeight / Math.max(1, rows)" in response.text
    assert "function worldObjectMapZoomForContext(context, zoomBounds = null)" in response.text
    assert "container.onwheel = event =>" in response.text
    assert "event.preventDefault();" in response.text
    assert "context.state.worldObjectMapZoom = nextZoom;" in response.text
    assert "renderWorldObjectMap(objects, container, bounds, context, observedCoords)" in response.text
    assert "renderWorldObjectMap(objects, mapHost, model.seen_bounds || {}, context, observedCoords)" in response.text
    assert "renderWorldObjectDetails(objects, detailHost, context)" in response.text
    assert 'data-world-model-mode=' not in response.text
    assert "collectWorldObjects(data).slice" not in response.text
    assert "Math.min(...xs, 0)" not in response.text


def test_world_model_object_map_uses_stable_world_coordinates(tmp_path: Path) -> None:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text("<!doctype html>")
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "world-object-detail" in response.text
    assert "world-object-prop" in response.text
    assert "world-object-token" in response.text
    assert "currently seen" in response.text
    assert "remembered" in response.text
    assert "x: col ?? dc" in response.text
    assert "y: row ?? dr" in response.text
    assert "rememberWorldObjects(context, currentObjects)" in response.text
    assert "mergeWorldObjectLists(collectRememberedWorldObjects(context), currentObjects)" in response.text
    assert "bounds.min_col" in response.text
    assert "bounds.max_row" in response.text


def test_world_model_anchors_current_obs_with_agent_center_and_movement_fallback(tmp_path: Path) -> None:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text("<!doctype html>")
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function observationCenterForData(data, context, fallbackCenter = null)" in response.text
    assert "data.obs_center || data.__obs_center__" in response.text
    assert "function updateEstimatedAgentCenter(context, data, obsCenter)" in response.text
    assert "last_action_move" in response.text
    assert "lastMovementTickByAgent" in response.text
    assert "move_north: [-1, 0]" in response.text
    assert "move_south: [1, 0]" in response.text
    assert "move_west: [0, -1]" in response.text
    assert "move_east: [0, 1]" in response.text
    assert "const row = obsCenter ? obsCenter[0] + dr : null" in response.text
    assert "const currentObjects = collectWorldObjects(data, context)" in response.text


def test_world_model_does_not_persist_transient_obs_grid_objects(tmp_path: Path) -> None:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text("<!doctype html>")
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const WORLD_OBJECT_MEMORY_VERSION = 3;" in response.text
    assert "source: 'world_model'" in response.text
    assert "source: 'obs_grid'" in response.text
    assert "if (object.source === 'obs_grid') return;" in response.text


def test_world_model_map_zoom_is_persisted_per_widget(tmp_path: Path) -> None:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text("<!doctype html>")
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const WORLD_OBJECT_MIN_CELL_PX = 2;" in response.text
    assert "const WORLD_OBJECT_MAX_CELL_PX = 76;" in response.text
    assert "function worldObjectZoomBounds(container, cols, rows)" in response.text
    assert "minZoom: 1" in response.text
    assert "maxZoom: Math.max(1, WORLD_OBJECT_MAX_CELL_PX / Math.max(1, baseCellSize))" in response.text
    assert "Math.round(zoomBounds.baseCellSize * zoom)" in response.text
    assert "context.saveState();" in response.text
    assert "worldObjectMapZoom" in response.text


def test_world_model_mouse_wheel_scroll_down_zooms_in(tmp_path: Path) -> None:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text("<!doctype html>")
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert (
        "previousZoom * (event.deltaY > 0 ? WORLD_OBJECT_ZOOM_STEP : 1 / WORLD_OBJECT_ZOOM_STEP)"
        in response.text
    )
    assert (
        "previousZoom * (event.deltaY < 0 ? WORLD_OBJECT_ZOOM_STEP : 1 / WORLD_OBJECT_ZOOM_STEP)"
        not in response.text
    )


def test_world_model_recenters_after_agent_client_action(tmp_path: Path) -> None:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text("<!doctype html>")
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function requestWorldModelRecenterOnAgent(agentId = selectedAgentId)" in response.text
    assert "if (AGENT_CLIENT_MODE) requestWorldModelRecenterOnAgent(selectedAgentId);" in response.text
    assert (
        "function recenterWorldObjectMapOnAgent(container, objects, minX, minY, cellSize, context = {})"
        in response.text
    )
    assert "const self = objects.find(object => object.props?.self" in response.text
    assert "container.scrollLeft = Math.max(0, targetLeft);" in response.text
    assert "container.scrollTop = Math.max(0, targetTop);" in response.text
    assert "recenterWorldObjectMapOnAgent(container, placed, minX, minY, cellSize, context);" in response.text


def test_world_model_object_clicks_open_bottom_info_panel(tmp_path: Path) -> None:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text("<!doctype html>")
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "if (event.target.closest('.world-object-cell.object')) return;" in response.text
    assert "function toggleWorldObjectInfoCollapsed(context)" in response.text
    assert "world-object-info-toggle" in response.text
    assert "context.state.worldObjectInfoCollapsed = false;" in response.text
    assert "context.state.worldObjectInfoOpen" not in response.text
    assert "world-object-info-close" not in response.text
    assert "Close info panel" not in response.text
