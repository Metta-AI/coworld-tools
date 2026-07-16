"""Tests for the HTML assembly helpers and the dev CLI."""

from __future__ import annotations

import pytest

from episode_analysis.html import embed_png, page, section, table


def test_embed_png_data_uri():
    tag = embed_png(b"\x89PNG\r\n\x1a\nfake", alt='a "chart"')
    assert tag.startswith('<img src="data:image/png;base64,')
    assert "&quot;chart&quot;" in tag


def test_table_and_page_escape():
    t = table(["name", "score"], [["<agent>", 3], ["b&c", 4]])
    assert "&lt;agent&gt;" in t and "b&amp;c" in t
    doc = page("My <Title>", section("Sec & tion", "<p>ok</p>", t))
    assert doc.startswith("<!doctype html>")
    assert "My &lt;Title&gt;" in doc and "Sec &amp; tion" in doc
    assert "<p>ok</p>" in doc  # body fragments pass through unescaped


def test_cli_end_to_end(tmp_path):
    pytest.importorskip("matplotlib")
    import json

    from episode_analysis.cli import main
    from reporter_sdk.event_log import write_events_parquet  # workspace sibling

    rows = []
    for t in range(0, 40, 4):
        rows.append({"ts": t, "player": 0, "key": "position",
                     "value": json.dumps({"x": t % 10, "y": t % 7})})
    rows.append({"ts": 20, "player": 0, "key": "reward",
                 "value": json.dumps({"delta": 1.0, "total": 1.0})})
    rows.append({"ts": 30, "player": 0, "key": "death", "value": "{}"})
    events = tmp_path / "events.parquet"
    events.write_bytes(write_events_parquet(rows))

    out = tmp_path / "charts"
    assert main([str(events), "--out", str(out)]) == 0
    assert (out / "occupancy.png").exists()
    assert (out / "timeline.png").exists()


def test_cli_empty_log(tmp_path):
    pytest.importorskip("matplotlib")
    from episode_analysis.cli import main
    from reporter_sdk.event_log import write_events_parquet

    events = tmp_path / "empty.parquet"
    events.write_bytes(write_events_parquet([]))
    assert main([str(events), "--out", str(tmp_path)]) == 1
