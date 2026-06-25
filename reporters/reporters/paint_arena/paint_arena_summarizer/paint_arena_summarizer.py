"""PaintArena summarizer reporter.

Pure function of the episode bundle (results JSON + replay JSON + optional
metadata, behind one COGAME_EPISODE_BUNDLE_URI). Produces a zip containing
a self-contained HTML summary, a JSON stats blob, and a Parquet event log,
per the canonical Coworld reporter contract: a top-level `manifest.json`
inside the zip flags `render` (the HTML) and `event_log` (the Parquet) for
downstream consumers. The HTML embeds final scores, a final-grid SVG
heatmap, and a curated set of "back-and-forth" highlights derived from the
replay's per-frame tile-owner deltas. The Parquet uses the shared
(ts, player, key, value) event-log schema and lists every tick where any
pair of slots was in close proximity.

See DESIGN.md for the full specification. Grid dimensions and frames come
from the game-owned replay; PaintArena's replay format is defined by its
game server in coworld.

Shared primitives (`BundleReader`, `ReporterInputs`, `read_uri` /
`write_uri`, `write_deterministic_zip`, `EVENT_LOG_SCHEMA`, the output
`manifest.json` writer) live in the shared `reporter_sdk` package and
are re-exported below so test code referencing this module's attributes
continues to work.
"""

from __future__ import annotations

# `time` and `requests` are intentionally imported (and used by the SDK
# at module-singleton level) so test code can `monkeypatch.setattr(par.time,
# "sleep", ...)` and `monkeypatch.setattr(par.requests, "request", ...)`
# without reaching into the SDK module.
import json
import sys
import time  # noqa: F401  (re-exported for monkeypatching)
from collections import defaultdict
from html import escape as html_escape
from typing import Any

import requests  # noqa: F401  (re-exported for monkeypatching)
from pydantic import BaseModel, Field, NonNegativeInt

from reporter_sdk import (
    EVENT_LOG_SCHEMA,
    BundleInnerManifest,
    BundleReader,
    OutputManifest,
    ReporterInputs,
    build_report_zip,
    load_reporter_inputs,
    read_json,
    read_uri,
    stable_json,
    write_deterministic_zip,
    write_events_parquet,
    write_uri,
)
# Re-exported for the test suite, which references `par._HTTP_MAX_ATTEMPTS`.
from reporter_sdk.io import _HTTP_MAX_ATTEMPTS  # noqa: F401

# Public re-exports — tests import these as attributes of this module.
__all__ = [
    "EVENT_LOG_SCHEMA",
    "BundleInnerManifest",
    "BundleReader",
    "OutputManifest",
    "ReporterInputs",
    "build_report_zip",
    "load_reporter_inputs",
    "read_json",
    "read_uri",
    "stable_json",
    "write_deterministic_zip",
    "write_events_parquet",
    "write_uri",
]

# The reporter's self-identifying id, stamped into the output zip's
# `manifest.json` `reporter_id` field. Conventionally matches the runnable's
# `id` in `manifest.reporter[]`.
REPORTER_ID = "paint-arena-summarizer"


# ---------- PaintArena-specific input/output types ----------


class PaintArenaResults(BaseModel):
    scores: list[float]
    painted_tiles: list[NonNegativeInt]
    ticks: NonNegativeInt


class PlayerMetadata(BaseModel):
    slot: int
    policy_name: str | None = None


class EpisodeMetadata(BaseModel):
    """Episode-level metadata used to populate `stats.json` and the HTML
    header. The canonical reporter contract (metta `docs/roles/reporter.md`)
    does not formally carry these fields in the bundle's inner `manifest.json`;
    in practice they reach the reporter via the bundle's optional `metadata`
    token. When that token is absent, every field falls back to a default."""

    episode_id: str | None = None
    variant_id: str = "unknown"
    duration_seconds: float | None = None
    players: list[PlayerMetadata] = []


class ReplayConfig(BaseModel):
    # Subset of the PaintArena replay's `config` dict that this reporter
    # consumes. Other config fields (max_ticks, tick_rate, players, ...) are
    # ignored. See packages/coworld/.../paintarena/game/server.py::_replay_payload.
    width: int
    height: int


class PaintArenaFrame(BaseModel):
    # Subset of a PaintArena snapshot. Other fields (player_names, scores,
    # started, paused, ...) are ignored by this reporter; the reporter
    # reconstructs scores from tile_owners.
    tick: int
    positions: list[list[int]]
    tile_owners: list[int]


class PaintArenaReplay(BaseModel):
    # Subset of the PaintArena replay payload. Other top-level fields
    # (player_names, results) are ignored by this reporter.
    config: ReplayConfig
    frames: list[PaintArenaFrame] = Field(default_factory=list)


class SlotStats(BaseModel):
    slot: int
    policy_name: str
    painted_tiles: int
    share_pct: float


class GridStats(BaseModel):
    width: int
    height: int
    total_tiles: int


class Highlight(BaseModel):
    """A contested tile: ownership flipped between distinct painted slots
    `flips` times within a sliding window ending at `tick_end`."""

    x: int
    y: int
    tick_start: int
    tick_end: int
    flips: int
    slots: list[int]  # distinct slots involved in the flips, sorted ascending


class PaintArenaStats(BaseModel):
    episode_id: str | None
    variant_id: str
    grid: GridStats
    ticks: int
    duration_seconds: float | None
    slots: list[SlotStats]
    unpainted_tiles: int
    unpainted_share_pct: float
    winner_slot: int | None
    margin_tiles: int
    tie: bool
    proximity_event_count: int
    highlights: list[Highlight]


# ---------- frame-walking extractors ----------

PROXIMITY_THRESHOLD = 2  # Chebyshev (king-move) distance; tuned for a small grid.
HIGHLIGHT_MIN_FLIPS = 2  # painted->painted re-paints within the window
HIGHLIGHT_WINDOW_TICKS = 10
HIGHLIGHT_MAX_RESULTS = 5


def _owner_at(owners: list[int], x: int, y: int, width: int) -> int:
    idx = y * width + x
    if 0 <= idx < len(owners):
        return owners[idx]
    return -1


def extract_tile_flips(
    frames: list[PaintArenaFrame],
    *,
    width: int,
) -> list[dict[str, Any]]:
    """Walk consecutive frames; emit a flip for every tile whose owner changed
    from one *painted* slot to a *different painted* slot. First-time paints
    (-1 → slot) are excluded — they're not "back and forth," they're the
    initial brush stroke. The flip list is in tick-ascending order.
    """
    flips: list[dict[str, Any]] = []
    if len(frames) < 2:
        return flips
    prev_owners = frames[0].tile_owners
    for frame in frames[1:]:
        cur_owners = frame.tile_owners
        for idx, (prev, cur) in enumerate(zip(prev_owners, cur_owners)):
            if prev != cur and prev >= 0 and cur >= 0:
                flips.append(
                    {
                        "tick": frame.tick,
                        "x": idx % width,
                        "y": idx // width,
                        "prev_owner": prev,
                        "new_owner": cur,
                    }
                )
        prev_owners = cur_owners
    return flips


def detect_back_and_forth_highlights(
    tile_flips: list[dict[str, Any]],
    *,
    min_flips: int = HIGHLIGHT_MIN_FLIPS,
    window_ticks: int = HIGHLIGHT_WINDOW_TICKS,
    max_results: int = HIGHLIGHT_MAX_RESULTS,
) -> list[Highlight]:
    """Find tiles that flipped ≥`min_flips` times within any `window_ticks`
    sliding window. Returns the top-`max_results` highlights ordered by
    flip-count descending, then earliest first. At most one highlight per
    distinct tile (the highest-flip window for that tile)."""
    by_tile: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for flip in tile_flips:
        by_tile[(flip["x"], flip["y"])].append(flip)

    best_per_tile: dict[tuple[int, int], Highlight] = {}
    for (x, y), flips in by_tile.items():
        # Walk windows: anchor at i, extend j while flips[j].tick - flips[i].tick <= window_ticks.
        for i in range(len(flips)):
            j = i
            while j + 1 < len(flips) and flips[j + 1]["tick"] - flips[i]["tick"] <= window_ticks:
                j += 1
            count = j - i + 1
            if count < min_flips:
                continue
            window = flips[i : j + 1]
            slot_set: set[int] = set()
            for f in window:
                slot_set.add(f["prev_owner"])
                slot_set.add(f["new_owner"])
            hl = Highlight(
                x=x,
                y=y,
                tick_start=window[0]["tick"],
                tick_end=window[-1]["tick"],
                flips=count,
                slots=sorted(slot_set),
            )
            cur = best_per_tile.get((x, y))
            if cur is None or (hl.flips, -hl.tick_start) > (cur.flips, -cur.tick_start):
                best_per_tile[(x, y)] = hl

    return sorted(
        best_per_tile.values(),
        key=lambda h: (-h.flips, h.tick_start, h.x, h.y),
    )[:max_results]


def build_proximity_rows(
    frames: list[PaintArenaFrame],
    *,
    width: int,
    threshold: int = PROXIMITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """One row per (tick, unordered slot-pair) within `threshold` Chebyshev
    distance. Width is required for the tile-owner lookups so the flat
    tile_owners array can be indexed as owners[y*width + x]."""
    rows: list[dict[str, Any]] = []
    for frame in frames:
        positions = frame.positions
        n = len(positions)
        if n < 2:
            continue
        owners = frame.tile_owners
        for i in range(n):
            xi, yi = positions[i]
            for j in range(i + 1, n):
                xj, yj = positions[j]
                dx = abs(xi - xj)
                dy = abs(yi - yj)
                d = dx if dx > dy else dy
                if d > threshold:
                    continue
                rows.append(
                    {
                        "tick": frame.tick,
                        "slot_a": i,
                        "slot_b": j,
                        "pos_a": [xi, yi],
                        "pos_b": [xj, yj],
                        "chebyshev_distance": d,
                        "tile_owner_a": _owner_at(owners, xi, yi, width),
                        "tile_owner_b": _owner_at(owners, xj, yj, width),
                    }
                )
    return rows


# ---------- aggregate stats ----------


def build_stats(
    results: PaintArenaResults,
    metadata: EpisodeMetadata,
    config: ReplayConfig,
    *,
    proximity_event_count: int,
    highlights: list[Highlight],
) -> PaintArenaStats:
    width = config.width
    height = config.height
    total_tiles = width * height

    policy_by_slot = {p.slot: p.policy_name for p in metadata.players if p.policy_name}
    slots = [
        SlotStats(
            slot=i,
            policy_name=policy_by_slot.get(i) or f"Slot {i}",
            painted_tiles=count,
            share_pct=round(count / total_tiles * 100.0, 2) if total_tiles > 0 else 0.0,
        )
        for i, count in enumerate(results.painted_tiles)
    ]

    total_painted = sum(results.painted_tiles)
    unpainted = max(total_tiles - total_painted, 0)
    unpainted_share = round(unpainted / total_tiles * 100.0, 2) if total_tiles > 0 else 0.0

    if total_painted == 0:
        winner_slot: int | None = None
        margin = 0
        tie = False
    else:
        max_count = max(results.painted_tiles)
        leaders = [i for i, c in enumerate(results.painted_tiles) if c == max_count]
        if len(leaders) > 1:
            winner_slot = None
            margin = 0
            tie = True
        else:
            winner_slot = leaders[0]
            others = [c for i, c in enumerate(results.painted_tiles) if i != winner_slot]
            margin = max_count - max(others) if others else max_count
            tie = False

    return PaintArenaStats(
        episode_id=metadata.episode_id,
        variant_id=metadata.variant_id,
        grid=GridStats(width=width, height=height, total_tiles=total_tiles),
        ticks=results.ticks,
        duration_seconds=metadata.duration_seconds,
        slots=slots,
        unpainted_tiles=unpainted,
        unpainted_share_pct=unpainted_share,
        winner_slot=winner_slot,
        margin_tiles=margin,
        tie=tie,
        proximity_event_count=proximity_event_count,
        highlights=highlights,
    )


# ---------- event-log projection ----------


def build_event_log_rows(
    proximity_rows: list[dict[str, Any]],
    highlights: list[Highlight],
) -> list[dict[str, Any]]:
    """Project frame-derived events into the shared (ts, player, key, value)
    event-log schema. Both proximity events and highlights are pair/tile-level
    facts, so `player` is -1 (global) for every row.
    """
    rows: list[dict[str, Any]] = []
    for ev in proximity_rows:
        rows.append(
            {
                "ts": int(ev["tick"]),
                "player": -1,
                "key": "proximity",
                "value": stable_json(
                    {
                        "slot_a": ev["slot_a"],
                        "slot_b": ev["slot_b"],
                        "pos_a": ev["pos_a"],
                        "pos_b": ev["pos_b"],
                        "chebyshev_distance": ev["chebyshev_distance"],
                        "tile_owner_a": ev["tile_owner_a"],
                        "tile_owner_b": ev["tile_owner_b"],
                    }
                ),
            }
        )
    for h in highlights:
        rows.append(
            {
                "ts": int(h.tick_end),
                "player": -1,
                "key": "back_and_forth",
                "value": stable_json(
                    {
                        "x": h.x,
                        "y": h.y,
                        "tick_start": h.tick_start,
                        "tick_end": h.tick_end,
                        "flips": h.flips,
                        "slots": h.slots,
                    }
                ),
            }
        )
    return rows


# ---------- HTML renderer ----------

# Distinct colors for up to 5 slots (PaintArena's results_schema allows 1-4
# today; 5th is a cushion). Picked for accessible contrast against the
# unpainted tile color #e9ecef.
_SLOT_COLORS = [
    "#e63946",  # slot 0 — red
    "#2a9d8f",  # slot 1 — teal
    "#f4a261",  # slot 2 — orange
    "#6a4c93",  # slot 3 — purple
    "#e9c46a",  # slot 4 — yellow
]
_UNPAINTED_COLOR = "#e9ecef"


def _slot_color(slot: int) -> str:
    if slot < 0:
        return _UNPAINTED_COLOR
    return _SLOT_COLORS[slot % len(_SLOT_COLORS)]


def _final_tile_owners(replay: PaintArenaReplay, total_tiles: int) -> list[int]:
    """The last frame's `tile_owners`, or a fully-unpainted grid if the replay
    has no frames."""
    if replay.frames:
        owners = replay.frames[-1].tile_owners
        if len(owners) == total_tiles:
            return list(owners)
    return [-1] * total_tiles


def _render_grid_svg(
    owners: list[int],
    width: int,
    height: int,
    *,
    cell: int = 22,
    gap: int = 2,
) -> str:
    """A flat, gap-spaced grid of cells colored by owner. Pure SVG, no JS."""
    svg_w = width * cell + (width + 1) * gap
    svg_h = height * cell + (height + 1) * gap
    parts = [
        f'<svg viewBox="0 0 {svg_w} {svg_h}" role="img" aria-label="final grid heatmap" '
        f'xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="{svg_w}" height="{svg_h}" fill="#f8f9fa" rx="6"/>',
    ]
    for y in range(height):
        for x in range(width):
            owner = owners[y * width + x]
            color = _slot_color(owner)
            cx = gap + x * (cell + gap)
            cy = gap + y * (cell + gap)
            parts.append(
                f'<rect x="{cx}" y="{cy}" width="{cell}" height="{cell}" '
                f'rx="3" fill="{color}"/>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _render_highlight_mini(
    h: Highlight,
    owners: list[int],
    width: int,
    height: int,
) -> str:
    """A small grid focused on the contested tile, with a halo around it. The
    full final-state owners are shown faintly so the reader sees where on the
    board the contest happened."""
    cell = 12
    gap = 1
    svg_w = width * cell + (width + 1) * gap
    svg_h = height * cell + (height + 1) * gap
    parts = [
        f'<svg viewBox="0 0 {svg_w} {svg_h}" role="img" '
        f'aria-label="contested tile location" xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="{svg_w}" height="{svg_h}" fill="#f8f9fa" rx="4"/>',
    ]
    for y in range(height):
        for x in range(width):
            owner = owners[y * width + x]
            color = _slot_color(owner)
            cx = gap + x * (cell + gap)
            cy = gap + y * (cell + gap)
            opacity = "1" if (x == h.x and y == h.y) else "0.45"
            parts.append(
                f'<rect x="{cx}" y="{cy}" width="{cell}" height="{cell}" '
                f'rx="2" fill="{color}" opacity="{opacity}"/>'
            )
    # Halo ring around the contested tile.
    hx = gap + h.x * (cell + gap) - 1
    hy = gap + h.y * (cell + gap) - 1
    parts.append(
        f'<rect x="{hx}" y="{hy}" width="{cell + 2}" height="{cell + 2}" '
        f'rx="3" fill="none" stroke="#212529" stroke-width="1.5"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _slot_swatch(slot: int) -> str:
    color = _slot_color(slot)
    return (
        f'<span class="swatch" style="background:{color}" aria-hidden="true"></span>'
    )


_HTML_CSS = """
:root { color-scheme: light; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f5f6f8;
  color: #212529;
  margin: 0;
  padding: 24px 16px 48px;
}
.wrap { max-width: 760px; margin: 0 auto; }
header { margin-bottom: 16px; }
h1 {
  font-size: 22px;
  font-weight: 600;
  margin: 0 0 4px;
}
.subtitle {
  color: #6c757d;
  font-size: 13px;
}
.card {
  background: white;
  border: 1px solid #e9ecef;
  border-radius: 10px;
  padding: 18px 20px;
  margin-bottom: 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}
.verdict {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.verdict .badge {
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  background: #f1f3f5;
  color: #495057;
  padding: 3px 8px;
  border-radius: 999px;
}
.verdict .headline {
  font-size: 18px;
  font-weight: 600;
}
.verdict .margin {
  color: #6c757d;
  font-size: 14px;
}
.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  vertical-align: middle;
  margin-right: 6px;
}
.heatmap { text-align: center; }
.heatmap svg { max-width: 100%; height: auto; }
table.scores {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
table.scores th, table.scores td {
  padding: 8px 6px;
  text-align: left;
  border-bottom: 1px solid #f1f3f5;
}
table.scores th {
  font-weight: 600;
  font-size: 12px;
  color: #6c757d;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
table.scores td.num { text-align: right; font-variant-numeric: tabular-nums; }
.bar {
  display: inline-block;
  vertical-align: middle;
  height: 8px;
  border-radius: 4px;
  min-width: 2px;
}
.bar-cell { width: 40%; }
h2 {
  font-size: 14px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #495057;
  margin: 0 0 10px;
}
.highlights {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.highlight {
  border: 1px solid #e9ecef;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fbfcfd;
  display: flex;
  gap: 10px;
  align-items: center;
}
.highlight .meta { font-size: 12px; color: #495057; line-height: 1.4; }
.highlight .meta strong { color: #212529; font-size: 13px; }
.empty { color: #6c757d; font-size: 13px; }
footer {
  margin-top: 24px;
  font-size: 11px;
  color: #adb5bd;
  text-align: center;
}
""".strip()


def render_summary_html(
    stats: PaintArenaStats,
    replay: PaintArenaReplay,
) -> str:
    grid = stats.grid
    duration = (
        f"{stats.duration_seconds:.1f} s ({stats.ticks} ticks)"
        if stats.duration_seconds is not None
        else f"{stats.ticks} ticks"
    )

    # Verdict band.
    if stats.winner_slot is None and stats.unpainted_tiles == grid.total_tiles:
        verdict_html = (
            '<span class="badge">No paint</span>'
            '<span class="headline">No tiles were painted</span>'
        )
    elif stats.tie:
        max_painted = max(s.painted_tiles for s in stats.slots)
        leaders = [s for s in stats.slots if s.painted_tiles == max_painted]
        names = ", ".join(html_escape(s.policy_name) for s in leaders)
        verdict_html = (
            '<span class="badge">Tie</span>'
            f'<span class="headline">Tied at {max_painted} tiles</span>'
            f'<span class="margin">{html_escape(names)}</span>'
        )
    else:
        winner = next(s for s in stats.slots if s.slot == stats.winner_slot)
        verdict_html = (
            f'<span class="badge">Winner</span>'
            f'<span class="headline">{_slot_swatch(winner.slot)}'
            f'Slot {winner.slot} &middot; {html_escape(winner.policy_name)}</span>'
            f'<span class="margin">by {stats.margin_tiles} tile'
            f'{"" if stats.margin_tiles == 1 else "s"}</span>'
        )

    # Score table with proportional bars.
    score_rows: list[str] = []
    for s in stats.slots:
        bar_pct = s.share_pct
        bar_html = (
            f'<span class="bar" style="width:{bar_pct:.1f}%;background:{_slot_color(s.slot)}"></span>'
        )
        score_rows.append(
            "<tr>"
            f"<td>{_slot_swatch(s.slot)}Slot {s.slot}</td>"
            f"<td>{html_escape(s.policy_name)}</td>"
            f'<td class="num">{s.painted_tiles} / {grid.total_tiles}</td>'
            f'<td class="num">{s.share_pct:.1f}%</td>'
            f'<td class="bar-cell">{bar_html}</td>'
            "</tr>"
        )
    score_rows.append(
        "<tr>"
        f"<td>{_slot_swatch(-1)}&mdash;</td>"
        "<td>unpainted</td>"
        f'<td class="num">{stats.unpainted_tiles} / {grid.total_tiles}</td>'
        f'<td class="num">{stats.unpainted_share_pct:.1f}%</td>'
        f'<td class="bar-cell"><span class="bar" style="width:{stats.unpainted_share_pct:.1f}%;'
        f'background:{_UNPAINTED_COLOR}"></span></td>'
        "</tr>"
    )

    final_owners = _final_tile_owners(replay, grid.total_tiles)
    heatmap = _render_grid_svg(final_owners, grid.width, grid.height)

    # Highlights.
    if stats.highlights:
        cards: list[str] = []
        slot_name = {s.slot: s.policy_name for s in stats.slots}
        for h in stats.highlights:
            mini = _render_highlight_mini(h, final_owners, grid.width, grid.height)
            slot_label = ", ".join(
                f"{_slot_swatch(s)}{html_escape(slot_name.get(s, f'Slot {s}'))}"
                for s in h.slots
            )
            tick_range = (
                f"tick {h.tick_start}"
                if h.tick_start == h.tick_end
                else f"ticks {h.tick_start}&ndash;{h.tick_end}"
            )
            cards.append(
                '<div class="highlight">'
                f"{mini}"
                '<div class="meta">'
                f"<strong>Tile ({h.x}, {h.y})</strong><br>"
                f"{h.flips} re-paints over {tick_range}<br>"
                f"{slot_label}"
                "</div>"
                "</div>"
            )
        highlights_html = '<div class="highlights">' + "".join(cards) + "</div>"
    else:
        highlights_html = (
            '<p class="empty">No back-and-forth moments detected '
            f"(threshold: {HIGHLIGHT_MIN_FLIPS}+ re-paints within {HIGHLIGHT_WINDOW_TICKS} ticks).</p>"
        )

    episode_label = stats.episode_id or "unknown"
    proximity_summary = (
        f"{stats.proximity_event_count} proximity event"
        f"{'' if stats.proximity_event_count == 1 else 's'} logged in proximity.parquet"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PaintArena &mdash; Episode {html_escape(episode_label)}</title>
<style>
{_HTML_CSS}
</style>
</head>
<body>
<div class="wrap">
<header>
<h1>PaintArena &mdash; Episode {html_escape(episode_label)}</h1>
<div class="subtitle">
Variant <strong>{html_escape(stats.variant_id)}</strong> &middot;
Grid {grid.width} &times; {grid.height} ({grid.total_tiles} tiles) &middot;
Duration {html_escape(duration)}
</div>
</header>

<section class="card">
<div class="verdict">{verdict_html}</div>
</section>

<section class="card heatmap">
<h2>Final grid</h2>
{heatmap}
</section>

<section class="card">
<h2>Tiles painted</h2>
<table class="scores">
<thead><tr><th>Slot</th><th>Policy</th><th class="num">Tiles</th><th class="num">Share</th><th></th></tr></thead>
<tbody>
{"".join(score_rows)}
</tbody>
</table>
</section>

<section class="card">
<h2>Back-and-forth highlights</h2>
{highlights_html}
</section>

<footer>{proximity_summary} &middot; full stats: <code>stats.json</code></footer>
</div>
</body>
</html>
"""


# ---------- zip assembly ----------


def build_zip_bytes(
    results: PaintArenaResults,
    metadata: EpisodeMetadata,
    replay: PaintArenaReplay,
) -> bytes:
    """Build the canonical output zip: a top-level `manifest.json` (flagging
    `summary.html` as `render` and `proximity.parquet` as `event_log`), the
    HTML render target, the auxiliary `stats.json`, and the event-log
    Parquet."""
    proximity_rows = build_proximity_rows(replay.frames, width=replay.config.width)
    tile_flips = extract_tile_flips(replay.frames, width=replay.config.width)
    highlights = detect_back_and_forth_highlights(tile_flips)

    stats = build_stats(
        results,
        metadata,
        replay.config,
        proximity_event_count=len(proximity_rows),
        highlights=highlights,
    )

    event_rows = build_event_log_rows(proximity_rows, highlights)

    summary_html = render_summary_html(stats, replay).encode("utf-8")
    stats_json = (json.dumps(stats.model_dump(), indent=2) + "\n").encode("utf-8")
    proximity_parquet = write_events_parquet(event_rows)

    return build_report_zip(
        OutputManifest(
            reporter_id=REPORTER_ID,
            render="summary.html",
            event_log="proximity.parquet",
        ),
        [
            ("summary.html", summary_html),
            ("stats.json", stats_json),
            ("proximity.parquet", proximity_parquet),
        ],
    )


# ---------- orchestration ----------


def run(inputs: ReporterInputs) -> None:
    with BundleReader(inputs.episode_bundle_uri) as bundle:
        inner = bundle.inner_manifest()
        if inner.status != "success":
            raise RuntimeError(
                f"bundle status={inner.status!r}; reporter cannot operate on "
                "a failed episode"
            )
        results = PaintArenaResults.model_validate(bundle.read_json("results"))
        replay = PaintArenaReplay.model_validate(bundle.read_json("replay"))
        metadata_raw: dict[str, Any] = bundle.read_json_optional("metadata") or {}
    metadata_raw.setdefault("episode_id", inner.ereq_id)
    metadata = EpisodeMetadata.model_validate(metadata_raw)
    payload = build_zip_bytes(results=results, metadata=metadata, replay=replay)
    write_uri(inputs.report_uri, payload, content_type="application/zip")
    print(
        f"[{REPORTER_ID}] wrote zip to {inputs.report_uri}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    run(load_reporter_inputs())
