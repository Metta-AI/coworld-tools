"""Phase 5 tests: HTML polish (palette, swatches, ghost glyph, sparkline).

Phase 5 is purely visual — the data already lives in `stats.json`
(per phases 2-4). This test file asserts the new visual contract:
- Every slot row carries a color swatch keyed to the slot's color.
- `likely_dead` slots get a ghost glyph in their outcome cell.
- Each scoreboard row has a per-slot activity sparkline SVG with
  one rect per dense bucket.
- The 16-entry palette mapping `PLAYER_COLOR_NAMES` → CSS hex codes
  is reachable from the HTML (the swatch's inline-style color
  matches the palette).
- Self-containment guarantees still hold (no <script>, no <link>).
- The page parses as well-formed HTML via stdlib `html.parser`.

The existing phase-2 verdict-ribbon and self-containment tests stay
authoritative; this file only covers the phase-5 additions.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from html.parser import HTMLParser
from typing import Any

import among_them_summarizer as ats
import fixtures
from test_phase4 import _make_replay_with_inputs


# ---------- helpers ----------


def _build_zip(
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay_bytes: bytes | None = None,
) -> bytes:
    return ats.build_zip_bytes(
        results=ats.AmongThemResults.model_validate(
            results or fixtures.make_results_crewmate_win()
        ),
        metadata=ats.EpisodeMetadata.model_validate(
            metadata or fixtures.make_metadata()
        ),
        replay_bytes=replay_bytes
        if replay_bytes is not None
        else fixtures.make_replay_bytes(),
    )


def _html_from(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return zf.read("summary.html").decode("utf-8")


class _WellFormednessParser(HTMLParser):
    """Verifies every open tag has a matching close (excluding void
    elements like <br>, <meta>, <rect>, etc.). Self-closing SVG
    elements parse fine in HTML5 even without explicit `/>`."""

    _VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
        # SVG primitives our renderer emits without explicit close tags.
        "rect",
        "path",
        "circle",
        "line",
    }

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._VOID:
            return
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._VOID:
            return
        if not self.stack:
            self.errors.append(f"closing </{tag}> with empty stack")
            return
        # Pop until match or empty; tolerate optional-end-tag elements (e.g. <p>).
        if self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            # Implicit closes in between are allowed by HTML5; pop to the match.
            while self.stack and self.stack[-1] != tag:
                self.stack.pop()
            if self.stack:
                self.stack.pop()
        else:
            self.errors.append(f"unmatched </{tag}> (stack: {self.stack})")


# ---------- well-formedness + self-containment ----------


def test_summary_html_parses_as_well_formed_html() -> None:
    html = _html_from(_build_zip(replay_bytes=_make_replay_with_inputs(slots=8)))
    parser = _WellFormednessParser()
    parser.feed(html)
    assert not parser.errors, parser.errors


def test_summary_html_stays_self_contained() -> None:
    html = _html_from(_build_zip())
    assert "<script" not in html.lower()
    assert "<link" not in html.lower()
    # Phase 5 still inlines CSS only.
    assert "<style" in html.lower()


# ---------- color palette ----------


def test_palette_has_sixteen_entries_aligned_with_color_names() -> None:
    assert len(ats.AMONG_THEM_COLORS) == len(ats.PLAYER_COLOR_NAMES) == 16
    # Every color name has a hex entry and every entry is a valid
    # 7-character #RRGGBB string.
    for name in ats.PLAYER_COLOR_NAMES:
        assert name in ats.AMONG_THEM_COLORS, name
    for name, hex_code in ats.AMONG_THEM_COLORS.items():
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", hex_code), (name, hex_code)


def test_swatch_hex_matches_slot_color_palette() -> None:
    """The inline-style fill on each scoreboard swatch matches
    `AMONG_THEM_COLORS[slot.color_name]`."""
    html = _html_from(_build_zip(replay_bytes=_make_replay_with_inputs(slots=8)))
    # Default 8 slots, no config.slots[].color → positional palette.
    for i in range(8):
        name = ats.PLAYER_COLOR_NAMES[i]
        hex_code = ats.AMONG_THEM_COLORS[name]
        assert hex_code.lower() in html.lower(), f"missing {name} ({hex_code})"


def test_swatch_count_equals_slot_count() -> None:
    html = _html_from(_build_zip(replay_bytes=_make_replay_with_inputs(slots=8)))
    # One `class="swatch"` per scoreboard row.
    assert html.count('class="swatch"') == 8


# ---------- ghost glyph for likely_dead ----------


def test_ghost_glyph_appears_only_for_likely_dead_slots() -> None:
    # Crewmate-win scenario; mutate two slots to lose individually
    # so they're flagged as likely_dead.
    results = fixtures.make_results_crewmate_win(slots=8)
    # Slots 0 and 1 are imposters by default; pick crewmate slots 2 and 3.
    results["win"][2] = False
    results["win"][3] = False
    html = _html_from(
        _build_zip(results=results, replay_bytes=_make_replay_with_inputs(slots=8))
    )
    # Each likely_dead slot gets one ghost glyph; non-likely-dead get none.
    count = html.count('class="ghost"')
    assert count == 2, f"expected 2 ghost glyphs (slots 2, 3), got {count}"


def test_no_ghost_glyph_when_no_one_likely_dead() -> None:
    # Imposter win — by the inference rule, only crewmates whose
    # team won would be flagged. Here imposters won, so no one is.
    html = _html_from(
        _build_zip(
            results=fixtures.make_results_imposter_win(),
            replay_bytes=_make_replay_with_inputs(slots=8),
        )
    )
    assert 'class="ghost"' not in html


# ---------- sparkline SVG ----------


def test_scoreboard_has_one_sparkline_svg_per_slot() -> None:
    html = _html_from(_build_zip(replay_bytes=_make_replay_with_inputs(slots=8)))
    # Sparkline svgs carry a marker class so the assertion doesn't
    # accidentally count the ghost glyph SVGs.
    assert html.count('class="sparkline"') == 8


def test_sparkline_emits_one_rect_per_dense_bucket() -> None:
    """The sparkline's rect count per slot equals the number of
    buckets in `stats.activity.buckets_per_slot[i].presses_per_bucket`."""
    replay_bytes = _make_replay_with_inputs(slots=2, last_tick=2400)
    payload = _build_zip(
        results=fixtures.make_results_crewmate_win(slots=2),
        metadata=fixtures.make_metadata(slots=2),
        replay_bytes=replay_bytes,
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
        html = zf.read("summary.html").decode("utf-8")
    n_buckets = len(stats["activity"]["buckets_per_slot"][0]["presses_per_bucket"])
    assert n_buckets > 1
    # Find each sparkline SVG block (one per slot) and count its <rect>s.
    sparklines = re.findall(
        r'<svg[^>]*class="sparkline".*?</svg>', html, flags=re.DOTALL
    )
    assert len(sparklines) == 2
    for spark in sparklines:
        rects = re.findall(r"<rect\b", spark)
        assert len(rects) == n_buckets


def test_sparkline_dims_buckets_outside_player_presence() -> None:
    """A leave mid-episode dims (lower opacity) the buckets after the
    leave tick. Implementation marker: post-leave rects carry the
    `bar-absent` class while present-window rects carry `bar-present`.
    """
    replay_bytes = fixtures.make_typical_replay_bytes(
        slots=8, last_tick=2400, leave_player=4, leave_time_ms=10_000
    )
    payload = _build_zip(replay_bytes=replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        html = zf.read("summary.html").decode("utf-8")
    # The slot 4 sparkline must contain at least one absent-window rect.
    # Lift the slot-4 sparkline by anchoring on the slot's `data-slot="4"`
    # attribute we emit.
    m = re.search(
        r'<svg[^>]*class="sparkline"[^>]*data-slot="4".*?</svg>',
        html,
        flags=re.DOTALL,
    )
    assert m is not None, "couldn't isolate slot 4's sparkline"
    spark = m.group(0)
    assert 'class="bar-absent"' in spark
    assert 'class="bar-present"' in spark


# ---------- footer + meetings footnote ----------


def test_meetings_note_links_to_design() -> None:
    """The meetings card's footnote mentions DESIGN.md so a reader can
    discover the friction discussion behind the 'estimated' label."""
    html = _html_from(_build_zip())
    assert "DESIGN.md" in html


def test_footer_carries_episode_and_reporter_ids() -> None:
    html = _html_from(_build_zip(metadata=fixtures.make_metadata(episode_id="ep_xyz")))
    assert "ep_xyz" in html
