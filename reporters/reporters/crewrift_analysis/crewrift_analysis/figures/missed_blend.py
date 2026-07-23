"""The missed-blend overlay: chances to look like crew, on the map.

For one player (typically an imposter), every run of ticks spent within
blend radius of a task station while **nobody had line of sight** is a
missed blend window — a moment the player could have stood at a station
and looked busy. Windows render as translucent amber discs, the only
saturated fill on the figure, over the player's path on a dimmed map.

Single-replay figure by design: one episode has a handful of kills and
tracks, so discrete marks and a trajectory read where a density surface
would be noise. The caption pairs the window count with this episode's
crew-mean station occupancy so the aggregate statistic becomes actionable.
"""

from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
from episode_analysis.palette import (
    ACCENT,
    INK,
    MUTED,
    NEGATIVE,
    PAGE,
    PORTAL_MARK,
    SECONDARY,
    STATION_MARK,
    world_axes,
)
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle

from ..events import CrewriftLogError, Episode
from ..metrics import station_occupancy
from ..palette import lifted_player_color

__all__ = ["BlendWindow", "build_missed_blend", "missed_blend_windows", "render_missed_blend"]

_DISC_RADIUS = 16.0  # px, drawing size of a window marker (not the blend radius)


@dataclass(frozen=True)
class BlendWindow:
    """One maximal run of near-station-and-unwatched ticks."""

    start: int
    end: int
    cx: float
    cy: float


def _runs(ticks: np.ndarray, mask: np.ndarray, stride: int) -> list[np.ndarray]:
    """Index arrays of maximal masked runs; a tick gap wider than the
    stride (a meeting, a death, a dropout) always breaks a run."""
    idx = np.nonzero(mask)[0]
    if idx.size == 0:
        return []
    breaks = np.nonzero(np.diff(ticks[idx]) > stride)[0] + 1
    return np.split(idx, breaks)


def missed_blend_windows(ep: Episode, slot: int, *, radius: float = 26.0) -> list[BlendWindow]:
    """All of ``slot``'s missed blend windows (living Playing ticks only)."""
    track = ep.tracks.get(slot)
    if track is None:
        raise CrewriftLogError(f"{ep.episode_id}: no track for slot {slot}")
    if not ep.tasks:
        return []
    stations = np.asarray(ep.tasks, dtype=float)
    dist = np.min(
        np.hypot(track.x[:, None] - stations[:, 0], track.y[:, None] - stations[:, 1]), axis=1
    )
    watched = np.zeros(track.ticks.size, dtype=bool)
    for s in ep.sightings_of(slot):
        watched |= (track.ticks >= s.tick_start) & (track.ticks <= s.tick_end)
    flagged = (dist < radius) & ~watched & track.playing_alive()
    return [
        BlendWindow(
            start=int(track.ticks[run[0]]),
            end=int(track.ticks[run[-1]]),
            cx=float(track.x[run].mean()),
            cy=float(track.y[run].mean()),
        )
        for run in _runs(track.ticks, flagged, ep.snapshot_stride)
    ]


def build_missed_blend(
    ep: Episode,
    slot: int,
    *,
    map_image: str | np.ndarray | None = None,
    radius: float = 26.0,
) -> Figure:
    """Build the overlay figure (sizes derived from the map aspect)."""
    windows = missed_blend_windows(ep, slot, radius=radius)
    track = ep.tracks[slot]
    player = ep.players.get(slot)
    label = player.label if player else f"slot {slot}"
    role = player.role if player else "?"
    color = lifted_player_color(player.color) if player and player.color else INK

    fig_w = 12.5
    ax_w_frac, ax_x0 = 0.94, 0.03
    map_h_in = fig_w * ax_w_frac * ep.map_h / ep.map_w
    title_in, caption_in = 0.45, 0.70
    fig_h = title_in + map_h_in + caption_in
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=PAGE)
    ax = fig.add_axes((ax_x0, caption_in / fig_h, ax_w_frac, map_h_in / fig_h))
    ax.set_aspect("equal")
    world_axes(ax, ep.map_w, ep.map_h, background=map_image)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    stations = np.asarray(ep.tasks, dtype=float)
    if stations.size:
        ax.scatter(
            stations[:, 0], stations[:, 1], marker="o", facecolors="none",
            edgecolors=STATION_MARK, s=34, lw=1.0, zorder=3,
        )
    vents = np.asarray(ep.vents, dtype=float)
    if vents.size:
        ax.scatter(vents[:, 0], vents[:, 1], marker="D", c=PORTAL_MARK, s=20, zorder=3)

    for run in _runs(track.ticks, track.playing_alive(), ep.snapshot_stride):
        ax.plot(track.x[run], track.y[run], color=color, lw=1.2, zorder=4)

    kills = [k for k in ep.kills if k.killer == slot]
    if kills:
        kx, ky = [k.x for k in kills], [k.y for k in kills]
        ax.scatter(kx, ky, marker="x", c=INK, s=110, lw=3.2, zorder=5)
        ax.scatter(kx, ky, marker="x", c=NEGATIVE, s=60, lw=1.8, zorder=6)

    for w in windows:
        ax.add_patch(
            Circle((w.cx, w.cy), _DISC_RADIUS, facecolor=ACCENT, alpha=0.38,
                   edgecolor=ACCENT, lw=1.0, zorder=7)
        )

    ax.set_title(
        f"missed blend windows, {label} ({role}), {ep.episode_id}",
        color=SECONDARY, fontsize=11, loc="left",
    )
    ax.legend(
        handles=[
            Line2D([], [], marker="o", ls="", ms=7, mfc="none", mec=STATION_MARK, label="task station"),
            Line2D([], [], marker="D", ls="", ms=5, color=PORTAL_MARK, label="vent"),
            Line2D([], [], marker="x", ls="", ms=8, mew=2.4, color=NEGATIVE, label="kill"),
            Line2D([], [], marker="o", ls="", ms=9, mfc=ACCENT, mec=ACCENT, alpha=0.5, label="missed blend window"),
            Line2D([], [], lw=1.4, color=color, label="path"),
        ],
        loc="lower right", frameon=False, fontsize=8, labelcolor=SECONDARY,
    )

    crew_occ = [station_occupancy(ep, s) for s in ep.crew]
    crew_occ = [v for v in crew_occ if np.isfinite(v)]
    crew_mean = float(np.mean(crew_occ)) if crew_occ else float("nan")
    own = station_occupancy(ep, slot)
    caption = " ".join(
        [
            f"{len(windows)} windows: within {radius:.0f}px of a station while no one had line of sight.",
            f"station occupancy this episode: crew mean {crew_mean:.1%}, this player {own:.1%}."
            if np.isfinite(crew_mean) and np.isfinite(own)
            else "",
        ]
    ).strip()
    fig.text(
        ax_x0, (caption_in - 0.14) / fig_h, "\n".join(textwrap.wrap(caption, 110)),
        ha="left", va="top", color=MUTED, fontsize=7, linespacing=1.5,
    )
    return fig


def render_missed_blend(
    ep: Episode,
    slot: int,
    *,
    map_image: str | np.ndarray | None = None,
    radius: float = 26.0,
    dpi: int = 130,
) -> bytes:
    """Render the overlay to PNG bytes."""
    fig = build_missed_blend(ep, slot, map_image=map_image, radius=radius)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=PAGE, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return buf.getvalue()
