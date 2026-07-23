"""The fog of war: what one observer actually saw before it voted.

Panels are Playing phases (derived from phase events — Playing phase 1 does
not start at tick 0; Lobby/GameInfo/RoleReveal precede it), stacked
vertically at full canvas width because the map is wide and thin
(side-by-side panels waste most of the pixels). The backdrop sits under a
near-black veil: **black means the observer had no information there**.
The observer's own path draws in its player color over a white casing;
every other player appears only during ticks the observer had line of
sight, in that player's own color, with a dot at the last-seen position.

There is deliberately **no role encoding anywhere in the plot**: the
observer does not know who the imposters are, and painting ground truth
into a view of one agent's information state is a category error (it would
also collide with red-the-player). Ground truth goes in the footnote only —
this module never imports the role colors.

Under each map, a chip row names every player in the game: the observer
first (white-bordered — the viewpoint), then everyone else by ticks seen
descending. Players never seen render greyed with "never seen" rather than
being dropped; the absence is the information.

Caption limitation (also in the README): sightings are per-player
intervals, not a field-of-view polygon, so black means "no player was seen
here", not "this area was not visible."
"""

from __future__ import annotations

import io
import textwrap
from collections.abc import Sequence

import matplotlib.pyplot as plt
import numpy as np
from episode_analysis.palette import EDGE, INK, MUTED, PAGE, SECONDARY, SURFACE, world_axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from ..events import Episode, PlayerTrack
from ..palette import lifted_player_color
from .missed_blend import _runs

__all__ = ["build_fog_of_war", "render_fog_of_war"]

_VEIL_COLOR = "#07090c"
_VEIL_ALPHA = 0.86
_TICKS_PER_SECOND = 24


def _color(ep: Episode, slot: int) -> str:
    player = ep.players.get(slot)
    if player is not None and player.color:
        return lifted_player_color(player.color)
    return SECONDARY


def _draw_panel(
    ax,
    ep: Episode,
    observer: int,
    span: tuple[int, int],
    number: int,
    map_image,
) -> dict[int, int]:
    """Draw one Playing-phase map panel; returns other-player ticks seen."""
    t0, t1 = span
    ax.set_aspect("equal")
    world_axes(ax, ep.map_w, ep.map_h, background=map_image)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.add_patch(
        Rectangle((0, 0), ep.map_w, ep.map_h, facecolor=_VEIL_COLOR, alpha=_VEIL_ALPHA,
                  lw=0, zorder=1)
    )

    obs_color = _color(ep, observer)
    track = ep.tracks.get(observer)
    obs_mask = (
        track.window(t0, t1 - 1) & track.playing_alive()
        if track is not None
        else np.zeros(0, dtype=bool)
    )
    if track is not None and obs_mask.any():
        for run in _runs(track.ticks, obs_mask, ep.snapshot_stride):
            ax.plot(track.x[run], track.y[run], color=INK, lw=7, alpha=0.10, zorder=2)
            ax.plot(track.x[run], track.y[run], color=INK, lw=3.0, alpha=0.55, zorder=3)
            ax.plot(track.x[run], track.y[run], color=obs_color, lw=1.6, zorder=4)
        first = np.nonzero(obs_mask)[0][0]
        ax.plot(track.x[first], track.y[first], marker="o", ms=7, mfc="none",
                mec=obs_color, mew=1.5, zorder=5)
    else:
        ax.text(0.5, 0.5, "observer dead this phase", transform=ax.transAxes,
                ha="center", va="center", color=MUTED, fontsize=9, zorder=6)

    seen_ticks: dict[int, int] = {}
    last_seen: dict[int, tuple[int, float, float]] = {}
    for s in ep.sightings:
        if s.observer != observer or s.target_kind != "player" or s.target == observer:
            continue
        lo, hi = max(t0, s.tick_start), min(t1 - 1, s.tick_end)
        if lo > hi:
            continue
        seen_ticks[s.target] = seen_ticks.get(s.target, 0) + (hi - lo + 1)
        other: PlayerTrack | None = ep.tracks.get(s.target)
        candidate = (hi, float(s.x), float(s.y))
        if other is not None:
            window = other.window(lo, hi)
            for run in _runs(other.ticks, window, ep.snapshot_stride):
                ax.plot(other.x[run], other.y[run], color=_color(ep, s.target), lw=1.4, zorder=4)
            idx = np.nonzero(window)[0]
            if idx.size:
                last = idx[-1]
                candidate = (int(other.ticks[last]), float(other.x[last]), float(other.y[last]))
        if s.target not in last_seen or candidate[0] >= last_seen[s.target][0]:
            last_seen[s.target] = candidate

    if last_seen:
        slots = sorted(last_seen)
        ax.scatter(
            [last_seen[s][1] for s in slots],
            [last_seen[s][2] for s in slots],
            c=[_color(ep, s) for s in slots],
            edgecolors=EDGE, marker="o", s=24, lw=0.8, zorder=5,
        )

    ax.text(0.012, 0.965, f"Playing phase {number}", transform=ax.transAxes,
            va="top", color=INK, fontsize=11, zorder=6)
    return seen_ticks


def _draw_chips(ax, ep: Episode, observer: int, seen_ticks: dict[int, int]) -> None:
    """One chip per seated player: observer first, then by ticks seen."""
    n = len(ep.players)
    ax.set_axis_off()
    ax.set_xlim(0, n + 2.2)
    ax.set_ylim(0, 1)
    others = [s for s in sorted(ep.players) if s != observer]
    seen_count = sum(seen_ticks.get(s, 0) > 0 for s in others)
    ax.text(0.05, 0.5, f"{seen_count} of {len(others)} seen", va="center",
            color=SECONDARY, fontsize=8)

    ordered = [observer] + sorted(others, key=lambda s: (-seen_ticks.get(s, 0), s))
    for i, slot in enumerate(ordered):
        x = 1.8 + i * 1.0
        name = ep.players[slot].color or f"slot {slot}"
        if slot == observer:
            ax.add_patch(Rectangle((x - 0.08, 0.14), 0.92, 0.72, facecolor=SURFACE,
                                   edgecolor=INK, lw=1.0, zorder=1))
            swatch_color, text, text_color = _color(ep, slot), f"{name} · observer", SECONDARY
        elif seen_ticks.get(slot, 0) > 0:
            seconds = seen_ticks[slot] / _TICKS_PER_SECOND
            swatch_color, text, text_color = _color(ep, slot), f"{name} · {seconds:.0f}s", SECONDARY
        else:
            swatch_color, text, text_color = MUTED, f"{name} · never seen", MUTED
        ax.add_patch(Rectangle((x, 0.30), 0.14, 0.40, facecolor=swatch_color, lw=0, zorder=2))
        ax.text(x + 0.20, 0.5, text, va="center", color=text_color, fontsize=7)


def build_fog_of_war(
    ep: Episode,
    observer: int,
    *,
    phases: Sequence[int] | None = None,
    map_image=None,
) -> Figure:
    """Build the stacked fog-of-war figure for ``observer``.

    ``phases`` are 1-based Playing phase numbers (default: the first two
    that exist)."""
    if observer not in ep.players:
        raise ValueError(
            f"unknown observer slot {observer}; seats: {sorted(ep.players)}"
        )
    if not ep.playing_spans:
        raise ValueError(f"{ep.episode_id}: no Playing phases to render")
    if phases is None:
        phases = list(range(1, min(2, len(ep.playing_spans)) + 1))
    for p in phases:
        if not 1 <= p <= len(ep.playing_spans):
            raise ValueError(
                f"Playing phase {p} does not exist; episode has {len(ep.playing_spans)}"
            )

    n = len(phases)
    fig_w = 12.5
    ax_x0, ax_w_frac = 0.02, 0.96
    map_h_in = fig_w * ax_w_frac * ep.map_h / ep.map_w
    chip_in, inner_in, gap_in, top_in, footer_in = 0.55, 0.10, 0.30, 0.12, 0.60
    fig_h = top_in + n * (map_h_in + inner_in + chip_in) + (n - 1) * gap_in + footer_in
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=PAGE)

    cursor = fig_h - top_in
    for p in phases:
        map_ax = fig.add_axes((ax_x0, (cursor - map_h_in) / fig_h, ax_w_frac, map_h_in / fig_h))
        seen = _draw_panel(map_ax, ep, observer, ep.playing_spans[p - 1], p, map_image)
        cursor -= map_h_in + inner_in
        chip_ax = fig.add_axes((ax_x0, (cursor - chip_in) / fig_h, ax_w_frac, chip_in / fig_h))
        _draw_chips(chip_ax, ep, observer, seen)
        cursor -= chip_in + gap_in

    imposters = [ep.players[s].label for s in ep.imposters]
    footnote = (
        "black means no player was seen here, not \"this area was not visible\": sightings are "
        "per-player line-of-sight intervals, not a field-of-view polygon. "
        f"ground truth (not encoded above): imposter{'s' if len(imposters) != 1 else ''} "
        f"{', '.join(imposters) or 'unknown'}."
    )
    fig.text(ax_x0, (footer_in - 0.14) / fig_h, "\n".join(textwrap.wrap(footnote, 110)),
             ha="left", va="top", color=MUTED, fontsize=7, linespacing=1.5)
    return fig


def render_fog_of_war(
    ep: Episode,
    observer: int,
    *,
    phases: Sequence[int] | None = None,
    map_image=None,
    dpi: int = 130,
) -> bytes:
    """Render the fog-of-war figure to PNG bytes."""
    fig = build_fog_of_war(ep, observer, phases=phases, map_image=map_image)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=PAGE, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return buf.getvalue()
