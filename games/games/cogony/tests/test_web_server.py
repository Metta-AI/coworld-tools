from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import cogony.web.server as web_server
from cogony.web.server import (
    WebRenderer,
    _browser_command,
    _browser_profile_pids,
    _launch_managed_browser,
    _llm_log_delta,
    _ManagedBrowser,
    build_agent_state_replay,
    build_panel_step_replay,
    build_policy_agent_state_replay,
    next_websocket_agent_id,
)


def _clear_codex_browser_env(monkeypatch) -> None:
    for name in ("CODEX_SHELL", "CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE"):
        monkeypatch.delenv(name, raising=False)


def test_web_renderer_serves_panel_shell_from_root(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "Cogony Panels" in response.text
    assert 'id="mettascope"' not in response.text
    assert "/wasm/mettascope.html?ws=" not in response.text
    assert "id: 'global_viewer', module: 'global_viewer', title: 'Viewer', config: {}" in response.text
    assert "renderGlobalWebGpuViewer" in response.text
    assert "new WebSocket(globalWsUrl())" in response.text
    assert "const url = POLICY_DEBUGGER_MODE ? policyDebugWsUrl(selectedAgentId) : agentWsUrl(selectedAgentId);" in response.text
    assert "new WebSocket(url)" in response.text
    assert "expandedLlmTicks" in response.text
    assert "details.tick-section" in response.text
    assert "no LLM log" not in response.text
    assert 'id="ws-status"' in response.text
    assert 'id="heartbeat-status"' in response.text
    assert "recordHeartbeat(message)" in response.text
    assert "forwardMettascopeKey" not in response.text
    assert "METTASCOPE_KEYS" not in response.text
    assert "handleViewerShortcut" in response.text
    assert "isQuitShortcut" in response.text
    assert "event.metaKey" in response.text
    assert "installUnloadQuitHandler" in response.text
    assert "if (!quitRequested) return;" in response.text
    assert "adminCommand('quit')" in response.text
    assert "agentWsUrl" in response.text
    assert "agentDataFromState" in response.text
    assert "connectGlobalStream" in response.text
    assert "connectPolicyDebugStream" in response.text
    assert "sendAgentAction" in response.text
    assert 'id="admin-stop"' not in response.text
    assert 'id="admin-play"' not in response.text
    assert 'id="admin-frame"' not in response.text
    assert 'id="admin-step-on-action"' not in response.text
    assert 'id="admin-speed"' not in response.text
    assert 'id="admin-speed-set"' not in response.text


def test_web_renderer_uses_named_client_html_entrypoints(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    assert not (web_server._WEB_DIR / "panels.html").exists()
    assert (web_server._WEB_DIR / "global-client.html").is_file()
    assert (web_server._WEB_DIR / "agent-client.html").exists()

    global_response = asyncio.run(renderer._serve_global_client(None))  # type: ignore[arg-type]
    agent_response = asyncio.run(renderer._serve_agent_client(None))  # type: ignore[arg-type]

    assert global_response.text == (web_server._WEB_DIR / "global-client.html").read_text()
    assert agent_response.text == (web_server._WEB_DIR / "agent-client.html").read_text()


def test_panel_shell_renders_agent_metadata_in_global_header_and_agent_status_widget(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert 'data-agent-header-status' in response.text
    assert '<span id="selected-agent-status" class="agent-header-status selected-agent-status" data-agent-header-status></span>' in response.text
    assert '<span class="agent-header-status" data-agent-header-status></span>' not in response.text
    assert "{ id: 'agent_status', module: 'agent_status', title: 'Agent', config: {} }" in response.text
    assert "registerPolicyWidgetModule('agent_status'" in response.text
    assert "function renderAgentStatusWidget(data, el)" in response.text
    assert "class=\"agent-status-compact\" data-agent-header-status" in response.text
    assert "function currentVibeFromAgent(agent = {}, data = {})" in response.text
    assert "function agentHeaderDataFromGlobalStep(message)" in response.text
    assert "function currentAgentHeaderData()" in response.text
    assert "function renderSelectedAgentStatus(data = currentAgentHeaderData())" in response.text
    assert "document.querySelectorAll('[data-agent-header-status]')" in response.text
    assert "['agent_id', agentId]" in response.text
    assert "['agent_name', agentName]" in response.text
    assert "['current_tick', tick]" in response.text
    assert "['last_action', lastAction]" in response.text
    assert "['current_vibe', currentVibe]" in response.text
    assert "renderSelectedAgentStatus(agentHeaderDataFromGlobalStep(message));" in response.text
    assert "policy.current_vibe = currentVibeFromAgent(message.agent || {}, policy);" in response.text


def test_global_client_exposes_admin_play_step_and_scrubber_controls(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert 'id="global-step-button"' in response.text
    assert 'id="global-play-button"' in response.text
    assert 'id="global-frame-scrubber"' in response.text
    assert 'id="global-frame-scrubber-value"' in response.text
    assert "function stepGlobalFrame()" in response.text
    assert "function toggleGlobalPlay()" in response.text
    assert "function scrubGlobalFrame(frame)" in response.text
    assert "adminCommand('step')" in response.text
    assert "adminCommand(lastAdminState.playing ? 'stop' : 'start')" in response.text
    assert "adminCommand('goto', { frame: normalizedFrame })" in response.text
    assert "scrubber.max = String(step)" in response.text
    assert "scrubber.value = String(step)" in response.text


def test_panel_shell_auto_reloads_when_served_client_html_changes(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert response.headers["Cache-Control"] == "no-store"
    assert "function installClientLiveReload()" in response.text
    assert "fetch(window.location.href, { cache: 'no-store'" in response.text
    assert "location.reload();" in response.text
    assert "live_reload') === '0'" in response.text
    assert "new WebSocket('/__client-reload')" not in response.text


def test_llm_log_widget_records_only_conversation_additions_by_tick(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function llmLogDelta(previous, current)" in response.text
    assert "function appendLlmLogSnapshot(tick, log, system = '')" in response.text
    assert "const hasAgentLog = Array.isArray(data.agent_log) && data.agent_log.length > 0;" in response.text
    assert "if (!hasAgentLog) appendLlmLogSnapshot(tick, log, system);" in response.text
    assert "if (entry.delta === true) addLlmTickSection(tick, log, entry.system || '');" in response.text
    assert "else appendLlmLogSnapshot(tick, log, entry.system || '');" in response.text
    assert "llmTickSections.set(tick, { tick, log });" not in response.text
    assert "const existing = llmTickSections.get(tick);" in response.text
    assert "const existingLog = existing?.log || '';" in response.text
    assert "const mergedLog = existingLog ? `${existingLog}\\n${sectionLog}` : sectionLog;" in response.text
    assert "llmTickSections.set(tick, { tick, log: mergedLog });" in response.text


def test_llm_log_widget_does_not_open_empty_filtered_tick_sections(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const visibleLines = llmLogVisibleLines(lines);" in response.text
    assert "if (visibleLines.length === 0) return;" in response.text


def test_llm_log_collapses_situation_and_goals_sections_by_default(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function llmCollapsibleSectionAt(lines, index)" in response.text
    assert "function renderLlmLogSubsection(title, lines)" in response.text
    assert "title = 'Goals'" in response.text
    assert "title = 'Situation'" in response.text
    assert "text === 'Re-evaluate goals:'" in response.text
    assert "function llmLogStartsExplicitSituation(line)" in response.text
    assert "if (llmLogStartsGoals(lines[end]) || llmLogStartsExplicitSituation(lines[end])) break;" in response.text
    assert "text === 'Current goals:' || text === 'Goals:' || text === 'Re-evaluate goals:'" in response.text
    assert "if (title === 'Goals' && (first === 'Current goals:' || first === 'Goals:' || first === 'Re-evaluate goals:'))" in response.text
    assert "if (section.title === 'Situation' && !goalsRendered) html += renderLlmLogSubsection('Goals', []);" not in response.text
    assert '<details class="llm-log-subsection" data-section="${escAttr(title.toLowerCase())}">' in response.text
    assert "html += renderLlmLogLines(lines);" in response.text


def test_llm_log_uses_tick_accordion_without_auto_expanding_latest_tick(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function collapseOtherLlmTickSections(container, activeDetails)" in response.text
    assert "function scrollLlmTickHeaderToTop(container, tickKey)" in response.text
    assert "const activeTickKey = latestLlmTick == null ? null : String(latestLlmTick);" not in response.text
    assert "const open = tickKey === activeTickKey;" not in response.text
    assert "const open = expandedLlmTicks.has(tickKey);" in response.text
    assert '<details class="tick-section llm-log-tick-panel" data-tick="${tickKey}"${open ? \' open\' : \'\'}>' in response.text
    assert "if (details.open) collapseOtherLlmTickSections(el, details);" in response.text
    assert "expandedLlmTicks.add(activeTickKey)" not in response.text
    assert "scrollLlmTickHeaderToTop(el, activeTickKey)" not in response.text
    assert ".llm-log details.tick-section > summary { position: sticky; top: 0; left: 0; right: 0;" in response.text
    assert "z-index: 3; display: block;" in response.text
    assert "background: #1a1a1a; box-shadow: 0 1px 0 #333, 0 8px 12px #1a1a1a;" in response.text
    assert "margin: -3px 0 0 -14px; padding: 4px 8px 4px 14px;" in response.text
    assert ".llm-log details.tick-section[open] > summary { border-bottom: 1px solid #333; }" in response.text
    assert ".llm-log details.tick-section[open] > .tick-body { background: #242424;" in response.text
    assert "box-shadow: inset 2px 0 0 #3a3a3a;" in response.text
    assert "margin: 0 0 0 -14px; padding: 6px 8px 8px 28px;" in response.text
    assert "const wasAtBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;" not in response.text
    assert "if (wasAtBottom) el.scrollTop = el.scrollHeight;" not in response.text


def test_llm_log_collapsed_tick_summary_displays_tool_calls(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function llmLogToolCallText(line)" in response.text
    assert "if (trimmed.startsWith('tool:')) return trimmed.slice(5).trim();" in response.text
    assert "function llmLogToolCalls(lines)" in response.text
    assert "const calls = collectLlmLogToolCalls(lines, false);" in response.text
    assert "return calls.length ? calls : collectLlmLogToolCalls(lines, true);" in response.text
    assert "function renderLlmTickSummary(section, lines)" in response.text
    assert "const toolCalls = llmLogToolCalls(lines);" in response.text
    assert "let html = `<summary><span class=\"tick-summary-head\">Tick ${section.tick}<span class=\"tick-meta\">${lines.length} lines</span></span>`;" in response.text
    assert "html += '<span class=\"tick-tools\" role=\"list\">';" in response.text
    assert "html += `<span class=\"${llmLogTickToolClass(call)}\" role=\"listitem\">${esc(call)}</span>`;" in response.text
    assert "html += renderLlmTickSummary(section, lines);" in response.text
    assert ".llm-log .tick-tools { display: flex; flex-direction: column;" in response.text
    assert ".llm-log .tick-tool { display: block;" in response.text


def test_llm_log_collapsed_tick_summary_shows_all_goals_without_overflow_count(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function llmLogTickToolClass(call)" in response.text
    assert "if (call.startsWith(LLM_LOG_OPEN_GOAL_MARK)) classes.push('new-goal');" in response.text
    assert ".llm-log .tick-tool.new-goal { color: #888;" in response.text
    assert "for (const call of toolCalls) {" in response.text
    assert "toolCalls.slice(0, 4)" not in response.text
    assert "toolCalls.length > 4" not in response.text
    assert "+${toolCalls.length - 4}" not in response.text


def test_llm_log_formats_added_goals_with_plus_marker(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const LLM_LOG_OPEN_GOAL_MARK = '+';" in response.text
    assert "const LLM_LOG_DONE_GOAL_MARK = '✅';" in response.text
    assert "function llmLogFormattedGoalToolCalls(callText)" in response.text
    assert "if (name === 'add_goal')" in response.text
    assert "return goals.map(goal => `${LLM_LOG_OPEN_GOAL_MARK} ${goal}`);" in response.text
    assert "if (name === 'complete_goal')" in response.text
    assert "return [`${LLM_LOG_DONE_GOAL_MARK} ${displayGoal}`];" in response.text
    assert "const formatted = llmLogFormattedToolCalls(call);" in response.text
    assert "for (const displayCall of formatted)" in response.text
    assert "const displayLines = llmLogFormattedToolCallsForLine(line);" in response.text


def test_llm_log_formats_completed_goal_ids_with_goal_text(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const llmLogGoalTextById = new Map();" in response.text
    assert "function rememberLlmLogGoalTasks(data)" in response.text
    assert "llmLogGoalTextById.set(String(task.id), task.text);" in response.text
    assert "rememberLlmLogGoalTasks(data);" in response.text
    assert "const goalId = llmLogGoalTextsFromValue(llmLogToolCallArgValue(callText, ['goal_id', 'id']))[0];" in response.text
    assert "const goal = llmLogGoalTextForId(goalId) || goalId;" in response.text


def test_llm_log_renderer_hides_verbose_assistant_response_text(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function llmLogVerboseAssistantLine(line)" in response.text
    assert "return line.startsWith('  text:') || line.startsWith('  assistant:');" in response.text
    assert "function llmLogVisibleLines(lines)" in response.text
    assert "if (llmLogVerboseAssistantLine(line)) {" in response.text
    assert "skippingAssistantText = true;" in response.text
    assert "if (skippingAssistantText && !llmLogActionBoundaryLine(line)) continue;" in response.text
    assert "const lines = llmLogVisibleLines(section.log ? section.log.split('\\n').filter(Boolean) : []);" in response.text


def test_panel_shell_supports_persisted_draggable_resizable_panels(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    for panel_id in ["game", "agent"]:
        assert f'data-panel-id="{panel_id}"' in response.text
    assert "agent-panel-container" in response.text
    assert "COGONY_CLIENT_STATE_KEY" in response.text
    assert "localStorage.getItem(COGONY_CLIENT_STATE_KEY)" in response.text
    assert "localStorage.setItem(COGONY_CLIENT_STATE_KEY" in response.text
    assert "initPanelWorkspace()" in response.text
    assert "beginPanelDrag" in response.text
    assert "beginSplitResize" in response.text
    assert "splitLeafForDrop" in response.text
    assert "drop-highlight" in response.text


def test_panel_shell_resizes_game_and_snaps_edge_panels_on_window_resize(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "renderPanelLayoutTree" in response.text
    assert "clientState.layout" in response.text
    assert "defaultPanelLayoutTree" in response.text
    assert "layoutMinSize" in response.text
    assert "splitSizes" in response.text
    assert "dataset.splitPath" in response.text


def test_panel_shell_sizes_obs_map_from_widget_width_and_height(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "availableWidth = Math.max(0, container.clientWidth - 16)" in response.text
    assert "availableHeight = Math.max(0, container.clientHeight - 16)" in response.text
    assert "mapSize = Math.max(0, Math.min(availableWidth, availableHeight))" in response.text
    assert "cellSize = Math.max(4, Math.floor((mapSize - (SIDE - 1) * gridGap) / SIDE))" in response.text
    assert "gridSize = cellSize * SIDE + (SIDE - 1) * gridGap" in response.text
    assert "width:${gridSize}px;height:${gridSize}px" in response.text


def test_panel_shell_uses_agent_stream_for_agent_panels(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "selectedAgentId" in response.text
    assert "handleMettascopeMessage" not in response.text
    assert "mettascopeSelectionChanged" not in response.text
    assert "if (!AGENT_CLIENT_MODE && object?.props?.agent_id != null) setSelectedAgentId(object.props.agent_id);" in response.text
    assert 'id="selected-agent-status"' in response.text
    assert "renderSelectedAgentStatus" in response.text
    assert "connectGlobalStream" in response.text
    assert "connectPolicyDebugStream" in response.text
    assert "agentPanelWs" in response.text
    assert "globalWs" in response.text


def test_panel_shell_groups_agent_views_without_agent_dropdown(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert '<div class="panel" id="agent-panel" data-panel-id="agent">' in response.text
    assert '<span class="panel-title">Agent</span>' in response.text
    assert '<select id="panel-agent-id"' not in response.text
    assert 'class="agent-selector"' not in response.text
    assert 'id="add-policy-widget"' in response.text
    assert '<div class="status-bar" id="status-bar">' in response.text
    assert '<span class="label">agent</span>' not in response.text
    assert '<input id="panel-agent-id" type="number"' not in response.text
    assert 'class="agent-subpanel-title">' not in response.text
    assert 'id="llm-log"' not in response.text
    assert 'id="policy-info"' not in response.text
    assert 'id="obs-entities"' not in response.text
    assert "policy-widget-container" in response.text
    assert "BUILTIN_POLICY_WIDGETS" in response.text
    assert "id: 'llm_log'" in response.text
    assert "id: 'policy_info'" in response.text
    assert "id: 'entities'" in response.text
    assert "id: 'obs_map'" not in response.text
    assert "{ id: 'toolsy_autopilocy', module: 'toolsy_autopilocy', title: 'AutoPilocy()', config: {} }" in response.text
    assert "{ id: 'toolsy_goals', module: 'toolsy_goals', title: 'Goals', config: {} }" in response.text
    assert "{ id: 'toolsy_diary', module: 'toolsy_diary', title: 'Diary', config: {} }" in response.text
    assert "{ id: 'toolsy_world_model', module: 'toolsy_world_model', title: 'World Model'" in response.text
    assert "{ id: 'agent_status', module: 'agent_status', title: 'Agent', config: {} }" in response.text
    assert 'id="add-policy-widget"' in response.text
    assert 'id="policy-widget-menu"' in response.text
    assert "policy-widget-close" in response.text
    assert "closePolicyWidget" in response.text
    assert "policyWidgetModules" in response.text
    assert "clientState.policyWidgets" in response.text
    assert "clientState.policyWidgetLayout" in response.text
    assert "clientState.policyWidgetCatalog" in response.text
    assert "clientState.agentPolicyWidgets" not in response.text
    assert "clientState.agentPolicyWidgetLayouts" not in response.text
    assert "registerPolicyWidgetModule('llm_log'" in response.text
    assert "registerPolicyWidgetModule('policy_info'" in response.text
    assert "registerPolicyWidgetModule('obs_map'" not in response.text
    assert "registerPolicyWidgetModule('entities'" in response.text
    assert "registerPolicyWidgetModule('toolsy_autopilocy'" in response.text
    assert "registerPolicyWidgetModule('toolsy_goals'" in response.text
    assert "registerPolicyWidgetModule('toolsy_diary'" in response.text
    assert "registerPolicyWidgetModule('toolsy_world_model'" in response.text
    assert "renderToolsyWorldModel" in response.text
    assert "collectWorldObjects(data, context)" in response.text
    assert "renderWorldObjectMap(objects, mapHost, model.seen_bounds || {}, context, observedCoords)" in response.text
    assert "renderWorldObjectDetails(objects, detailHost, context)" in response.text
    assert "currently seen" in response.text
    assert "world-object-token" in response.text
    assert "collectWorldObjects(data).slice" not in response.text
    assert 'data-world-model-mode=' not in response.text
    assert "world-model-mode-button" not in response.text
    assert "renderToolsyGoals" in response.text
    assert "renderToolsyAutoPilocy" in response.text
    assert "data.auto_pilocy || data.auto_pilocy_status" in response.text
    assert "toolsy-autopilocy-state" in response.text
    assert "current_goals" in response.text
    assert "goal_tasks" in response.text
    assert "type: 'add_goal'" in response.text
    assert "toolsy-diary-entry" in response.text
    assert "Array.from(data.diary).reverse()" in response.text
    assert "slice(-maxEntries)" not in response.text
    assert ".obs-entities .entity { border: 1px solid" in response.text
    assert "global-token-card" in response.text
    assert "function entityTagChip(tag)" in response.text
    assert "...e.tags.map(entityTagChip)" in response.text
    assert "...e.tags.map(tag => `tag:${tag}`)" not in response.text
    assert "data.obs_global || data.__obs_global__ || {}" in response.text
    assert "Object.entries(feats).filter(([_k, v]) => v !== 0)" not in response.text
    assert "Object.entries(globalTokens).filter(([_key, value]) => value !== 0)" not in response.text
    assert "renderPolicyWidgets(data)" in response.text
    assert "renderPolicyWidgetLayoutTree" in response.text
    assert "beginPolicyWidgetDrag" in response.text
    assert "completePolicyWidgetDrop" in response.text
    assert "policyWidgetsFromMessage(message, policy)" not in response.text
    assert "status.textContent = item.id === item.module ? '' : item.module;" in response.text
    assert "policy-widget-drop-highlight" in response.text
    assert "togglePolicyWidgetMenu" in response.text
    assert "addPolicyWidget" in response.text
    assert "createPolicyWidgetContext" in response.text
    assert "websocket: agentPanelWs" in response.text
    assert "sendPolicyWidgetRequest" in response.text
    assert "const agentOptions = new Map()" in response.text
    assert "updateAgentOptionFromObject" in response.text
    assert "syncAgentDropdownOptions" not in response.text
    assert "agentLabel" in response.text
    assert "`${name} #${agentId}`" in response.text
    assert "const stateKey = widget.id;" in response.text


def test_toolsy_goals_widget_renders_task_list_with_completed_items(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function normalizeToolsyGoalTasks(data)" in response.text
    assert "function activeToolsyGoalsText(tasks)" in response.text
    assert "function toggleToolsyGoalCompleted(context, taskId, completed)" in response.text
    assert "function sendToolsyGoalsUpdate(context, tasks)" in response.text
    assert "String(data?.current_goals || '').split('\\n')" in response.text
    assert "map(task => task.text).join('\\n')" in response.text
    assert "textarea.value.split('\\n')" not in response.text
    assert 'aria-label="Active goals, one per line"' not in response.text
    assert "Update goals" not in response.text
    assert '<div class="toolsy-goal-list">' in response.text
    assert 'class="toolsy-goal-task${task.completed ? \' completed\' : \'\'}"' in response.text
    assert 'type="checkbox" class="toolsy-goal-checkbox"' in response.text
    assert "checkbox.checked = task.completed;" in response.text
    assert "toggleToolsyGoalCompleted(context, task.id, checkbox.checked)" in response.text
    assert "type: 'add_goal'" in response.text
    assert "goal_tasks: tasks" in response.text
    assert "function activeToolsyGoalTexts(tasks)" in response.text
    assert "goals: activeToolsyGoalTexts(tasks)" in response.text
    assert "prompt: activeToolsyGoalsText(tasks)" not in response.text
    assert "lastData.goal_tasks = tasks" in response.text
    assert "lastData.current_goals = activeToolsyGoalsText(tasks)" in response.text
    assert ".toolsy-goal-task.completed" in response.text
    assert ".toolsy-goals textarea" not in response.text


def test_toolsy_autopilocy_widget_renders_current_status(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function normalizeToolsyAutoPilocyStatus(data)" in response.text
    assert "function renderToolsyAutoPilocy(data, el)" in response.text
    assert "auto.status" in response.text
    assert "auto.remaining" in response.text
    assert "auto.timeout" in response.text
    assert "last_tool_result" in response.text


def test_panel_shell_merges_obs_map_into_world_model_widget(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const POLICY_WIDGET_MERGES = { obs_map: 'toolsy_world_model' };" in response.text
    assert "migrateMergedPolicyWidgets();" in response.text
    assert "clientState.policyWidgets = uniqueMergedPolicyWidgetIds(clientState.policyWidgets);" in response.text
    assert "migratePolicyWidgetLayoutNode(clientState.policyWidgetLayout);" in response.text
    assert "has('llm_log') && has('policy_info') && has('toolsy_world_model') && has('entities')" in response.text
    assert "second: leaf('toolsy_world_model')" in response.text
    assert "second: leaf('obs_map')" not in response.text


def test_world_model_widget_renders_one_clickable_object_map(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function collectWorldObjects(data, context = {})" in response.text
    assert "function mergeWorldObject(target, source)" in response.text
    assert "seenNow: true" in response.text
    assert '<button type="button" class="world-object-cell object sprite${observed}${seen}${selected}"' in response.text
    assert "data-object-key=\"${escAttr(object.key)}\"" in response.text
    assert "container.onclick = event =>" in response.text
    assert "cell.classList.add('selected');" in response.text
    assert "selectWorldObjectCell(cell.getAttribute('data-object-key'), context);" in response.text
    assert "cell.onclick = event =>" in response.text
    assert "cell.onkeydown = event =>" in response.text
    assert "cell.onpointerdown = event => selectObject(event);" not in response.text
    assert "cell.onmousedown = event => selectObject(event);" not in response.text
    assert "cell.onfocus = event => selectObject(event);" not in response.text
    assert "event.stopPropagation();" in response.text
    assert "function selectWorldObjectCell(key, context = null)" in response.text
    assert "renderPolicyWidgets(lastData || {});" in response.text
    assert "onclick=\"selectCell('${escAttr(object.key)}')\"" not in response.text
    assert "selectedWorldObject(objects)" in response.text
    assert "Click an object on the map." in response.text
    assert "world-object-props" in response.text
    assert "world-object-tokens" in response.text
    assert "world-object-seen-now" in response.text
    assert "x: col ?? dc" in response.text
    assert "y: row ?? dr" in response.text
    assert "rememberWorldObjects(context, currentObjects)" in response.text
    assert "mergeWorldObjectLists(collectRememberedWorldObjects(context), currentObjects)" in response.text
    assert "bounds.min_col" in response.text
    assert "bounds.max_row" in response.text


def test_world_model_widget_info_panel_selects_any_object_and_can_resize(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert '<button type="button" class="world-object-cell object wall${observed}${selected}"' in response.text
    assert "function renderWorldObjectDetails(objects, el, context = {})" in response.text
    assert "function toggleWorldObjectInfoCollapsed(context)" in response.text
    assert "function beginWorldObjectInfoResize(event, context)" in response.text
    assert "world-object-info-panel" in response.text
    assert "world-object-info-toggle" in response.text
    assert "world-object-info-resize-handle" in response.text
    assert "context.state.worldObjectInfoCollapsed = false;" in response.text
    assert "el.classList.toggle('collapsed', collapsed);" in response.text
    assert "function worldObjectInfoToggleIcon(collapsed)" in response.text
    assert "worldObjectInfoToggleIcon(collapsed)" in response.text
    assert "const toggleText = collapsed ? '[^]' : '[v]';" not in response.text
    assert "world-object-info-toggle-icon" in response.text
    assert "Collapse info panel to bottom" in response.text
    assert "context.state.worldObjectInfoHeight" in response.text
    assert "selectWorldObjectCell(cell.getAttribute('data-object-key'), context);" in response.text
    assert "renderWorldObjectDetails(objects, detailHost, context);" in response.text
    assert "world-object-info-close" not in response.text


def test_world_model_widget_uses_light_walls_and_object_sprites(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "wall: '#d8d8d8'" in response.text
    assert ".world-object-cell.wall { background: #d8d8d8;" in response.text
    assert ".world-object-cell.wall.observed-now { background: #eeeeee;" in response.text
    assert ".world-object-cell.object.sprite" in response.text
    assert "function worldObjectSpriteName(object)" in response.text
    assert "function worldObjectSpriteUrl(object)" in response.text
    assert "`/mettascope-assets/objects/${encodeURIComponent(spriteName)}.png`" in response.text
    assert 'class="world-object-cell object sprite${observed}${seen}${selected}"' in response.text
    assert 'style="${escAttr(worldObjectCellStyle(object))}"' in response.text


def test_world_model_widget_displays_known_walls_from_policy_model(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function collectKnownWallObjects(model, modelCenter)" in response.text
    assert "const walls = Array.isArray(model.walls) ? model.walls : [];" in response.text
    assert "for (const wall of collectKnownWallObjects(model, modelCenter))" in response.text
    assert "type: 'wall'" in response.text
    assert ".world-object-cell.wall" in response.text
    assert 'class="world-object-cell object wall${observed}${selected}"' in response.text
    assert "if (existing?.type === 'wall' && object.type !== 'wall')" in response.text
    assert "policy.wall_objects = message.wall_objects || [];" not in response.text


def test_web_renderer_serves_mettascope_assets(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    resources = {resource.canonical for resource in renderer._app.router.resources()}

    assert "/mettascope-assets" in resources


def test_world_model_widget_does_not_mix_static_wall_stream_into_policy_model(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    wall_objects = [{"id": 7, "type_name": "wall", "location": [3, 4]}]
    renderer._walls_msg = json.dumps({"type": "walls", "objects": wall_objects})
    renderer._latest_agent_state_msgs[0] = json.dumps(
        build_agent_state_replay(
            {
                "step": 1,
                "objects": [
                    {
                        "type_name": "agent",
                        "agent_id": 0,
                        "policy_infos": {"world_model": {"walls": [{"row": 1, "col": 2}]}},
                    }
                ],
                "episode_stats": {},
            },
            agent_id=0,
        )
    )

    state = renderer.agent_state(0)

    assert "wall_objects" not in state
    assert state["policy_infos"]["world_model"]["walls"] == [{"row": 1, "col": 2}]


def test_global_wall_stream_still_updates_global_client_state(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "if (message.type === 'walls')" in response.text
    assert "wall_objects: message.objects || []" in response.text
    assert "data.wall_objects || []" in response.text


def test_global_stream_sends_static_walls_to_world_model_clients() -> None:
    source = Path(web_server.__file__).read_text()
    handle_global = source[source.index("async def _handle_global_ws") : source.index("async def _handle_ws")]

    assert "self._broadcast(self._walls_msg)" in source
    assert "walls = self._walls_msg" in handle_global
    assert "if walls:" in handle_global
    assert "await self._send_ws_message(ws, walls)" in handle_global


def test_agent_state_does_not_include_static_wall_objects_for_world_model(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    wall_objects = [{"id": 7, "type_name": "wall", "location": [3, 4]}]
    renderer._walls_msg = json.dumps({"type": "walls", "objects": wall_objects})
    renderer._latest_agent_state_msgs[0] = json.dumps(
        build_agent_state_replay(
            {
                "step": 1,
                "objects": [{"type_name": "agent", "agent_id": 0, "policy_infos": {}}],
                "episode_stats": {},
            },
            agent_id=0,
        )
    )

    state = renderer.agent_state(0)

    assert "wall_objects" not in state


def test_world_model_map_supports_drag_pan_bounded_zoom_and_obs_mask(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const WORLD_OBJECT_MAX_CELL_PX = 76;" in response.text
    assert "function worldObjectZoomBounds(container, cols, rows)" in response.text
    assert "minZoom: 1" in response.text
    assert "maxZoom: Math.max(1, WORLD_OBJECT_MAX_CELL_PX / Math.max(1, baseCellSize))" in response.text
    assert "function updateWorldObjectPanDataset(container)" in response.text
    assert "function worldObjectZoomAnchor(container, event)" in response.text
    assert "const mapRect = map.getBoundingClientRect();" in response.text
    assert "mapX: event.clientX - mapRect.left" in response.text
    assert "function restoreWorldObjectZoomAnchor(container, anchor)" in response.text
    assert "const ratioX = newMapWidth / Math.max(1, anchor.mapWidth);" in response.text
    assert "container.scrollLeft = Math.max(0, mapLeft + anchor.mapX * ratioX - anchor.cursorX);" in response.text
    assert "function beginWorldObjectMapPan(event)" in response.text
    assert "container.addEventListener('pointerdown', beginWorldObjectMapPan);" in response.text
    assert "container.classList.add('is-panning');" in response.text
    assert "container.scrollLeft = startScrollLeft - dx;" in response.text
    assert "container.scrollTop = startScrollTop - dy;" in response.text
    assert "container.dataset.worldObjectSuppressClick = 'true';" in response.text
    assert "function consumeWorldObjectSuppressedClick(container, event)" in response.text
    assert "if (container.dataset.worldObjectSuppressClick !== 'true') return false;" in response.text
    assert "function isObservedRelativeCoord(dr, dc)" in response.text
    assert "Math.sqrt(dr * dr + dc * dc) <= VISION_R + 0.5" in response.text
    assert "function observedWorldCoords(data, currentObjects)" in response.text
    assert "const observedCoords = observedWorldCoords(data, currentObjects);" in response.text
    assert "for (let dr = -VISION_R; dr <= VISION_R; dr++)" in response.text
    assert "for (let dc = -VISION_R; dc <= VISION_R; dc++)" in response.text
    assert "if (!isObservedRelativeCoord(dr, dc)) continue;" in response.text
    assert "const observedPoints = Array.from(observedCoords).map(coord =>" in response.text
    assert "const xs = [...placed.map(object => object.x), ...observedPoints.map(coord => coord.x)];" in response.text
    assert "const observed = observedCoords.has(`${x},${y}`) ? ' observed-now' : '';" in response.text
    assert 'html += `<div class="world-object-cell${observed}${unexplored}"></div>`;' in response.text
    assert ".world-object-cell.observed-now" in response.text
    assert ".world-object-map-host.is-panning" in response.text


def test_world_model_map_double_click_centers_and_zooms_object(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert ".world-object-map-host { flex: 1; min-height: 112px; display: flex; align-items: flex-start; justify-content: flex-start;" in response.text
    assert "function centerWorldObjectMapOnObject(container, object, minX, minY, cellSize, context)" in response.text
    assert "function worldObjectCellForEvent(container, event)" in response.text
    assert "function applyWorldObjectSelection(key, object = null, context = null)" in response.text
    assert "const targetZoom = 36 / Math.max(1, zoomBounds.baseCellSize);" in response.text
    assert "const focusPadX = focusObject ? Math.ceil(container.clientWidth / Math.max(1, 2 * (cellSize + 1))) : 0;" in response.text
    assert "const renderMinX = minX - focusPadX;" in response.text
    assert "context.state.worldObjectFocusKey = object.key;" in response.text
    assert "container.ondblclick = event =>" in response.text
    assert "event.stopPropagation();" in response.text
    assert "renderWorldObjectMap(objects, container, bounds, context, observedCoords);" in response.text
    assert "centerWorldObjectMapOnObject(container, focusObject, renderMinX, renderMinY, cellSize, context);" in response.text
    assert "delete context.state.worldObjectFocusKey;" in response.text


def test_world_model_map_renders_unexplored_empty_terrain_grey(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert ".world-object-cell.unexplored { background: #383838;" in response.text
    assert "const unexplored = observed ? '' : ' unexplored';" in response.text
    assert 'html += `<div class="world-object-cell${observed}${unexplored}"></div>`;' in response.text


def test_world_model_widget_does_not_render_summary_count_cards(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "world-model-summary" not in response.text
    assert "world-model-stat" not in response.text
    assert '<span class="key">seen</span>' not in response.text
    assert '<span class="key">objects</span>' not in response.text
    assert '<span class="key">walls</span>' not in response.text
    assert "model.wall_count" not in response.text
    assert "'<div class=\"world-object-map-host\"></div>'" in response.text


def test_panel_shell_keeps_add_widget_menu_clickable_when_all_widgets_are_active(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "All widgets added" in response.text
    assert "addButton.disabled = false;" in response.text
    assert "addButton.disabled = addable.length === 0" not in response.text


def test_panel_shell_does_not_clip_header_add_menus(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert 'id="add-policy-widget"' in response.text
    assert 'id="policy-widget-menu"' in response.text
    assert 'id="add-global-panel"' in response.text
    assert 'id="global-panel-menu"' in response.text
    assert "overflow: visible;" in response.text


def test_panel_shell_uses_client_widget_catalog_for_add_menu(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const POLICY_WIDGET_LAYOUT_VERSION = 5;" in response.text
    assert "normalizePolicyWidgets(data.policy_widgets || data.__policy_widgets__)" not in response.text
    assert "policy_widgets: normalize" not in response.text
    assert "const policyProvided = widgets.map(widget => widget.id).filter(widgetId => !builtins.includes(widgetId));" not in response.text
    assert "return builtins;" in response.text
    assert "return [];" in response.text


def test_mettascope_vibe_controls_support_ctrl_click_bindings() -> None:
    mettascope_dir = Path(__file__).parents[1] / ".mettagrid" / "nim" / "mettascope" / "src" / "mettascope"
    gameplayer = (mettascope_dir / "gamemode" / "gameplayer.nim").read_text()
    vibespanel = (mettascope_dir / "panelmode" / "vibespanel.nim").read_text()
    app = (mettascope_dir.parent / "mettascope.nim").read_text()

    assert "panelmode/vibespanel" in gameplayer
    assert "openVibeBindingPopup(vibeName, sk.mousePos)" in gameplayer
    assert "vibeBindingModifierDown()" in gameplayer
    assert "beginVibeBindingClick(vibeName, sk.mousePos)" in gameplayer
    assert "bindingPopupClickVibe == vibeName" in gameplayer
    assert "window.buttonReleased[MouseRight]" in gameplayer
    assert "drawBindingsPopup()" in gameplayer
    assert "window.buttonDown[KeyLeftControl]" in vibespanel
    assert "window.buttonPressed[MouseLeft] and vibeBindingModifierDown()" in vibespanel
    assert "bindingPopupClickVibe == vibeName" in vibespanel
    assert "bindingPopupClickVibe.len == 0" in vibespanel
    assert "window.buttonReleased[MouseRight]" in vibespanel
    assert "## Game mode UI.\n    handleVibeHotkeys()\n    drawGameWorld()" in app


def test_panel_shell_keeps_agent_layout_independent_from_selected_agent(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function policyWidgetKey()" not in response.text
    assert "getStoredLayout: () => AGENT_CLIENT_MODE ? clientState.policyClientWidgetLayout" in response.text
    assert "else clientState.policyWidgetLayout = layout;" in response.text
    assert "clientState.policyWidgets = uniqueMergedPolicyWidgetIds(ids);" in response.text
    assert "clientState.policyClientWidgets = uniqueMergedPolicyWidgetIds(ids);" in response.text
    assert "rememberPolicyWidgetDefinitions(availableWidgets);" in response.text
    assert "widget.unavailable" in response.text
    assert "Widget not available for this agent." in response.text
    assert "tab.textContent = tabItem ? tabItem.title : itemId;" in response.text


def test_panel_shell_uses_global_panel_workspace_for_webgpu_viewer(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert 'id="global-panel-container"' in response.text
    assert "global-panel-container global-panels" in response.text
    assert 'id="add-global-panel"' in response.text
    assert 'id="global-panel-menu"' in response.text
    assert "BUILTIN_GLOBAL_PANELS" in response.text
    assert "globalPanelsFromData" in response.text
    assert "id: 'mettascope'" not in response.text
    assert "id: 'global_viewer'" in response.text
    assert "globalPanelModules" in response.text
    assert "clientState.globalPanels" in response.text
    assert "clientState.globalPanelLayouts" in response.text
    assert "registerGlobalPanelModule('mettascope'" not in response.text
    assert "registerGlobalPanelModule('global_viewer'" in response.text
    assert "global-panel-close" in response.text
    assert "closeGlobalPanel" in response.text
    assert "nonClosableIds: new Set(['global_viewer'])" in response.text
    assert "function itemHasCloseControl(itemId)" in response.text
    assert "if (itemHasCloseControl(item.id)) header.appendChild(close);" in response.text
    assert "renderGlobalPanelLayoutTree" in response.text
    assert "beginGlobalPanelDrag" in response.text
    assert "completeGlobalPanelDrop" in response.text
    assert "global-panel-drop-highlight" in response.text
    assert "toggleGlobalPanelMenu" in response.text
    assert "addGlobalPanel" in response.text
    assert "createGlobalPanelContext" in response.text
    assert "websocket: globalWs" in response.text
    assert "renderGlobalPanels(lastGlobalData || {})" in response.text
    assert "loadMettascope(container)" not in response.text
    assert "function collectGlobalViewerObjects(data = {})" in response.text
    assert "function renderGlobalWebGpuViewer(data, el, context = {})" in response.text
    assert "renderGlobalHtmlViewer" not in response.text
    assert "renderGlobalWebGpuMap(objects, mapHost, context)" in response.text
    assert "renderWorldObjectMap(objects, mapHost, {}, context, new Set())" not in response.text


def test_global_viewer_uses_webgpu_and_sprite_textures(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function renderGlobalWebGpuMap(objects, host, context = {})" in response.text
    assert "global-webgpu-viewer-canvas" in response.text
    assert "navigator.gpu.requestAdapter()" in response.text
    assert "canvas.getContext('webgpu')" in response.text
    assert "device.createRenderPipeline" in response.text
    assert "textureSample(spriteTexture, spriteSampler, input.uv)" in response.text
    assert "createImageBitmap" in response.text
    assert "device.queue.copyExternalImageToTexture" in response.text
    assert "worldObjectSpriteUrl(object)" in response.text
    assert "renderer.device.queue.onSubmittedWorkDone().then(() => {" in response.text
    assert "vertexBuffer.destroy();" in response.text


def test_global_webgpu_shader_samples_textures_from_uniform_control_flow(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "let texel = textureSample(spriteTexture, spriteSampler, input.uv);" in response.text
    assert "if (input.useTexture > 0.5) {\n    let texel = textureSample" not in response.text
    assert "input.color * (1.0 - input.useTexture) + texel * input.useTexture" in response.text


def test_global_webgpu_viewer_clicks_objects_into_properties_panel(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function selectGlobalWebGpuObject(object, renderer)" in response.text
    assert "selectedCell = object.key;" in response.text
    assert "context.state.worldObjectInfoCollapsed = false;" in response.text
    assert "renderWorldObjectDetails(renderer.objects, detailHost, context);" in response.text
    assert "requestGlobalWebGpuDraw(renderer);" in response.text
    assert "selectGlobalWebGpuObject(object, renderer);" in response.text


def test_global_webgpu_agent_click_selects_agent_and_recenters_view(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function globalWebGpuObjectIsAgent(object)" in response.text
    assert "function centerGlobalWebGpuViewOnObject(renderer, object)" in response.text
    assert "state.globalWebGpuZoom = Math.max(view.zoom, Math.min(view.zoomBounds.maxZoom" in response.text
    assert "state.globalWebGpuPanX = Math.round(view.width / 2 - objectCenterX);" in response.text
    assert "state.globalWebGpuPanY = Math.round(view.height / 2 - objectCenterY);" in response.text
    assert "if (globalWebGpuObjectIsAgent(object)) centerGlobalWebGpuViewOnObject(renderer, object);" in response.text
    assert "setSelectedAgentId(object.props.agent_id)" in response.text


def test_global_agents_panel_click_selects_agent_and_recenters_viewer(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function globalWebGpuRendererForGlobalViewer()" in response.text
    assert "function globalViewerObjectForAgentId(agentId, renderer = null)" in response.text
    assert "function selectGlobalAgentFromPanel(agentId)" in response.text
    assert "const renderer = globalWebGpuRendererForGlobalViewer();" in response.text
    assert "const object = globalViewerObjectForAgentId(normalized, renderer);" in response.text
    assert "if (object && renderer) selectGlobalWebGpuObject(object, renderer);" in response.text
    assert "else setSelectedAgentId(normalized);" in response.text
    assert "renderGlobalPanels(lastGlobalData || {});" in response.text
    assert 'data-agent-id="${agentId}"' in response.text
    assert 'onclick="selectGlobalAgentFromPanel(${agentId})"' in response.text
    assert 'onkeydown="handleGlobalAgentRowKeydown(event, ${agentId})"' in response.text
    assert "${agentId === selectedAgentId ? ' selected' : ''}" in response.text
    assert ".global-agent-row.selected { background: #203040;" in response.text


def test_global_viewer_uses_agents_global_panel_instead_of_agent_widget_panel(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const PANEL_IDS = AGENT_CLIENT_MODE ? ['agent'] : ['game'];" in response.text
    assert (
        "if (PLAYER_CLIENT_MODE) connectPlayerStream(); else if (POLICY_DEBUGGER_MODE) "
        "connectPolicyDebugStream(); else connectGlobalStream();"
    ) in response.text
    assert "connectAgentPanelStream" not in response.text
    assert "connectPolicyStream" not in response.text
    assert "{ id: 'agents', module: 'agents', title: 'Agents', config: {} }" in response.text
    assert "registerGlobalPanelModule('agents'" in response.text
    assert "function renderGlobalAgentsPanel(data, el)" in response.text
    assert "agentInventoryValue(agent, 'creds')" in response.text
    assert "agentInventoryValue(agent, 'heart')" in response.text
    assert "selfFeats[`inv:${resource}`]" in response.text
    assert "agentConnectionStatus(data, agentId)" in response.text
    assert "body:not(.policy-client-mode) #agent-panel { display: none !important; }" in response.text
    assert "wsEl.textContent = `global ${globalWsState}`;" in response.text


def test_global_agents_panel_can_open_agent_clients(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "function agentClientUrl(agentId)" in response.text
    assert "url.pathname = '/policy-debugger';" in response.text
    assert "url.searchParams.set('agent', String(normalizeAgentId(agentId)));" in response.text
    assert 'class="global-agent-open"' in response.text
    assert 'href="${escAttr(agentClientUrl(agentId))}"' in response.text
    assert 'target="_blank" rel="noopener noreferrer"' in response.text
    assert "function openAgentClient(event, agentId)" in response.text
    assert "const opened = window.open(url, '_blank');" in response.text
    assert "if (opened) opened.opener = null;" in response.text
    assert "else window.location.href = url;" in response.text
    assert 'onpointerdown="event.stopPropagation()"' in response.text
    assert 'onclick="openAgentClient(event, ${agentId})"' in response.text
    assert "function externalLinkIcon()" in response.text
    assert 'class="global-agent-open-icon"' in response.text
    assert "[->]" not in response.text

    name_markup = '<span class="global-agent-name">${esc(name)}</span>'
    status_markup = '<span class="global-agent-status ${status.connected ? \'connected\' : \'disconnected\'}"'
    resources_markup = '<span class="global-agent-resources">'
    open_markup = '<a class="global-agent-open"'
    assert response.text.index(name_markup) < response.text.index(resources_markup)
    assert response.text.index(resources_markup) < response.text.index(status_markup)
    assert response.text.index(status_markup) < response.text.index(open_markup)


def test_global_agents_panel_uses_status_dots_instead_of_status_text(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert ".global-agent-status { justify-self: end; width: 9px; height: 9px;" in response.text
    assert ".global-agent-status.connected { background: #62c462;" in response.text
    assert ".global-agent-status.disconnected { background: #c46262;" in response.text
    assert 'title="${escAttr(status.label)}" aria-label="${escAttr(status.label)}" role="img"></span>' in response.text
    assert ">${esc(status.label)}</span>" not in response.text


def test_global_agents_panel_collapses_to_right_instead_of_closing(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const COLLAPSED_RIGHT_RAIL_WIDTH = 36;" in response.text
    assert "clientState.globalPanelCollapsedRight" in response.text
    assert "collapsibleRightIds: new Set(['agents'])" in response.text
    assert "function collapseItemRight(itemId, event = null)" in response.text
    assert "function expandItemRight(itemId, event = null)" in response.text
    assert "function renderCollapsedRightRail(container, items, activeIds, collapsed)" in response.text
    assert "close.title = itemCollapsesRight(item.id) ? `Collapse ${item.title} to right` : `Close ${item.title}`;" in response.text
    assert "close.setAttribute('aria-label', close.title);" in response.text
    assert "function workspaceControlIcon(name)" in response.text
    assert "close.innerHTML = workspaceControlIcon(itemCollapsesRight(item.id) ? 'collapseRight' : 'close');" in response.text
    assert "button.innerHTML = workspaceControlIcon('expandLeft')" in response.text
    assert "close.textContent = itemCollapsesRight(item.id) ? '[>]' : '[x]';" not in response.text
    assert "`[<] ${item.title}`" not in response.text
    assert "itemCollapsesRight(item.id) ? collapseItemRight(item.id, event) : closeItem(item.id, event)" in response.text
    assert "Expand ${item.title}" in response.text
    assert "global-panel-collapsed-rail" in response.text
    assert "global-panel-collapsed-tab" in response.text


def test_heartbeat_reports_per_agent_connection_counts(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._initial_replay["num_agents"] = 3
    renderer._agent_clients[1] = [_FakeWs()]  # type: ignore[list-item]
    renderer._policy_clients[2] = [_FakeWs(), _FakeWs()]  # type: ignore[list-item]
    renderer._policy_debug_clients[2] = [_FakeWs()]  # type: ignore[list-item]

    message = json.loads(renderer.heartbeat_message())

    assert message["agent_connections"] == [
        {"agent_id": 0, "agent": 0, "policy": 0, "policy_debug": 0, "connected": False},
        {"agent_id": 1, "agent": 1, "policy": 0, "policy_debug": 0, "connected": True},
        {"agent_id": 2, "agent": 0, "policy": 2, "policy_debug": 1, "connected": True},
    ]


def test_mettascope_posts_selected_agent_changes() -> None:
    object_panel = Path(".mettagrid/nim/mettascope/src/mettascope/panelmode/objectpanel.nim").read_text()

    assert "postSelectedAgent" in object_panel
    assert "mettascopeSelectionChanged" in object_panel
    assert "window.parent.postMessage" in object_panel


def test_web_renderer_exposes_coworld_style_http_routes(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    routes = {(route.method, route.resource.canonical) for route in renderer._app.router.routes()}

    assert ("GET", "/favicon.ico") in routes
    assert ("GET", "/healthz") in routes
    assert ("GET", "/admin") in routes
    assert ("GET", "/status") in routes
    assert ("POST", "/admin") in routes
    assert ("GET", "/global") in routes
    assert ("GET", "/global-client") in routes
    assert ("GET", "/agent/{agent_id}") in routes
    assert ("GET", "/policy/{agent_id}") in routes
    assert ("GET", "/policy-debug/{agent_id}") in routes
    assert ("GET", "/player") in routes
    assert ("GET", "/policy-debugger") in routes
    assert ("GET", "/policy-client") not in routes
    assert ("GET", "/ws") in routes
    assert ("GET", "/wasm/mettascope.html") in routes


def test_web_renderer_serves_runner_status_json(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)
    renderer.set_status_provider(
        lambda: {
            "components": [{"name": "game", "state": "running", "detail": "step 3 / 10"}],
            "endpoints": {"global": "ws://127.0.0.1:8899/global"},
        }
    )

    response = asyncio.run(
        renderer._serve_status(SimpleNamespace(query={"format": "json"}, headers={}))  # type: ignore[arg-type]
    )

    payload = json.loads(response.text)
    assert payload["components"][0] == {"name": "game", "state": "running", "detail": "step 3 / 10"}
    assert payload["endpoints"]["global"] == "ws://127.0.0.1:8899/global"


def test_panel_shell_uses_policy_client_agent_query_as_initial_agent(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const initialParams = new URLSearchParams(window.location.search);" in response.text
    assert "const queryAgentId = initialParams.has('agent')" in response.text
    assert ": (initialParams.has('slot') ? Number(initialParams.get('slot')) : null);" in response.text
    assert "let selectedAgentId = Math.max(0, Number(queryAgentId ??" in response.text


def test_policy_debugger_is_web_only_agent_widget_workspace(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const POLICY_DEBUGGER_MODE = window.location.pathname === '/policy-debugger';" in response.text
    assert "const POLICY_CLIENT_MODE = window.location.pathname === '/policy-client';" not in response.text
    assert "const PLAYER_CLIENT_MODE = window.location.pathname === '/player';" in response.text
    assert "const AGENT_CLIENT_MODE = POLICY_DEBUGGER_MODE || PLAYER_CLIENT_MODE;" in response.text
    assert "document.body.classList.toggle('policy-client-mode', AGENT_CLIENT_MODE);" in response.text
    assert "PLAYER_CLIENT_MODE ? 'Cogony Player Client' : 'Cogony Policy Debugger'" in response.text
    assert "body.policy-client-mode #game-panel { display: none !important; }" in response.text
    assert "body.policy-client-mode #agent-panel { inset: 0 !important;" in response.text
    assert "clientState.policyClientWidgets = null;" in response.text
    assert "clientState.policyClientWidgetLayout = null;" in response.text
    assert "function defaultPolicyClientWidgetIds(widgets)" in response.text
    assert (
        "const preferred = ['agent_status', 'toolsy_world_model', 'entities', 'llm_log', "
        "'toolsy_goals', 'toolsy_autopilocy', 'toolsy_diary'];"
    ) in response.text
    assert (
        "const preferred = ['toolsy_world_model', 'agent_status', 'toolsy_autopilocy', 'llm_log', "
        "'policy_info', 'entities', 'toolsy_goals', 'toolsy_diary'];"
    ) not in response.text
    assert "function defaultPolicyClientWidgetLayout(widgetIds)" in response.text
    assert "const leftColumn = split('horizontal', 0.12, leafOrNull('agent_status')," in response.text
    assert "split('horizontal', 0.62, leafOrNull('toolsy_world_model'), leafOrNull('entities')));" in response.text
    assert "const middleColumn = leafOrNull('llm_log');" in response.text
    assert "const rightColumn = split('horizontal', 0.43, leafOrNull('toolsy_goals')," in response.text
    assert "split('horizontal', 0.39, leafOrNull('toolsy_autopilocy'), leafOrNull('toolsy_diary')));" in response.text
    assert "const mainLayout = split('vertical', 0.36, leftColumn, split('vertical', 0.5, middleColumn, rightColumn));" in response.text
    assert (
        "const known = new Set(['agent_status', 'toolsy_world_model', 'entities', 'llm_log', "
        "'toolsy_goals', 'toolsy_autopilocy', 'toolsy_diary']);"
    ) in response.text
    assert "const tabLeaf = ids => ({ type: 'leaf', widgets: ids, selected: ids[0] || null });" not in response.text
    assert "defaultLayout: AGENT_CLIENT_MODE ? defaultPolicyClientWidgetLayout : defaultPolicyWidgetLayout" in response.text
    assert "getStoredLayout: () => AGENT_CLIENT_MODE ? clientState.policyClientWidgetLayout" in response.text
    assert "function initPolicyClientWorkspace()" in response.text
    assert "if (AGENT_CLIENT_MODE) {" in response.text
    assert "if (!AGENT_CLIENT_MODE) renderGlobalPanels(lastGlobalData || {});" in response.text
    assert "body.policy-client-mode #mettascope { display: none; }" not in response.text
    assert "return wsUrl(`/policy/${agentId}`);" not in response.text
    assert "function policyDebugWsUrl(agentId = selectedAgentId)" in response.text
    assert "return wsUrl(`/policy-debug/${agentId}`);" in response.text
    assert "function playerWsUrl()" in response.text
    assert "return wsUrlWithCurrentQuery('/player');" in response.text
    assert "if (PLAYER_CLIENT_MODE) connectPlayerStream(); else if (POLICY_DEBUGGER_MODE) connectPolicyDebugStream(); else connectGlobalStream();" in response.text
    assert "connectPolicyStream" not in response.text
    assert "const url = POLICY_DEBUGGER_MODE ? policyDebugWsUrl(selectedAgentId) : agentWsUrl(selectedAgentId);" in response.text
    assert "new WebSocket(policyWsUrl(selectedAgentId))" not in response.text


def test_agent_client_has_footer_game_controls(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const POLICY_CLIENT_WIDGET_LAYOUT_VERSION = 5;" in response.text
    assert 'id="footer-game-controls"' in response.text
    assert 'id="footer-step-button"' in response.text
    assert 'id="footer-play-button"' in response.text
    assert 'id="footer-pause-button"' in response.text
    assert 'id="autostep-toggle"' in response.text
    assert '<span>autostep</span>' in response.text
    assert "function syncFooterGameControls(state = lastAdminState)" in response.text
    assert "adminCommand('step')" in response.text
    assert "adminCommand('start')" in response.text
    assert "adminCommand('stop')" in response.text
    assert "syncFooterGameControls(state);" in response.text
    assert "document.getElementById('footer-step-button').addEventListener('click'" in response.text
    assert "document.getElementById('footer-play-button').addEventListener('click'" in response.text
    assert "document.getElementById('footer-pause-button').addEventListener('click'" in response.text
    assert "document.getElementById('autostep-toggle').addEventListener('change'" in response.text
    assert 'id="step-on-action-toggle"' not in response.text
    footer_idx = response.text.index('id="footer-game-controls"')
    step_idx = response.text.index('id="footer-step-button"')
    autostep_idx = response.text.index('id="autostep-toggle"')
    assert footer_idx < step_idx < autostep_idx
    assert "{ id: 'game_control', module: 'game_control', title: 'Game Control', config: {} }" not in response.text
    assert "registerPolicyWidgetModule('game_control'" not in response.text


def test_policy_client_supports_wasd_action_keys_for_selected_agent(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "const POLICY_ACTION_KEYS = new Map([" in response.text
    assert "['w', 'move_north']" in response.text
    assert "['a', 'move_west']" in response.text
    assert "['s', 'move_south']" in response.text
    assert "['d', 'move_east']" in response.text
    assert "function handlePolicyClientActionKey(event)" in response.text
    assert "if (!AGENT_CLIENT_MODE || isTypingTarget(event.target)) return;" in response.text
    assert "const actionName = POLICY_ACTION_KEYS.get(event.key.toLowerCase());" in response.text
    assert "sendAgentAction(actionName)" in response.text
    assert (
        "agentPanelWs.send(JSON.stringify({ type: 'action', agent_id: selectedAgentId, "
        "action_name: actionName, client_action: true }));"
    ) in response.text
    assert "window.addEventListener('keydown', handlePolicyClientActionKey, true);" in response.text


def test_policy_client_allows_repeated_wasd_action_keydown(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert "if (!AGENT_CLIENT_MODE || event.repeat || isTypingTarget(event.target)) return;" not in response.text
    assert "if (!AGENT_CLIENT_MODE || isTypingTarget(event.target)) return;" in response.text
    assert "if (AGENT_CLIENT_MODE && isAgentPlayShortcut(event)) {" in response.text
    assert "if (event.repeat) return;" in response.text
    assert "sendAgentAction(actionName)" in response.text


def test_policy_client_exposes_autostep_toggle_via_admin(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert 'id="autostep-toggle"' in response.text
    assert 'type="checkbox"' in response.text
    assert "function syncAutostepToggle(state = lastAdminState)" in response.text
    assert "function setAutostepMode(enabled)" in response.text
    assert "adminCommand('set_mode', { mode: enabled ? 'step-on-action' : 'manual' })" in response.text
    assert "toggle.checked = !!state.step_on_action;" in response.text
    assert "document.getElementById('autostep-toggle').addEventListener('change'" in response.text
    assert "setAutostepMode(event.target.checked);" in response.text
    assert "syncAutostepToggle(state);" in response.text
    assert "step-on-action</span>" not in response.text


def test_policy_client_exposes_llm_trigger_button(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert 'id="footer-llm-button"' in response.text
    assert "function sendLlmTrigger()" in response.text
    assert "agentPanelWs.send(JSON.stringify({ type: 'trigger_llm', agent_id: selectedAgentId }))" in response.text
    assert "document.getElementById('footer-llm-button').addEventListener('click'" in response.text


def test_agent_client_space_toggles_play_stop_instead_of_stepping(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_index(None))  # type: ignore[arg-type]

    assert response.text is not None
    assert 'id="footer-step-button"' in response.text
    assert "body.policy-client-mode .footer-game-controls { display: inline-flex; }" in response.text
    assert "document.body.classList.toggle('player-client-mode', PLAYER_CLIENT_MODE);" in response.text
    assert "function toggleAgentClientPlay()" in response.text
    assert "return adminCommand(lastAdminState.playing ? 'stop' : 'start');" in response.text
    assert "function isAgentPlayShortcut(event)" in response.text
    assert "event.code === 'Space'" in response.text
    assert "if (AGENT_CLIENT_MODE && isAgentPlayShortcut(event))" in response.text
    assert "toggleAgentClientPlay();" in response.text
    assert "document.getElementById('footer-step-button').addEventListener('click'" in response.text
    assert 'title="Step one frame (Space)"' not in response.text
    assert "stepPlayerClientFrame()" not in response.text
    assert 'id="player-step-button"' not in response.text


def test_web_renderer_serves_runner_status_page(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)
    renderer.set_status_provider(
        lambda: {
            "components": [{"name": "policies", "state": "coworld", "detail": "toolsy x4"}],
            "endpoints": {"agent_template": "ws://127.0.0.1:8899/agent/{id}"},
        }
    )

    response = asyncio.run(renderer._serve_status(SimpleNamespace(query={}, headers={})))  # type: ignore[arg-type]

    assert response.text is not None
    assert "Cogony Runner Status" in response.text
    assert "policies" in response.text
    assert "coworld" in response.text
    assert "toolsy x4" in response.text
    assert "/status?format=json" in response.text


def test_wasm_html_cache_busts_compiled_assets(tmp_path: Path) -> None:
    wasm_dir = _wasm_dir(tmp_path)
    (wasm_dir / "mettascope.js").write_text("js")
    (wasm_dir / "mettascope.wasm").write_bytes(b"wasm")
    (wasm_dir / "mettascope.data").write_bytes(b"data")
    renderer = WebRenderer(wasm_dir=wasm_dir, port=8899, tick_rate=20)

    response = asyncio.run(renderer._serve_patched_wasm_html(None))  # type: ignore[arg-type]

    assert response.headers["Cache-Control"] == "no-store"
    assert 'src="mettascope.js?v=' in response.text
    assert "locateFile: function(path, prefix)" in response.text
    assert "path + '?v=" in response.text


def test_browser_command_uses_dedicated_chrome_app_window(tmp_path: Path) -> None:
    command = _browser_command(
        ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        "http://localhost:8808",
        tmp_path,
    )

    assert command[0].endswith("Google Chrome")
    assert "--new-window" in command
    assert "--app=http://localhost:8808" in command
    assert f"--user-data-dir={tmp_path}" in command
    assert "--no-first-run" in command


def test_launch_managed_browser_respects_disabled_browser_env(monkeypatch) -> None:
    opened_urls = []
    monkeypatch.setenv("BROWSER", "none")
    monkeypatch.delenv("COGONY_BROWSER", raising=False)
    monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url))

    assert _launch_managed_browser("http://localhost:8808") is None
    assert opened_urls == []


def test_launch_managed_browser_opens_external_window_inside_codex_by_default(monkeypatch) -> None:
    commands = []
    monkeypatch.delenv("COGONY_BROWSER", raising=False)
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.setenv("CODEX_SHELL", "1")

    class FakePopen:
        def __init__(self, command, **kwargs) -> None:
            self.command = command
            commands.append(command)

        def poll(self):
            return 0

    monkeypatch.setattr(web_server, "_find_browser_command", lambda: ["/usr/bin/chromium"])
    monkeypatch.setattr(web_server, "_disable_macos_quit_warning", lambda base_command: None)
    monkeypatch.setattr(web_server.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(web_server, "_terminate_browser_profile_processes", lambda profile_path: None)

    browser = _launch_managed_browser("http://localhost:8808")

    assert browser is not None
    assert commands
    assert "--app=http://localhost:8808" in commands[0]
    browser.close()


def test_web_renderer_codex_browser_mode_skips_external_window(monkeypatch, tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20, codex_browser=True)
    monkeypatch.setattr(web_server, "_launch_managed_browser", lambda url: pytest.fail("should not launch external browser"))

    renderer._launch_browser()

    assert renderer._browser is None


def test_web_renderer_launch_browser_uses_configured_path(monkeypatch, tmp_path: Path) -> None:
    launched = []
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20, launch_path="/admin")
    monkeypatch.setattr(web_server, "_launch_managed_browser", lambda url: launched.append(url) or None)

    renderer._launch_browser()

    assert launched == ["http://localhost:8899/admin"]


def test_launch_managed_chrome_disables_cmd_q_quit_warning(monkeypatch) -> None:
    defaults_calls = []
    _clear_codex_browser_env(monkeypatch)

    class FakePopen:
        def __init__(self, command, **kwargs) -> None:
            self.command = command

        def poll(self):
            return 0

    def fake_defaults(command, **kwargs):
        defaults_calls.append(command)
        if command[:4] == ["defaults", "read", "com.google.Chrome", "WarnBeforeQuittingEnabled"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(web_server.sys, "platform", "darwin")
    monkeypatch.setattr(
        web_server,
        "_find_browser_command",
        lambda: ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
    )
    monkeypatch.setattr(web_server.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(web_server.subprocess, "run", fake_defaults)
    monkeypatch.setattr(web_server, "_terminate_browser_profile_processes", lambda profile_path: None)

    browser = _launch_managed_browser("http://localhost:8808")
    assert browser is not None
    assert ["defaults", "write", "com.google.Chrome", "WarnBeforeQuittingEnabled", "-bool", "false"] in defaults_calls

    browser.close()

    assert ["defaults", "delete", "com.google.Chrome", "WarnBeforeQuittingEnabled"] in defaults_calls


def test_web_renderer_routes_access_log_to_session_file_not_root_logger(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20, log_dir=tmp_path / "logs")
    root_messages = []

    class RootCapture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            root_messages.append(record.getMessage())

    root_handler = RootCapture()
    root_logger = logging.getLogger()
    root_logger.addHandler(root_handler)
    try:
        access_logger = renderer._open_access_log()
        access_logger.info('127.0.0.1 "GET /admin?format=json HTTP/1.1" 200')
    finally:
        root_logger.removeHandler(root_handler)
        renderer._close_access_log()

    assert root_messages == []
    assert renderer.session_log_path == tmp_path / "logs" / f"{renderer.session_id}.out"
    assert 'GET /admin?format=json HTTP/1.1" 200' in renderer.session_log_path.read_text()


def test_web_renderer_records_os_assigned_port(tmp_path: Path) -> None:
    async def run_renderer() -> int:
        renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=0, tick_rate=20, log_dir=tmp_path / "logs")
        renderer._loop = asyncio.get_running_loop()
        task = asyncio.create_task(renderer._serve())
        try:
            deadline = time.monotonic() + 2.0
            while not renderer._ready.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)

            assert renderer._ready.is_set()
            assert renderer._port > 0
            assert renderer.admin_state()["port"] == renderer._port
            return renderer._port
        finally:
            renderer.request_shutdown()
            await asyncio.wait_for(task, timeout=2.0)

    bound_port = asyncio.run(run_renderer())

    assert bound_port != 8808


def test_web_renderer_closes_managed_browser_on_episode_end(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    browser = _FakeBrowser()
    renderer._browser = browser  # type: ignore[assignment]
    renderer._sim = SimpleNamespace(_c_sim=SimpleNamespace(get_episode_stats=lambda: {}))  # type: ignore[assignment]

    renderer.on_episode_end()

    assert browser.closed is True
    assert renderer._browser is None


def test_managed_browser_close_terminates_profile_processes() -> None:
    profile_dir = tempfile.TemporaryDirectory(prefix="cogony-browser-test-")
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", f"--user-data-dir={profile_dir.name}"],
        start_new_session=True,
    )
    browser = _ManagedBrowser(subprocess.Popen(["/usr/bin/true"]), profile_dir)

    try:
        deadline = time.monotonic() + 2.0
        while sleeper.pid not in _browser_profile_pids(profile_dir.name) and time.monotonic() < deadline:
            time.sleep(0.05)

        assert sleeper.pid in _browser_profile_pids(profile_dir.name)

        browser.close()
        deadline = time.monotonic() + 2.0
        while sleeper.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)

        assert sleeper.poll() is not None
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
            sleeper.wait(timeout=2.0)


def test_last_ui_disconnect_waits_for_reconnect_before_shutdown(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._ui_disconnect_grace_seconds = 0.5
    ws = _FakeWs()
    renderer._global_clients.append(ws)  # type: ignore[arg-type]
    renderer._ui_client_seen = True

    renderer._remove_global_client(ws)  # type: ignore[arg-type]

    assert not renderer.shutdown_requested()

    reconnect = _FakeWs()
    renderer._global_clients.append(reconnect)  # type: ignore[arg-type]
    renderer._cancel_ui_disconnect_shutdown()
    time.sleep(0.08)

    assert not renderer.shutdown_requested()


def test_last_ui_disconnect_requests_shutdown_after_grace(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._ui_disconnect_grace_seconds = 0.01
    ws = _FakeWs()
    renderer._global_clients.append(ws)  # type: ignore[arg-type]
    renderer._ui_client_seen = True

    renderer._remove_global_client(ws)  # type: ignore[arg-type]

    deadline = time.monotonic() + 0.5
    while not renderer.shutdown_requested() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert renderer.shutdown_requested()
    assert renderer.wait_until_step_allowed() is False


def test_last_ui_disconnect_does_not_stop_active_autoplay(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20, autoplay=True)
    renderer._ui_disconnect_grace_seconds = 0.01
    ws = _FakeWs()
    renderer._global_clients.append(ws)  # type: ignore[arg-type]
    renderer._ui_client_seen = True

    renderer._remove_global_client(ws)  # type: ignore[arg-type]
    time.sleep(0.05)

    assert not renderer.shutdown_requested()
    assert renderer.wait_until_step_allowed() is True


def test_admin_quit_requests_shutdown_and_unblocks_wait(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    state = renderer.handle_admin_command({"command": "quit"})

    assert state["ok"] is True
    assert state["playing"] is False
    assert state["shutdown_requested"] is True
    assert renderer.shutdown_requested()
    assert renderer.wait_until_step_allowed() is False


def test_panel_step_replay_includes_global_objects_and_sanitized_agent_state() -> None:
    step_replay = {
        "step": 7,
        "episode_stats": {"score": 3},
        "objects": [
            {"id": 1, "type_name": "wall"},
            {
                "id": 2,
                "type_name": "agent",
                "agent_id": 0,
                "policy_infos": {"goal": "join_team", "policy_widgets": ["toolsy_diary"]},
            },
            {"id": 3, "type_name": "market_station"},
        ],
    }

    panel_replay = build_panel_step_replay(step_replay)

    assert panel_replay == {
        "step": 7,
        "episode_stats": {"score": 3},
        "objects": [
            {"id": 2, "type_name": "agent", "agent_id": 0, "policy_infos": {"goal": "join_team"}},
            {"id": 3, "type_name": "market_station"},
        ],
    }


def test_panel_step_replay_includes_agent_last_actions_when_available() -> None:
    step_replay = {
        "step": 7,
        "episode_stats": {},
        "objects": [
            {"id": 2, "type_name": "agent", "agent_id": 0, "policy_infos": {}},
            {"id": 3, "type_name": "agent", "agent_id": 1, "policy_infos": {}},
        ],
    }

    panel_replay = build_panel_step_replay(step_replay, last_actions={0: "move_north"})

    assert panel_replay["objects"][0]["last_action"] == "move_north"
    assert "last_action" not in panel_replay["objects"][1]


def test_agent_state_replay_includes_obs_action_and_log() -> None:
    step_replay = {
        "step": 9,
        "episode_stats": {"score": 4},
        "objects": [
            {
                "id": 7,
                "type_name": "agent",
                "agent_id": 1,
                "policy_infos": {
                    "obs_grid": {"0,0": {"tags": ["type:agent"], "feats": {}}},
                    "llm_log": "LLM CALL 1\n  assistant: move north",
                    "llm_system": "SYSTEM prompt",
                    "goal": "hold_junction",
                },
            }
        ],
    }
    agent_log = [{"step": 9, "log": "LLM CALL 1\n  assistant: move north", "system": "SYSTEM prompt"}]

    state = build_agent_state_replay(step_replay, agent_id=1, last_action="move_north", agent_log=agent_log)

    assert state == {
        "type": "agent_state",
        "agent_id": 1,
        "step": 9,
        "agent": step_replay["objects"][0],
        "obs": {"0,0": {"tags": ["type:agent"], "feats": {}}},
        "last_obs": {"0,0": {"tags": ["type:agent"], "feats": {}}},
        "last_action": "move_north",
        "policy_infos": step_replay["objects"][0]["policy_infos"],
        "llm_log": "LLM CALL 1\n  assistant: move north",
        "llm_system": "SYSTEM prompt",
        "agent_log": agent_log,
        "episode_stats": {"score": 4},
    }


def test_llm_log_delta_returns_only_new_suffix_lines() -> None:
    assert _llm_log_delta("", "LLM CALL 1\n  user: state") == "LLM CALL 1\n  user: state"
    assert _llm_log_delta("LLM CALL 1\n  user: state", "LLM CALL 1\n  user: state") == ""
    assert _llm_log_delta(
        "LLM CALL 1\n  user: state",
        "LLM CALL 1\n  user: state\nRESPONSE 1\n  assistant: move",
    ) == "RESPONSE 1\n  assistant: move"
    assert _llm_log_delta("old conversation", "new conversation") == "new conversation"


def test_agent_log_records_only_ticks_with_llm_log_deltas(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    first_log = "LLM CALL 1\n  user: state"
    second_log = first_log + "\nRESPONSE 1\n  assistant: move"
    base_agent = {
        "id": 7,
        "type_name": "agent",
        "agent_id": 1,
        "policy_infos": {"llm_system": "SYSTEM prompt"},
    }

    renderer._build_agent_state_messages({  # type: ignore[attr-defined]
        "step": 8,
        "objects": [base_agent | {"policy_infos": {"llm_log": first_log, "llm_system": "SYSTEM prompt"}}],
        "episode_stats": {},
    })
    renderer._build_agent_state_messages({  # type: ignore[attr-defined]
        "step": 9,
        "objects": [base_agent | {"policy_infos": {"llm_log": first_log, "llm_system": "SYSTEM prompt"}}],
        "episode_stats": {},
    })
    renderer._build_agent_state_messages({  # type: ignore[attr-defined]
        "step": 10,
        "objects": [base_agent | {"policy_infos": {"llm_log": second_log, "llm_system": "SYSTEM prompt"}}],
        "episode_stats": {},
    })

    assert renderer._agent_logs[1] == [
        {"step": 8, "log": first_log, "system": "SYSTEM prompt", "delta": True},
        {"step": 10, "log": "RESPONSE 1\n  assistant: move", "system": "SYSTEM prompt", "delta": True},
    ]


def test_policy_agent_state_replay_omits_debug_payloads() -> None:
    large_world_model = {"objects": [{"id": idx, "notes": "x" * 1024} for idx in range(2048)]}
    state = {
        "type": "agent_state",
        "agent_id": 1,
        "step": 12,
        "agent": {
            "type_name": "agent",
            "agent_id": 1,
            "location": [4, 5],
            "policy_infos": {
                "current_goals": "Hold the hub.",
                "world_model": large_world_model,
                "diary": [{"step": 11, "event": "debug"}],
            },
        },
        "obs": {"0,0": {"tags": ["type:agent"], "feats": {}}},
        "last_obs": {"0,0": {"tags": ["type:agent"], "feats": {}}},
        "last_action": "move_north",
        "policy_infos": {
            "current_goals": "Hold the hub.",
            "__policy_name__": "toolsy",
            "world_model": large_world_model,
            "llm_log": "CALL 1",
            "llm_system": "SYSTEM",
            "diary": [{"step": 11, "event": "debug"}],
        },
        "llm_log": "CALL 1",
        "llm_system": "SYSTEM",
        "agent_log": [{"step": 11, "log": "CALL 1"}],
        "wall_objects": [{"type_name": "wall"}],
        "episode_stats": {"score": 4},
    }

    policy_state = build_policy_agent_state_replay(state)

    assert len(json.dumps(state)) > 1_048_576
    assert len(json.dumps(policy_state)) < 32_768
    assert policy_state == {
        "type": "agent_state",
        "agent_id": 1,
        "step": 12,
        "agent": {
            "type_name": "agent",
            "agent_id": 1,
            "location": [4, 5],
            "policy_infos": {"current_goals": "Hold the hub.", "__policy_name__": "toolsy"},
        },
        "obs": {"0,0": {"tags": ["type:agent"], "feats": {}}},
        "last_obs": {"0,0": {"tags": ["type:agent"], "feats": {}}},
        "last_action": "move_north",
        "policy_infos": {"current_goals": "Hold the hub.", "__policy_name__": "toolsy"},
        "episode_stats": {"score": 4},
    }


def test_agent_state_replay_does_not_send_policy_provided_widgets() -> None:
    step_replay = {
        "step": 3,
        "episode_stats": {},
        "objects": [
            {
                "type_name": "agent",
                "agent_id": 0,
                "policy_infos": {
                    "policy_widgets": [
                        "obs_map",
                        {"id": "plan", "module": "plan_view", "title": "Plan", "config": {"lines": 4}},
                    ],
                },
            }
        ],
    }

    state = build_agent_state_replay(step_replay, agent_id=0)

    assert "policy_widgets" not in state
    assert "policy_widgets" not in state["policy_infos"]
    assert "policy_widgets" not in state["agent"]["policy_infos"]


def test_agent_state_does_not_add_widgets_after_external_policy_info_merge(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    step_replay = {
        "step": 4,
        "objects": [{"type_name": "agent", "agent_id": 2, "policy_infos": {}}],
        "episode_stats": {},
    }
    renderer._latest_agent_state_msgs[2] = json.dumps(build_agent_state_replay(step_replay, agent_id=2))

    renderer.handle_agent_message(
        2,
        {
            "type": "action",
            "action_name": "noop",
            "policy_infos": {
                "policy_widgets": [
                    {"id": "toolsy_goals", "module": "toolsy_goals", "title": "Goals", "config": {}},
                    {"id": "toolsy_diary", "module": "toolsy_diary", "title": "Diary", "config": {}},
                ],
            },
        },
    )

    state = renderer.agent_state(2)

    assert "policy_widgets" not in state
    assert "policy_widgets" not in state["policy_infos"]


def test_agent_state_drops_stale_top_level_widgets_from_policy_infos(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._latest_agent_state_msgs[0] = json.dumps({
        "type": "agent_state",
        "agent_id": 0,
        "step": 1,
        "agent": {
            "type_name": "agent",
            "agent_id": 0,
            "policy_infos": {
                "policy_widgets": [
                    {"id": "toolsy_goals", "module": "toolsy_goals", "title": "Goals", "config": {}},
                ],
            },
        },
        "policy_infos": {
            "policy_widgets": [
                {"id": "toolsy_goals", "module": "toolsy_goals", "title": "Goals", "config": {}},
            ],
        },
        "policy_widgets": [],
    })

    state = renderer.agent_state(0)

    assert "policy_widgets" not in state
    assert "policy_widgets" not in state["agent"]["policy_infos"]


def test_agent_state_message_drops_stale_empty_top_level_widgets(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._latest_agent_state_msgs[0] = json.dumps({
        "type": "agent_state",
        "agent_id": 0,
        "step": 1,
        "policy_infos": {
            "policy_widgets": [
                {"id": "toolsy_diary", "module": "toolsy_diary", "title": "Diary", "config": {}},
            ],
        },
        "policy_widgets": [],
    })

    state = json.loads(renderer.agent_state_message(0))

    assert "policy_widgets" not in state


def test_next_websocket_agent_id_wraps_to_existing_agents() -> None:
    assert next_websocket_agent_id(0, 1) == 0
    assert next_websocket_agent_id(1, 1) == 0
    assert next_websocket_agent_id(3, 2) == 1


def test_admin_commands_control_step_permission(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    assert renderer.admin_state()["playing"] is False
    assert not renderer._consume_step_permission()

    state = renderer.handle_admin_command({"command": "stop"})
    assert state["playing"] is False
    assert not renderer._consume_step_permission()

    state = renderer.handle_admin_command({"command": "frame"})
    assert state["playing"] is False
    assert state["frame_requests"] == 1
    assert renderer._consume_step_permission()
    assert not renderer._consume_step_permission()

    state = renderer.handle_admin_command({"command": "play"})
    assert state["playing"] is True
    assert renderer._consume_step_permission()


def test_autostep_defaults_on_and_survives_play_stop_and_step(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    state = renderer.admin_state()
    assert state["mode"] == "step-on-action"
    assert state["step_on_action"] is True

    state = renderer.handle_admin_command({"command": "play"})
    assert state["playing"] is True
    assert state["step_on_action"] is True

    state = renderer.handle_admin_command({"command": "stop"})
    assert state["playing"] is False
    assert state["mode"] == "step-on-action"
    assert state["step_on_action"] is True

    state = renderer.handle_admin_command({"command": "step"})
    assert state["playing"] is False
    assert state["mode"] == "step-on-action"
    assert state["step_on_action"] is True
    assert renderer._consume_step_permission()

    state = renderer.handle_admin_command({"command": "set_mode", "mode": "manual"})
    assert state["mode"] == "stopped"
    assert state["step_on_action"] is False


def test_autoplay_starts_with_step_permission(tmp_path: Path) -> None:
    renderer = WebRenderer(
        wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20, autoplay=True,
    )

    assert renderer.admin_state()["playing"] is True
    assert renderer._consume_step_permission()


def test_admin_speed_updates_tick_rate(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    state = renderer.handle_admin_command({"command": "speed", "speed": 12.5})

    assert state["speed"] == 12.5
    assert renderer._tick_interval == 0.08


def test_admin_supports_named_server_controls(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._sim = _FakeSim(current_step=4)  # type: ignore[assignment]

    state = renderer.handle_admin_command({"command": "start()"})
    assert state["playing"] is True
    assert renderer._consume_step_permission()

    state = renderer.handle_admin_command({"command": "stop()"})
    assert state["playing"] is False
    assert not renderer._consume_step_permission()

    state = renderer.handle_admin_command({"command": "step"})
    assert state["playing"] is False
    assert state["frame_requests"] == 1
    assert renderer._consume_step_permission()
    assert not renderer._consume_step_permission()

    state = renderer.handle_admin_command({"command": "goto", "frame": 7})
    assert state["playing"] is False
    assert state["frame_requests"] == 3
    assert [renderer._consume_step_permission() for _ in range(4)] == [True, True, True, False]

    state = renderer.handle_admin_command({"command": "set_ticks_per_second", "ticks_per_second": 12.5})
    assert state["speed"] == 12.5
    assert renderer._tick_interval == 0.08

    with pytest.raises(ValueError, match="cannot goto past frame"):
        renderer.handle_admin_command({"command": "goto", "frame": 2})


def test_admin_supports_method_style_control_strings(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._sim = _FakeSim(current_step=4)  # type: ignore[assignment]

    state = renderer.handle_admin_command({"command": "goto(6)"})
    assert state["frame_requests"] == 2

    state = renderer.handle_admin_command({"command": "set_ticks_per_second(25)"})
    assert state["speed"] == 25.0
    assert renderer._tick_interval == 0.04


def test_heartbeat_message_reports_admin_and_connections(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._sim = _FakeSim(current_step=4)  # type: ignore[assignment]
    renderer.handle_admin_command({"command": "start"})

    message = json.loads(renderer.heartbeat_message())

    assert message["type"] == "heartbeat"
    assert isinstance(message["server_time"], float)
    assert message["admin"]["playing"] is True
    assert message["admin"]["step"] == 4
    assert message["connections"] == {"players": 0, "global": 0, "agents": 0, "policy": 0, "policy_debug": 0}


def test_stop_clears_queued_frames_and_pending_actions(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    with renderer._lock:
        renderer._playing = True
        renderer._frame_requests = 3
        renderer._pending_actions[0] = "move_north"

    state = renderer.handle_admin_command({"command": "stop"})

    assert state["playing"] is False
    assert state["frame_requests"] == 0
    assert not renderer._consume_step_permission()
    assert renderer._pending_actions == {}


def test_player_action_does_not_grant_step_permission_while_paused(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer.handle_admin_command({"command": "set_mode", "mode": "manual"})

    renderer.queue_player_action(0, "move_north")

    assert not renderer._consume_step_permission()
    assert renderer._pending_actions == {0: "move_north"}


def test_authenticated_player_action_is_bound_to_player_slot(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    ignored_step_controls = renderer.handle_player_message(
        {"type": "action", "agent_id": 0, "action_name": "move_north"},
        authenticated_agent_id=2,
    )

    assert ignored_step_controls == 1
    assert renderer._pending_actions == {2: "move_north"}
    assert renderer._last_actions == {2: "move_north"}


def test_agent_message_uses_path_agent_id_and_records_last_action(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    ignored_step_controls = renderer.handle_agent_message(
        2,
        {"type": "action", "action_name": "move_west"},
        ignored_step_controls=0,
    )

    assert ignored_step_controls == 0
    assert renderer._pending_actions == {2: "move_west"}
    assert renderer.agent_state(2)["last_action"] == "move_west"


def test_agent_message_merges_external_policy_infos_for_next_render(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._sim = SimpleNamespace(  # type: ignore[assignment]
        _context={"policy_infos": {2: {"__policy_name__": "toolsy"}}}
    )

    renderer.handle_agent_message(
        2,
        {
            "type": "action",
            "action_name": "move_east",
            "policy_infos": {"goal": "thinking", "llm_log": "CALL 1"},
        },
    )
    renderer._merge_external_policy_infos()

    assert renderer._sim._context["policy_infos"][2] == {
        "__policy_name__": "toolsy",
        "goal": "thinking",
        "llm_log": "CALL 1",
    }


def test_agent_request_queues_action_without_stale_state_echo(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    response = renderer.handle_agent_request(
        2,
        {
            "type": "action",
            "action_name": "noop",
            "policy_infos": {
                "policy_widgets": [
                    {"id": "toolsy_diary", "module": "toolsy_diary", "title": "Diary", "config": {}},
                ],
            },
        },
    )

    assert response["broadcast_state"] is False
    assert response["messages"] == []
    assert renderer._pending_actions == {2: "noop"}
    assert "policy_widgets" not in renderer._external_policy_infos[2]


def test_agent_request_does_not_emit_action_state_until_next_render(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    response = renderer.handle_agent_request(2, {"type": "action", "action_name": "move_west"})

    assert response["broadcast_state"] is False
    assert response["messages"] == []
    assert renderer._last_actions[2] == "move_west"


def test_policy_and_policy_debug_clients_receive_scoped_agent_state_broadcasts(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    class CaptureWs:
        closed = False

        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send_str(self, message: str) -> None:
            self.messages.append(message)

        async def close(self) -> None:
            self.closed = True

    policy_ws = CaptureWs()
    debug_ws = CaptureWs()
    renderer._policy_clients[2] = [policy_ws]  # type: ignore[list-item]
    renderer._policy_debug_clients[2] = [debug_ws]  # type: ignore[list-item]

    full_message = json.dumps({
        "type": "agent_state",
        "agent_id": 2,
        "policy_infos": {"current_goals": "Hold.", "world_model": {"objects": [{"id": 1}]}},
        "llm_log": "CALL 1",
    })
    policy_message = json.dumps({
        "type": "agent_state",
        "agent_id": 2,
        "policy_infos": {"current_goals": "Hold."},
    })

    asyncio.run(renderer._async_broadcast_agent_states({2: full_message}, policy_messages={2: policy_message}))

    assert policy_ws.messages == [policy_message]
    assert debug_ws.messages == [full_message]


def test_agent_state_reports_action_newer_than_cached_render(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    step_replay = {
        "step": 4,
        "objects": [{"type_name": "agent", "agent_id": 2, "policy_infos": {}}],
        "episode_stats": {},
    }
    renderer._latest_agent_state_msgs[2] = json.dumps(
        build_agent_state_replay(step_replay, agent_id=2, last_action=None)
    )

    renderer.handle_agent_message(2, {"type": "action", "action_name": "move_east"})

    assert renderer.agent_state(2)["last_action"] == "move_east"


def test_agent_request_echoes_request_id_for_widget_requests(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    step_replay = {
        "step": 4,
        "objects": [{"type_name": "agent", "agent_id": 2, "policy_infos": {}}],
        "episode_stats": {},
    }
    renderer._latest_agent_state_msgs[2] = json.dumps(build_agent_state_replay(step_replay, agent_id=2))

    response = renderer.handle_agent_request(2, {"type": "get_state", "request_id": "widget-42"})

    assert response["messages"][0]["request_id"] == "widget-42"


def test_agent_request_updates_current_goals_for_policy_context(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._sim = SimpleNamespace(  # type: ignore[assignment]
        current_step=4,
        _context={"policy_infos": {2: {"__policy_name__": "toolsy"}}},
    )

    response = renderer.handle_agent_request(
        2,
        {"type": "add_goal", "request_id": "add-goal-1", "goals": ["Join red and capture two junctions."]},
    )
    renderer._merge_external_policy_infos()

    assert response["messages"] == [
        {
            "type": "add_goal",
            "agent_id": 2,
            "current_goals": "Join red and capture two junctions.",
            "goal_tasks": [
                {
                    "id": "goal-1",
                    "text": "Join red and capture two junctions.",
                    "completed": False,
                }
            ],
            "request_id": "add-goal-1",
        }
    ]
    assert renderer._sim._context["policy_infos"][2]["current_goals"] == "Join red and capture two junctions."
    assert renderer._sim._context["policy_infos"][2]["goal_tasks"] == [
        {"id": "goal-1", "text": "Join red and capture two junctions.", "completed": False}
    ]
    assert renderer.agent_state(2)["policy_infos"]["current_goals"] == "Join red and capture two junctions."


def test_agent_request_updates_structured_goal_tasks_for_policy_context(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._sim = SimpleNamespace(  # type: ignore[assignment]
        current_step=4,
        _context={"policy_infos": {2: {"__policy_name__": "toolsy"}}},
    )
    goal_tasks = [
        {"id": "goal-1", "text": "Mine carbon", "completed": True},
        {"id": "goal-2", "text": "Sell cargo", "completed": False},
    ]

    response = renderer.handle_agent_request(
        2,
        {"type": "add_goal", "request_id": "add-goal-2", "goal_tasks": goal_tasks},
    )
    renderer._merge_external_policy_infos()

    assert response["messages"] == [
        {
            "type": "add_goal",
            "agent_id": 2,
            "current_goals": "Sell cargo",
            "goal_tasks": goal_tasks,
            "request_id": "add-goal-2",
        }
    ]
    assert renderer._sim._context["policy_infos"][2]["current_goals"] == "Sell cargo"
    assert renderer._sim._context["policy_infos"][2]["goal_tasks"] == goal_tasks
    assert renderer.agent_state(2)["policy_infos"]["goal_tasks"] == goal_tasks


def test_agent_request_records_llm_trigger_for_policy_process(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer._sim = SimpleNamespace(  # type: ignore[assignment]
        current_step=4,
        _context={"policy_infos": {2: {"__policy_name__": "toolsy"}}},
    )

    response = renderer.handle_agent_request(2, {"type": "trigger_llm", "request_id": "llm-1"})

    assert response["broadcast_state"] is True
    assert response["messages"] == [
        {"type": "llm_trigger", "agent_id": 2, "llm_trigger_id": 1, "request_id": "llm-1"}
    ]
    state = renderer.agent_state(2)
    assert state["llm_trigger_id"] == 1


def test_step_on_action_mode_grants_one_step_per_paused_action(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)

    state = renderer.handle_admin_command({"command": "set_mode", "mode": "step-on-action"})
    assert state["mode"] == "step-on-action"
    assert state["step_on_action"] is True

    renderer.queue_player_action(0, "move_north")

    assert renderer.admin_state()["frame_requests"] == 1
    assert renderer._pending_actions == {0: "move_north"}
    assert renderer._consume_step_permission()
    assert not renderer._consume_step_permission()


def test_step_on_action_ignores_autonomous_policy_actions(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer.handle_admin_command({"command": "set_mode", "mode": "step-on-action"})

    ignored_step_controls = renderer.handle_agent_message(
        0,
        {"type": "action", "action_name": "move_north"},
        ignored_step_controls=0,
    )

    assert ignored_step_controls == 0
    assert renderer.admin_state()["frame_requests"] == 0
    assert renderer._pending_actions == {0: "move_north"}
    assert not renderer._consume_step_permission()


def test_step_on_action_grants_one_step_for_client_policy_actions(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer.handle_admin_command({"command": "set_mode", "mode": "step-on-action"})

    ignored_step_controls = renderer.handle_agent_message(
        0,
        {"type": "action", "action_name": "move_north", "client_action": True},
        ignored_step_controls=0,
    )

    assert ignored_step_controls == 1
    assert renderer.admin_state()["frame_requests"] == 1
    assert renderer._pending_actions == {0: "move_north"}
    assert renderer._consume_step_permission()
    assert not renderer._consume_step_permission()


def test_step_on_action_suppresses_legacy_following_step_control(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    renderer.handle_admin_command({"command": "set_mode", "mode": "step-on-action"})

    ignored_step_controls = renderer.handle_player_message(
        {"type": "action", "agent_id": 0, "action_name": "move_east"},
        ignored_step_controls=0,
    )
    ignored_step_controls = renderer.handle_player_message(
        {"type": "control", "command": "step"},
        ignored_step_controls=ignored_step_controls,
    )

    assert ignored_step_controls == 0
    assert renderer.admin_state()["frame_requests"] == 1
    assert renderer._consume_step_permission()
    assert not renderer._consume_step_permission()


def test_mettascope_paused_actions_request_one_server_step() -> None:
    bridge = Path(".mettagrid/nim/mettascope/src/mettascope/multiplayer.nim").read_text()
    send_actions = bridge[bridge.index("proc mpSendActions*") : bridge.index("proc mpOnAssign")]

    assert 'if not play:' in send_actions
    assert 'mpSendControl("step")' in send_actions


def test_pending_websocket_action_applies_on_current_frame(tmp_path: Path) -> None:
    renderer = WebRenderer(wasm_dir=_wasm_dir(tmp_path), port=8899, tick_rate=20)
    fake_sim = _FakeSim()
    renderer._sim = fake_sim  # type: ignore[assignment]
    with renderer._lock:
        renderer._pending_actions[0] = "move_north"

    renderer.apply_deferred_user_actions()

    assert fake_sim.agents[0].action_name == "move_north"
    assert renderer._pending_actions == {}


class _FakeAgent:
    def __init__(self) -> None:
        self.action_name: str | None = None

    def set_action(self, action) -> None:
        self.action_name = action.name if hasattr(action, "name") else str(action)


class _FakeSim:
    def __init__(self, current_step: int = 0) -> None:
        self.current_step = current_step
        self.agents = {0: _FakeAgent()}

    def agent(self, agent_id: int) -> _FakeAgent:
        return self.agents[agent_id]


class _FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeWs:
    closed = False


def _wasm_dir(tmp_path: Path) -> Path:
    wasm_dir = tmp_path / "wasm"
    wasm_dir.mkdir()
    (wasm_dir / "mettascope.html").write_text(
        '<!doctype html><script>var Module = { canvas: null };</script>'
        '<script async type="text/javascript" src="mettascope.js"></script>'
    )
    return wasm_dir
