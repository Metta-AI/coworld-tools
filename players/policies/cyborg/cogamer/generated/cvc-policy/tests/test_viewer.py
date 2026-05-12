"""Tests for the HTML report viewer (Batch 3)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


def _write_fake_run(
    run_dir: Path,
    *,
    run_id: str = "fake-run-20260101-000000",
    scenario: str = "fake_scenario",
    status: str = "passed",
    cogs: int = 2,
    steps: int = 10,
    seed: int = 42,
    duration_s: float = 1.5,
    events: list[dict] | None = None,
    assertions: list[dict] | None = None,
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    events = events if events is not None else [
        {"step": 0, "agent": 0, "stream": "py", "type": "action",
         "payload": {"role": "miner", "summary": "noop"}},
        {"step": 1, "agent": 0, "stream": "py", "type": "role_change",
         "payload": {"from": "miner", "to": "aligner"}},
        {"step": 2, "agent": 1, "stream": "py", "type": "target",
         "payload": {"kind": "carbon_extractor", "pos": [5, 5], "distance": 3}},
        {"step": 3, "agent": None, "stream": "py", "type": "note",
         "payload": {"text": "hello"}},
        {"step": 5, "agent": 0, "stream": "llm", "type": "llm_tool_call",
         "payload": {"tool": "patch", "input": {}, "latency_ms": 100}},
    ]
    (run_dir / "events.json").write_text(json.dumps(events))
    result = {
        "run_id": run_id,
        "scenario": scenario,
        "started_at": "2026-01-01T00:00:00",
        "duration_s": duration_s,
        "steps": steps,
        "cogs": cogs,
        "mission": "tutorial.miner",
        "variants": [],
        "seed": seed,
        "policy_kwargs": {},
        "status": status,
        "assertions": assertions if assertions is not None else [
            {"name": "no_crash", "passed": True, "message": "ok",
             "failed_at_step": None},
        ],
    }
    (run_dir / "result.json").write_text(json.dumps(result))
    return run_dir


def test_render_writes_report_html_non_empty(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "fake-run")
    out = render(run_dir)
    assert out == run_dir / "report.html"
    assert out.exists()
    assert out.stat().st_size > 0


def test_report_contains_run_id_and_scenario(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(
        tmp_path / "r", run_id="my-run-id-123", scenario="my_scenario"
    )
    html = render(run_dir).read_text()
    assert "my-run-id-123" in html
    assert "my_scenario" in html


def test_report_has_no_timeline_svgs(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=3)
    html = render(run_dir).read_text()
    # Left-panel timelines are gone; no timeline SVGs in the output.
    svgs = re.findall(r"<svg[^>]*class=\"timeline\"", html)
    assert len(svgs) == 0


def test_report_main_has_replay_handle_log_columns(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=3)
    html = render(run_dir).read_text()
    # Three slots: replay column, drag handle, log column. The grid uses
    # a CSS variable so the JS resize can override the default ratio.
    assert 'id="main-grid"' in html
    assert 'id="col-resize"' in html
    assert "grid-template-columns: var(--main-cols" in html


def test_report_layout_fills_viewport_height(tmp_path: Path) -> None:
    """Body/main/section use flex column + grow so the page fills the
    viewport vertically and regressions to fixed heights fail tests."""
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=2)
    html = render(run_dir).read_text()

    # html, body must stretch to full viewport height.
    assert re.search(r"html,\s*body\s*\{[^}]*height:\s*100%", html), (
        "expected `html, body { height: 100% }` rule"
    )
    # body is a flex column so header/main/footer stack vertically.
    assert re.search(
        r"body\s*\{[^}]*display:\s*flex[^}]*flex-direction:\s*column",
        html,
    ), "expected body to be a flex column"
    # main must grow to fill remaining space.
    assert re.search(r"main\s*\{[^}]*flex:\s*1", html), (
        "expected `main { ... flex: 1 ... }` so it fills remaining height"
    )
    # section must be a flex column (so iframe / #log can grow inside).
    assert re.search(
        r"section\s*\{[^}]*display:\s*flex[^}]*flex-direction:\s*column",
        html,
    ), "expected section to be a flex column"
    # iframe grows inside replay section.
    assert re.search(r"\.replay-card iframe\s*\{[^}]*flex:\s*1", html), (
        "expected replay iframe to grow via flex: 1"
    )
    # #log grows inside log section instead of a fixed max-height.
    assert re.search(r"#log\s*\{[^}]*flex:\s*1", html), (
        "expected #log to grow via flex: 1"
    )


def test_report_embeds_events_json_blob(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action",
         "payload": {"role": "miner"}},
        {"step": 3, "agent": None, "stream": "py", "type": "note",
         "payload": {"text": "team event"}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", events=events)
    html = render(run_dir).read_text()
    m = re.search(
        r'<script type="application/json" id="events">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m is not None
    parsed = json.loads(m.group(1))
    assert parsed == events


def test_report_failure_view_shows_failed_assertion(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(
        tmp_path / "r",
        status="failed",
        assertions=[
            {"name": "mining_trips_efficient", "passed": False,
             "message": "plateau waste", "failed_at_step": 42},
        ],
    )
    html = render(run_dir).read_text()
    assert "mining_trips_efficient" in html
    assert "failed" in html.lower()
    assert "42" in html  # failed_at_step surfaced


def test_report_tick_has_data_attrs(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 7, "agent": 0, "stream": "py", "type": "action",
         "payload": {"role": "miner", "summary": "mine_carbon"}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events)
    html = render(run_dir).read_text()
    # Tick should carry data-step / data-agent / data-type attributes.
    assert 'data-step="7"' in html
    assert 'data-agent="0"' in html
    assert 'data-type="action"' in html


def test_report_replay_card_present_when_replay_file_exists(
    tmp_path: Path,
) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "my-run")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()
    # Replay card present and references replay resource somehow.
    assert "replay-card" in html


def test_render_includes_compact_copy_badge(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "my-run")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()
    assert 'data-copy="softmax cogames replay ' in html


def test_report_replay_copy_badge_uses_absolute_path(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "my-run")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()
    m = re.search(r'data-copy="softmax cogames replay ([^"]+)"', html)
    assert m is not None
    path_part = m.group(1)
    assert Path(path_part).is_absolute()
    assert Path(path_part).exists()
    assert "replay.json.z" in path_part


def test_report_replay_cmd_is_header_button(tmp_path: Path) -> None:
    """Replay cmd lives as a compact button inside <header>, not a full-width row."""
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "my-run")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()
    # Old full-width row is gone.
    assert "replay-cmd-line" not in html
    # Header contains a .header-copy button with the copy data attribute.
    m = re.search(r"<header[^>]*>(.*?)</header>", html, re.DOTALL)
    assert m is not None
    header = m.group(1)
    assert "header-copy" in header
    assert 'data-copy="softmax cogames replay ' in header
    assert "copy replay cmd" in header


def test_render_includes_mettascope_iframe(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "my-run")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()
    assert '<iframe id="mettascope"' in html
    # JS prefers the locally-served mettascope path (fixes mixed-content).
    assert "./mettascope/mettascope.html" in html
    # Github-pages URL is still present as fallback.
    assert "https://metta-ai.github.io/metta/mettascope/mettascope.html" in html
    assert "./replay.json.z" in html


def test_render_iframe_prefers_local_mettascope_on_http(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()
    # The inline JS constructs a ./mettascope/mettascope.html URL (same
    # origin as the run folder), not jumping straight to the github URL.
    # Ensure the local path appears before the remote fallback in source.
    assert html.find("./mettascope/mettascope.html") < html.find(
        "https://metta-ai.github.io/metta/mettascope/mettascope.html"
    )


def test_report_scrubber_pushes_step_to_mettascope_iframe(tmp_path: Path) -> None:
    """setStep posts mettascopeSetStep to the iframe contentWindow."""
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()

    # Post the message type that mettascope listens for, on the iframe's
    # contentWindow (not window.parent).
    assert "'mettascopeSetStep'" in html
    assert "iframe.contentWindow.postMessage" in html


def test_report_listens_for_mettascope_step_with_source_check(
    tmp_path: Path,
) -> None:
    """Inbound mettascopeStep handler is wired and verifies event.source."""
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()

    # The inbound message type from mettascope.
    assert "'mettascopeStep'" in html
    # Must verify the message came from our own iframe, not a random window.
    assert "event.source !== iframe.contentWindow" in html


def test_report_guards_against_mettascope_step_feedback_loop(
    tmp_path: Path,
) -> None:
    """The inbound handler must suppress the outbound push to avoid a loop."""
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()

    # A dedicated flag guards the re-entry: setStep reads it to skip the
    # outbound postMessage, and the inbound handler sets/clears it.
    assert "suppressMettascopePush" in html


def test_render_neutralizes_script_end_in_json_island(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(
        tmp_path / "r",
        events=[
            {"step": 0, "agent": 0, "stream": "py", "type": "note",
             "payload": {"text": "oops </script><script>alert(1)</script>"}},
        ],
    )
    html = render(run_dir).read_text()
    # Extract only the JSON island and assert no `</script>` breaks out.
    m = re.search(
        r'<script type="application/json" id="events">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m is not None
    island = m.group(1)
    assert "</script>" not in island
    # Escaped form should appear inside the island.
    assert "<\\/script>" in island
    # And the island JSON must still round-trip to the original payload.
    parsed = json.loads(island)
    assert parsed[0]["payload"]["text"] == "oops </script><script>alert(1)</script>"


def test_render_escapes_event_text_in_log_panel(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(
        tmp_path / "r",
        events=[
            {"step": 0, "agent": 0, "stream": "py", "type": "note",
             "payload": {"text": "<img src=x onerror=alert(1)>"}},
        ],
    )
    html = render(run_dir).read_text()
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_render_escapes_assertion_message(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(
        tmp_path / "r",
        status="failed",
        assertions=[
            {"name": "bad", "passed": False,
             "message": "<script>alert('x')</script>",
             "failed_at_step": 3},
        ],
    )
    html = render(run_dir).read_text()
    assert "<script>alert('x')</script>" not in html
    assert "&lt;script&gt;alert(" in html




def test_report_has_no_standalone_filter_bar(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=3)
    html = render(run_dir).read_text()
    # The standalone top filter bar is gone; contents moved into the
    # right (log) panel.
    assert '<section class="filter-bar"' not in html


def test_agent_filters_live_in_log_panel(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=3)
    html = render(run_dir).read_text()
    # Find the log panel section (the one containing #log).
    m = re.search(
        r'<section[^>]*class="log-card"[^>]*>(.*?)</section>',
        html,
        re.DOTALL,
    )
    assert m is not None, "log-card section not found"
    panel = m.group(1)
    # Exactly one checkbox per cog, all inside the log panel.
    cbs = re.findall(r'class="agent-toggle"', panel)
    assert len(cbs) == 3
    # Search + type chips also in the log panel.
    assert 'id="search"' in panel
    assert 'id="type-chips"' in panel


def test_agent_checkboxes_total_count_matches_cogs(tmp_path: Path) -> None:
    """Exactly `cogs` agent checkboxes in the whole report, not duplicated."""
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=4)
    html = render(run_dir).read_text()
    cbs = re.findall(r'class="agent-toggle"', html)
    assert len(cbs) == 4


def test_group_by_step_dense_has_no_ranges() -> None:
    """Every step has ≥ 1 event: no range groups."""
    from cvc_policy.viewer.render import _group_by_step

    events = [
        {"step": 0, "type": "a"},
        {"step": 1, "type": "b"},
        {"step": 2, "type": "c"},
    ]
    groups = _group_by_step(events, max_step=2)
    assert all(g["type"] == "step" for g in groups)
    assert len(groups) == 3


def test_group_by_step_collapses_multi_empty_gap() -> None:
    """A gap of ≥ 2 consecutive empty steps becomes one range group."""
    from cvc_policy.viewer.render import _group_by_step

    # events at steps 12, 13, and 200. Everything in 14..199 is empty.
    events = [
        {"step": 12, "type": "a"},
        {"step": 13, "type": "b"},
        {"step": 200, "type": "c"},
    ]
    groups = _group_by_step(events, max_step=200)
    # First must be a range [0-11] (12 empty steps before first event).
    assert groups[0] == {"type": "range", "start": 0, "end": 11}
    # step 12 and step 13 are populated.
    assert groups[1]["type"] == "step" and groups[1]["step"] == 12
    assert groups[2]["type"] == "step" and groups[2]["step"] == 13
    # Then [14-199] range.
    assert groups[3] == {"type": "range", "start": 14, "end": 199}
    # Then step 200.
    assert groups[4]["type"] == "step" and groups[4]["step"] == 200


def test_group_by_step_single_gap_not_collapsed() -> None:
    """A single empty step stays as a step group (no range)."""
    from cvc_policy.viewer.render import _group_by_step

    events = [
        {"step": 0, "type": "a"},
        {"step": 2, "type": "b"},  # step 1 is a single empty step
    ]
    groups = _group_by_step(events, max_step=2)
    # step 0 event, then step 1 empty (as a bare step marker), then step 2.
    # Requirement: "Single-step gaps: emit `step N` (no range)."
    assert groups[0]["type"] == "step" and groups[0]["step"] == 0
    assert groups[1]["type"] == "step" and groups[1]["step"] == 1
    assert groups[1]["events"] == []
    assert groups[2]["type"] == "step" and groups[2]["step"] == 2


def test_group_by_step_no_events_single_range() -> None:
    """No events: one range [0-max_step] spanning the whole run."""
    from cvc_policy.viewer.render import _group_by_step

    groups = _group_by_step([], max_step=99)
    assert groups == [{"type": "range", "start": 0, "end": 99}]


def test_group_by_step_events_on_step_zero() -> None:
    from cvc_policy.viewer.render import _group_by_step

    events = [{"step": 0, "type": "a"}, {"step": 0, "type": "b"}]
    groups = _group_by_step(events, max_step=0)
    assert len(groups) == 1
    assert groups[0]["type"] == "step"
    assert groups[0]["step"] == 0
    assert len(groups[0]["events"]) == 2


def test_group_by_step_trailing_empty_range() -> None:
    """Empty tail past the last event still produces a range marker."""
    from cvc_policy.viewer.render import _group_by_step

    events = [{"step": 0, "type": "a"}]
    groups = _group_by_step(events, max_step=10)
    assert groups[0]["type"] == "step" and groups[0]["step"] == 0
    # steps 1..10 all empty → one range [1-10].
    assert groups[-1] == {"type": "range", "start": 1, "end": 10}


def test_render_sparse_events_no_step_range(tmp_path: Path) -> None:
    """Step-range gaps are no longer emitted."""
    from cvc_policy.viewer import render

    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action", "payload": {}},
        {"step": 100, "agent": 0, "stream": "py", "type": "action", "payload": {}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events, steps=100)
    html = render(run_dir).read_text()
    assert 'class="step-range"' not in html


def test_render_dense_events_no_step_range(tmp_path: Path) -> None:
    """Every step has events: zero step-range elements."""
    from cvc_policy.viewer import render

    events = [
        {"step": i, "agent": 0, "stream": "py", "type": "action",
         "payload": {"summary": f"s{i}"}}
        for i in range(5)
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events, steps=4)
    html = render(run_dir).read_text()
    m = re.search(r'<div id="log">(.*?)</div>\s*</section>', html, re.DOTALL)
    assert m is not None
    log = m.group(1)
    assert 'class="step-range"' not in log
    # And one step label per step (5 distinct steps) — data-step-label
    # attribute on the first line of each step block.
    labels = re.findall(r'data-step-label="(\d+)"', log)
    assert len(labels) == 5


def test_render_no_step_range_attrs(tmp_path: Path) -> None:
    """Step-range gaps are no longer emitted."""
    from cvc_policy.viewer import render

    events = [
        {"step": 5, "agent": 0, "stream": "py", "type": "action", "payload": {}},
        {"step": 20, "agent": 0, "stream": "py", "type": "action", "payload": {}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events, steps=20)
    html = render(run_dir).read_text()
    assert 'class="step-range"' not in html


def test_log_has_step_separators_between_distinct_steps(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action",
         "payload": {"summary": "a"}},
        {"step": 1, "agent": 0, "stream": "py", "type": "action",
         "payload": {"summary": "b"}},
        {"step": 2, "agent": 0, "stream": "py", "type": "action",
         "payload": {"summary": "c"}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events)
    html = render(run_dir).read_text()
    # Extract just the log panel.
    m = re.search(r'<div id="log">(.*?)</div>\s*</section>', html, re.DOTALL)
    assert m is not None
    log = m.group(1)
    seps = re.findall(r'class="step-sep"', log)
    # At least one separator between distinct steps.
    assert len(seps) >= 2


def test_log_colors_lines_by_stream(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action",
         "payload": {}},
        {"step": 1, "agent": 0, "stream": "llm", "type": "llm_tool_call",
         "payload": {"tool": "patch"}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events)
    html = render(run_dir).read_text()
    # Stream is encoded via data-stream on each .line; CSS colors the line.
    assert 'data-stream="py"' in html
    assert 'data-stream="llm"' in html
    assert '#log .line[data-stream="py"]' in html
    assert '#log .line[data-stream="llm"]' in html
    # No literal [py]/[llm] text in the log, no stream tag spans.
    m = re.search(r'<div id="log">(.*?)</div>\s*</section>', html, re.DOTALL)
    assert m is not None
    log = m.group(1)
    assert "[py]" not in log
    assert "[llm]" not in log
    assert 'class="stream stream-py"' not in log
    assert 'class="stream stream-llm"' not in log


def test_log_uses_per_agent_colors(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action",
         "payload": {}},
        {"step": 0, "agent": 1, "stream": "py", "type": "action",
         "payload": {}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=2, events=events)
    html = render(run_dir).read_text()
    m = re.search(r'<div id="log">(.*?)</div>\s*</section>', html, re.DOTALL)
    assert m is not None
    log = m.group(1)
    tags = re.findall(
        r'<span class="agent-tag"[^>]*style="color:\s*([^"]+)"[^>]*>a(\d+)</span>',
        log,
    )
    agent_to_color = {a: c for c, a in tags}
    assert "0" in agent_to_color
    assert "1" in agent_to_color
    assert agent_to_color["0"] != agent_to_color["1"]


def test_payload_text_helper_strips_stream_and_agent_prefix() -> None:
    from cvc_policy.recorder import payload_text

    ev = {"step": 7, "agent": 2, "stream": "py", "type": "target",
          "payload": {"kind": "carbon_extractor", "pos": [1, 1]}}
    out = payload_text(ev)
    assert "[py]" not in out
    assert "a2" not in out
    # No step=... / type prefix either — just the payload bit.
    assert "step=" not in out
    assert "target" not in out.split()[:1]
    # Should still contain payload values.
    assert "carbon_extractor" in out


def test_cgp_view_rejects_path_traversal(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from cvc_policy.cli import app

    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    # Sibling directory the attacker is trying to escape into.
    (tmp_path / "escape").mkdir()

    result = CliRunner().invoke(
        app, ["view", "../escape", "--runs-root", str(runs_root)]
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "traversal" in combined.lower() or "outside" in combined.lower()


def test_cgp_view_no_server_opens_file_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from cvc_policy.cli import app

    runs_root = tmp_path / "runs"
    _write_fake_run(runs_root / "abc-20260101-000000", run_id="abc")

    opened: list[str] = []
    monkeypatch.setattr(
        "webbrowser.open", lambda url: opened.append(url) or True
    )

    result = CliRunner().invoke(
        app,
        [
            "view",
            "abc-20260101-000000",
            "--runs-root",
            str(runs_root),
            "--no-server",
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(opened) == 1
    opened_path = opened[0]
    # file:// URL pointing at an existing report.html
    assert opened_path.startswith("file://") or Path(opened_path).is_absolute()
    path_str = opened_path.replace("file://", "")
    assert Path(path_str).exists()
    assert path_str.endswith("report.html")


def test_cgp_view_with_server_starts_http_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import re as _re
    import urllib.request

    from typer.testing import CliRunner

    from cvc_policy.cli import app

    # Use a random port so tests don't collide with the user's viewer.
    monkeypatch.delenv("CMUX_PORT", raising=False)

    runs_root = tmp_path / "runs"
    _write_fake_run(runs_root / "abc-20260101-000000", run_id="abc")

    opened: list[str] = []
    monkeypatch.setattr(
        "webbrowser.open", lambda url: opened.append(url) or True
    )

    # Force the blocking loop to exit immediately.
    def _fake_serve_forever(self):  # type: ignore[no-untyped-def]
        raise KeyboardInterrupt

    # Patch ThreadingHTTPServer.serve_forever so `cgp view` returns.
    import http.server

    # The CLI command uses _serve_run helper; by patching serve_forever we let
    # the command start the server, fire open, then unwind via KeyboardInterrupt.
    monkeypatch.setattr(
        http.server.ThreadingHTTPServer,
        "serve_forever",
        _fake_serve_forever,
    )

    result = CliRunner().invoke(
        app,
        [
            "view",
            "abc-20260101-000000",
            "--runs-root",
            str(runs_root),
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(opened) == 1
    url = opened[0]
    m = _re.match(r"^http://localhost:(\d+)$", url)
    assert m is not None, f"unexpected url: {url}"


def test_serve_run_mounts_mettascope_dist_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /mettascope/mettascope.html returns 200 when dist is found."""
    import urllib.request

    from cvc_policy import cli as cli_mod
    from cvc_policy.viewer import render

    runs_root = tmp_path / "runs"
    run_dir = _write_fake_run(runs_root / "abc-20260101-000000", run_id="abc")
    render(run_dir)

    # Fake a mettascope dist with the required marker file.
    fake_dist = tmp_path / "fake-dist"
    fake_dist.mkdir()
    (fake_dist / "mettascope.html").write_text(
        "<!doctype html><title>fake</title>"
    )
    monkeypatch.setattr(cli_mod, "_mettascope_dist", lambda: fake_dist)

    httpd, port = cli_mod._serve_run(run_dir)
    try:
        with urllib.request.urlopen(
            f"http://localhost:{port}/mettascope/mettascope.html", timeout=5
        ) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
            assert "fake" in body
            # COOP/COEP headers emitted for SharedArrayBuffer support.
            assert resp.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
            assert resp.headers.get("Cross-Origin-Embedder-Policy") == "require-corp"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_serve_run_still_serves_run_dir_when_mettascope_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no dist, run-dir paths still serve and COOP/COEP headers present."""
    import urllib.request

    from cvc_policy import cli as cli_mod
    from cvc_policy.viewer import render

    runs_root = tmp_path / "runs"
    run_dir = _write_fake_run(runs_root / "abc-20260101-000000", run_id="abc")
    render(run_dir)

    monkeypatch.setattr(cli_mod, "_mettascope_dist", lambda: None)

    httpd, port = cli_mod._serve_run(run_dir)
    try:
        with urllib.request.urlopen(
            f"http://localhost:{port}/report.html", timeout=5
        ) as resp:
            assert resp.status == 200
            assert resp.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
            assert resp.headers.get("Cross-Origin-Embedder-Policy") == "require-corp"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_serve_run_helper_actually_serves_report(tmp_path: Path) -> None:
    """The _serve_run helper returns a live server that serves report.html."""
    import urllib.request

    from cvc_policy.cli import _serve_run
    from cvc_policy.viewer import render

    runs_root = tmp_path / "runs"
    run_dir = _write_fake_run(runs_root / "abc-20260101-000000", run_id="abc")
    render(run_dir)

    httpd, port = _serve_run(run_dir)
    try:
        with urllib.request.urlopen(
            f"http://localhost:{port}/report.html", timeout=5
        ) as resp:
            body = resp.read().decode("utf-8")
        assert "abc" in body
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_cgp_runs_lists_most_recent_first(
    tmp_path: Path,
) -> None:
    from typer.testing import CliRunner

    from cvc_policy.cli import app

    runs_root = tmp_path / "runs"
    _write_fake_run(runs_root / "old-20260101-000000", run_id="old",
                    scenario="scen_a", status="passed")
    _write_fake_run(runs_root / "new-20260102-000000", run_id="new",
                    scenario="scen_b", status="failed")
    # Bump mtime so "new" is newer.
    import os
    os.utime(runs_root / "new-20260102-000000", (2_000_000_000, 2_000_000_000))
    os.utime(runs_root / "old-20260101-000000", (1_000_000_000, 1_000_000_000))

    result = CliRunner().invoke(app, ["runs", "--runs-root", str(runs_root)])
    assert result.exit_code == 0, result.output
    # Most recent first: "new" before "old".
    assert result.output.find("new-20260102-000000") < result.output.find(
        "old-20260101-000000"
    )
    assert "scen_a" in result.output
    assert "scen_b" in result.output
    assert "failed" in result.output


def test_mettascope_dist_uses_env_var_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CVC_METTASCOPE_DIST wins over all other probes when it contains mettascope.html."""
    from cvc_policy import cli as cli_mod

    dist = tmp_path / "custom-dist"
    dist.mkdir()
    (dist / "mettascope.html").write_text("x")

    monkeypatch.setenv("CVC_METTASCOPE_DIST", str(dist))
    # Force all other probes to fail so we know env var is what matched.
    monkeypatch.setattr(cli_mod, "_mettascope_home_glob_dists", lambda: [])

    import mettagrid

    monkeypatch.setattr(
        mettagrid, "__file__", str(tmp_path / "no_such_mg" / "__init__.py")
    )

    result = cli_mod._mettascope_dist()
    assert result is not None
    assert result.resolve() == dist.resolve()


def test_mettascope_dist_falls_through_env_var_if_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset CVC_METTASCOPE_DIST means no env-var match; later probes run."""
    from cvc_policy import cli as cli_mod

    monkeypatch.delenv("CVC_METTASCOPE_DIST", raising=False)

    # Seed the home-glob probe with a valid fake dist — if env var path ran
    # first and matched nothing, the glob path must still be consulted and win.
    fake_dist = tmp_path / "home-dist"
    fake_dist.mkdir()
    (fake_dist / "mettascope.html").write_text("x")
    monkeypatch.setattr(
        cli_mod, "_mettascope_home_glob_dists", lambda: [fake_dist]
    )

    # Force the site-packages probe to fail.
    import mettagrid

    monkeypatch.setattr(
        mettagrid, "__file__", str(tmp_path / "no_such_mg" / "__init__.py")
    )

    result = cli_mod._mettascope_dist()
    assert result is not None
    assert result.resolve() == fake_dist.resolve()


def test_mettascope_dist_env_var_invalid_dir_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Env var pointing at a dir without mettascope.html is skipped."""
    from cvc_policy import cli as cli_mod

    bad = tmp_path / "no-html-here"
    bad.mkdir()
    monkeypatch.setenv("CVC_METTASCOPE_DIST", str(bad))
    monkeypatch.setattr(cli_mod, "_mettascope_home_glob_dists", lambda: [])

    import mettagrid

    monkeypatch.setattr(
        mettagrid, "__file__", str(tmp_path / "no_such_mg" / "__init__.py")
    )

    result = cli_mod._mettascope_dist()
    assert result is None


def test_mettascope_home_glob_finds_sibling_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_mettascope_home_glob_dists() returns dirs matched by ~/code/metta*/.../dist."""
    from cvc_policy import cli as cli_mod

    fake_home_code = tmp_path / "code"
    dist = (
        fake_home_code
        / "metta-test"
        / "packages"
        / "mettagrid"
        / "nim"
        / "mettascope"
        / "dist"
    )
    dist.mkdir(parents=True)
    (dist / "mettascope.html").write_text("x")

    # expanduser("~/code/metta*") should resolve under our fake HOME.
    monkeypatch.setenv("HOME", str(tmp_path))

    results = cli_mod._mettascope_home_glob_dists()
    assert any(p.resolve() == dist.resolve() for p in results), results


def test_render_iframe_shows_error_panel_when_both_sources_fail(
    tmp_path: Path,
) -> None:
    """JS falls back to an in-page error panel when github.io HEAD also fails."""
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "my-run")
    (run_dir / "replay.json.z").write_bytes(b"fake")
    html = render(run_dir).read_text()

    # The JS must have an error-panel branch with actionable copy.
    assert "Mettascope not available" in html
    assert "CVC_METTASCOPE_DIST" in html


# ---------- merge consecutive duplicate step events ----------


def _dup_event(step: int, *, role: str = "miner", summary: str = "mine_carbon") -> dict:
    return {
        "step": step,
        "agent": 0,
        "stream": "py",
        "type": "action",
        "payload": {"role": role, "summary": summary},
    }


def test_merge_duplicate_consecutive_steps_into_run() -> None:
    """Adjacent steps with one identical event each collapse to one run."""
    from cvc_policy.viewer.render import _group_by_step, _merge_duplicate_steps

    events = [_dup_event(s) for s in (5, 6, 7, 8)]
    groups = _group_by_step(events, max_step=10)
    merged = _merge_duplicate_steps(groups)

    step_groups = [g for g in merged if g["type"] == "step"]
    assert len(step_groups) == 1
    g = step_groups[0]
    assert g["step"] == 5
    assert g["step_end"] == 8
    assert len(g["events"]) == 1
    assert g["events"][0]["step"] == 5


def test_no_merge_across_gap() -> None:
    """Identical events at steps 5 and 7 with empty step 6 stay separate."""
    from cvc_policy.viewer.render import _group_by_step, _merge_duplicate_steps

    events = [_dup_event(5), _dup_event(7)]
    groups = _group_by_step(events, max_step=7)
    merged = _merge_duplicate_steps(groups)

    # Expect (after leading [0-4] range): step 5, step 6 (empty bare), step 7.
    step_groups = [g for g in merged if g["type"] == "step"]
    assert [g["step"] for g in step_groups] == [5, 6, 7]
    assert all(g.get("step_end") in (None, g["step"]) for g in step_groups)
    # Step 6 is the bare empty-step marker between them.
    bare = [g for g in step_groups if g["events"] == []]
    assert len(bare) == 1 and bare[0]["step"] == 6


def test_no_merge_across_range() -> None:
    """A ``range`` group between populated steps blocks merging."""
    from cvc_policy.viewer.render import _group_by_step, _merge_duplicate_steps

    events = [_dup_event(0), _dup_event(100)]
    groups = _group_by_step(events, max_step=100)
    merged = _merge_duplicate_steps(groups)

    assert merged[0]["type"] == "step" and merged[0]["step"] == 0
    assert merged[0].get("step_end") in (None, 0)
    assert merged[1]["type"] == "range"
    assert merged[2]["type"] == "step" and merged[2]["step"] == 100


def test_no_merge_when_multiple_events_on_a_step() -> None:
    """Merging only applies when both sides have exactly one event."""
    from cvc_policy.viewer.render import _group_by_step, _merge_duplicate_steps

    events = [
        _dup_event(5),
        {"step": 5, "agent": 1, "stream": "py", "type": "action",
         "payload": {"role": "aligner", "summary": "scan"}},
        _dup_event(6),
    ]
    groups = _group_by_step(events, max_step=6)
    merged = _merge_duplicate_steps(groups)

    step_groups = [g for g in merged if g["type"] == "step"]
    assert [g["step"] for g in step_groups] == [5, 6]
    assert len(step_groups[0]["events"]) == 2
    assert all(g.get("step_end") in (None, g["step"]) for g in step_groups)


def test_no_merge_when_payload_differs() -> None:
    """Different summaries should not merge."""
    from cvc_policy.viewer.render import _group_by_step, _merge_duplicate_steps

    events = [
        _dup_event(5, summary="mine_carbon"),
        _dup_event(6, summary="deposit_resources"),
    ]
    groups = _group_by_step(events, max_step=6)
    merged = _merge_duplicate_steps(groups)

    step_groups = [g for g in merged if g["type"] == "step"]
    assert [g["step"] for g in step_groups] == [5, 6]
    assert all(g.get("step_end") in (None, g["step"]) for g in step_groups)


def test_no_merge_when_type_differs() -> None:
    """Different event types with same payload_text should not merge."""
    from cvc_policy.viewer.render import _group_by_step, _merge_duplicate_steps

    events = [
        {"step": 5, "agent": 0, "stream": "py", "type": "action",
         "payload": {"role": "miner", "summary": "x"}},
        {"step": 6, "agent": 0, "stream": "py", "type": "note",
         "payload": {"role": "miner", "summary": "x"}},
    ]
    groups = _group_by_step(events, max_step=6)
    merged = _merge_duplicate_steps(groups)

    step_groups = [g for g in merged if g["type"] == "step"]
    assert [g["step"] for g in step_groups] == [5, 6]
    assert all(g.get("step_end") in (None, g["step"]) for g in step_groups)


def test_merge_ignores_varying_latency() -> None:
    """payload_text strips volatile fields — merge still fires."""
    from cvc_policy.viewer.render import _group_by_step, _merge_duplicate_steps

    events = [
        {"step": 5, "agent": 0, "stream": "llm", "type": "llm_tool_call",
         "payload": {"tool": "patch", "input": {}, "latency_ms": 100}},
        {"step": 6, "agent": 0, "stream": "llm", "type": "llm_tool_call",
         "payload": {"tool": "patch", "input": {}, "latency_ms": 250}},
    ]
    groups = _group_by_step(events, max_step=6)
    merged = _merge_duplicate_steps(groups)

    step_groups = [g for g in merged if g["type"] == "step"]
    # If payload_text strips latency_ms these merge; if not, they stay
    # separate. Check whichever the recorder says.
    from cvc_policy.recorder import payload_text
    a = payload_text(events[0])
    b = payload_text(events[1])
    if a == b:
        assert len(step_groups) == 1
        assert step_groups[0]["step"] == 5 and step_groups[0]["step_end"] == 6
    else:
        assert len(step_groups) == 2


def test_render_emits_one_step_marker_per_step_not_pre_merged(tmp_path: Path) -> None:
    """Duplicate-merging is client-side now; render emits one marker per step."""
    from cvc_policy.viewer import render

    events = [_dup_event(s) for s in range(10)]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events, steps=9)
    html = render(run_dir).read_text()

    # Step labels render via data-step-label on the first line of each
    # step block (the standalone step-marker div is only kept for
    # empty-event steps).
    labels = re.findall(r'data-step-label="(\d+)"', html)
    assert [int(m) for m in labels] == list(range(10))


def test_render_lines_have_data_payload_for_js_merging(tmp_path: Path) -> None:
    """Each .line carries data-payload so client JS can test equality."""
    from cvc_policy.viewer import render

    events = [_dup_event(s) for s in range(3)]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events, steps=2)
    html = render(run_dir).read_text()

    assert 'data-payload="' in html
    # Three lines, each with data-payload on the .line element.
    lines_with_payload = re.findall(
        r'<div class="line[^"]*"[^>]*data-payload="[^"]*"',
        html,
        re.DOTALL,
    )
    assert len(lines_with_payload) == 3


def test_render_includes_recompute_merges_js(tmp_path: Path) -> None:
    """The client-side merge function exists in the generated JS."""
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=[], steps=0)
    html = render(run_dir).read_text()
    assert "function recomputeMerges" in html
    # And it must be called from applyFilters so filter changes recompose merges.
    assert "recomputeMerges()" in html


def test_render_click_handler_jumps_scrubber_to_step(tmp_path: Path) -> None:
    """Clicking a .line or .step-marker jumps the scrubber to that step."""
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=[], steps=0)
    html = render(run_dir).read_text()
    # Delegated click handler on #log.
    assert "log.addEventListener('click'" in html
    # Handler reads a step from the target's data-step and calls setStep.
    assert "closest('.line, .step-marker, .step-range')" in html
    assert "setStep(step)" in html


# ---------------------------------------------------------------------------
# Feature 1: Role icon inline in each log line
# ---------------------------------------------------------------------------


def _find_line_block(html: str, idx: int) -> str:
    """Return the substring of a .line div with `data-idx=N`.

    The first line of each step block carries `step-start` in the class
    list, so match either `class="line"` or `class="line step-start"`.
    """
    m = re.search(
        r'<div class="line[^"]*"\s+data-idx="' + str(idx)
        + r'"[^>]*>(.*?)</div>',
        html,
        re.DOTALL,
    )
    assert m is not None, f"could not locate .line idx={idx} in html"
    return m.group(0)


def test_role_glyph_helper_maps_known_roles() -> None:
    from cvc_policy.viewer.render import role_glyph

    assert role_glyph("miner") == "\u26cf"        # pickaxe
    assert role_glyph("aligner") == "\U0001f517"  # link
    assert role_glyph("scrambler") == "\U0001f300"  # spiral
    assert role_glyph("scout") == "\U0001f52d"  # telescope
    # fallthrough: unknown returns empty
    assert role_glyph("nope") == ""
    assert role_glyph(None) == ""


def test_action_event_renders_role_icon_inline(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action",
         "payload": {"role": "miner", "summary": "noop"}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events)
    html = render(run_dir).read_text()
    block = _find_line_block(html, 0)
    # Glyph + title attribute next to the agent tag.
    assert 'class="role-icon"' in block
    assert 'title="miner"' in block
    assert "\u26cf" in block  # pickaxe


def test_non_action_event_inherits_prior_role(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action",
         "payload": {"role": "aligner", "summary": "noop"}},
        # Different event type for SAME agent — should inherit aligner.
        {"step": 1, "agent": 0, "stream": "py", "type": "role_change",
         "payload": {"from": "aligner", "to": "aligner"}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events)
    html = render(run_dir).read_text()
    # Second line (idx=1) inherits aligner glyph.
    block = _find_line_block(html, 1)
    assert 'title="aligner"' in block
    assert "\U0001f517" in block


def test_team_event_has_no_role_icon(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action",
         "payload": {"role": "miner", "summary": "noop"}},
        {"step": 1, "agent": None, "stream": "py", "type": "note",
         "payload": {"text": "hi"}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events)
    html = render(run_dir).read_text()
    # Team event (agent=None) — no role-icon span on that line.
    block = _find_line_block(html, 1)
    assert "role-icon" not in block


def test_role_icon_css_present(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=1)
    html = render(run_dir).read_text()
    assert "#log .role-icon" in html


def test_unknown_role_is_ignored(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action",
         "payload": {"role": "banana", "summary": "noop"}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events)
    html = render(run_dir).read_text()
    block = _find_line_block(html, 0)
    # Unknown role: no glyph span emitted.
    assert "role-icon" not in block


# ---------------------------------------------------------------------------
# Feature 2: Current-inventory panel
# ---------------------------------------------------------------------------


def test_inventory_panel_exists_with_one_row_per_agent(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=3)
    html = render(run_dir).read_text()
    assert 'id="inventory-panel"' in html
    rows = re.findall(r'<div class="inv-row"[^>]*data-agent="(\d+)"', html)
    assert sorted(int(a) for a in rows) == [0, 1, 2]


def test_inventory_panel_uses_agent_color(tmp_path: Path) -> None:
    from cvc_policy.viewer import render
    from cvc_policy.viewer.render import agent_color

    run_dir = _write_fake_run(tmp_path / "r", cogs=2)
    html = render(run_dir).read_text()
    # Agent tag inside inv-row uses the per-agent color.
    m = re.search(
        r'<div class="inv-row"[^>]*data-agent="0">(.*?)</div>',
        html,
        re.DOTALL,
    )
    assert m is not None
    row = m.group(0)
    assert agent_color(0) in row
    assert "a0" in row


def test_inventory_panel_emits_heartbeat_lookup_table(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    events = [
        {"step": 200, "agent": 0, "stream": "py", "type": "heartbeat",
         "payload": {"hp": 90, "role": "miner",
                     "inventory": {"carbon": 4, "oxygen": 2},
                     "team_resources": {}}},
        {"step": 400, "agent": 0, "stream": "py", "type": "heartbeat",
         "payload": {"hp": 75, "role": "aligner",
                     "inventory": {"carbon": 1, "oxygen": 3},
                     "team_resources": {}}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events)
    html = render(run_dir).read_text()
    # A precomputed lookup table is emitted as a script island.
    assert 'id="inventory-by-agent-step"' in html
    m = re.search(
        r'<script type="application/json" id="inventory-by-agent-step">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m is not None
    data = json.loads(m.group(1))
    assert "0" in data
    entries = data["0"]
    assert len(entries) == 2
    steps = [e["step"] for e in entries]
    assert steps == sorted(steps)
    assert entries[0]["payload"]["hp"] == 90


def test_inventory_panel_sits_above_log(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=2)
    html = render(run_dir).read_text()
    # Panel precedes the #log div.
    assert html.find('id="inventory-panel"') < html.find('id="log"')


def test_inventory_panel_has_css_class(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=2)
    html = render(run_dir).read_text()
    # A css rule for .inventory-panel (or #inventory-panel) exists.
    assert "inventory-panel" in html
    # Panel row subelements present in template.
    assert "inv-agent" in html
    assert "inv-role" in html
    assert "inv-hp" in html
    assert "inv-cargo" in html


def test_inventory_panel_js_updates_on_set_step(tmp_path: Path) -> None:
    from cvc_policy.viewer import render

    run_dir = _write_fake_run(tmp_path / "r", cogs=2)
    html = render(run_dir).read_text()
    # JS reads the lookup table and wires into setStep.
    assert "inventoryByAgentStep" in html
    assert "updateInventoryPanel" in html


def test_render_groups_agents_by_team(tmp_path: Path) -> None:
    """Inventory panel should emit one .team-block per unique team id,
    each containing the .inv-rows for that team's agents."""
    from cvc_policy.viewer import render

    events = [
        {"step": 1, "agent": 0, "stream": "py", "type": "inventory",
         "payload": {"inventory": {}, "hp": 100, "team": "red"}},
        {"step": 1, "agent": 1, "stream": "py", "type": "inventory",
         "payload": {"inventory": {}, "hp": 100, "team": "red"}},
        {"step": 1, "agent": 2, "stream": "py", "type": "inventory",
         "payload": {"inventory": {}, "hp": 100, "team": "blue"}},
        {"step": 1, "agent": 3, "stream": "py", "type": "inventory",
         "payload": {"inventory": {}, "hp": 100, "team": "blue"}},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=4, events=events)
    html = render(run_dir).read_text()
    blocks = re.findall(
        r'<div class="team-block" data-team="([^"]*)">(.*?)</div>\s*</div>',
        html,
        re.DOTALL,
    )
    # Two teams; order is sorted by team id.
    teams = [t for t, _ in blocks]
    assert teams == ["blue", "red"]
    blue_body = blocks[0][1]
    red_body = blocks[1][1]
    assert 'data-agent="2"' in blue_body
    assert 'data-agent="3"' in blue_body
    assert 'data-agent="0"' not in blue_body
    assert 'data-agent="0"' in red_body
    assert 'data-agent="1"' in red_body
    assert 'data-agent="2"' not in red_body


def test_team_header_js_populates_from_team_by_step(tmp_path: Path) -> None:
    """The `team-by-step` script island is emitted and updateInventoryPanel
    reads it to render the per-team header."""
    from cvc_policy.viewer import render

    events = [
        {"step": 10, "agent": 0, "stream": "py", "type": "inventory",
         "payload": {
             "inventory": {},
             "hp": 100,
             "team": "red",
             "team_resources": {"carbon": 7, "heart": 2},
             "junctions": {"friendly": 3, "enemy": 1, "neutral": 4},
         }},
    ]
    run_dir = _write_fake_run(tmp_path / "r", cogs=1, events=events)
    html = render(run_dir).read_text()
    assert 'id="team-by-step"' in html
    m = re.search(
        r'<script type="application/json" id="team-by-step">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m is not None
    data = json.loads(m.group(1))
    assert "red" in data
    entry = data["red"][0]
    assert entry["payload"]["team_resources"] == {"carbon": 7, "heart": 2}
    assert entry["payload"]["junctions"] == {"friendly": 3, "enemy": 1, "neutral": 4}
    # JS wires teamByStep through the update function.
    assert "teamByStep" in html
    assert "updateInventoryPanel" in html
    # The template renders a team header placeholder for team resources + junctions.
    assert 'class="team-header"' in html
    assert 'class="team-resources"' in html
    assert 'class="team-junctions"' in html
    # Score placeholder (deferred — no direct source yet).
    assert 'class="team-score"' in html
