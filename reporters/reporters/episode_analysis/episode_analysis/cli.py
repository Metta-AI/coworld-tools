"""Dev CLI: render charts straight from a canonical event-log Parquet.

    python -m episode_analysis <events.parquet> --out <dir> [--width W --height H]

Writes an occupancy heatmap (from ``position`` events) and a per-player
swimlane timeline (``reward`` markers, ``death`` crosses, global span rows)
as PNGs. This is the local iteration loop for reporter authors — the
packaged replacement for the origin project's three per-chart CLIs
(``swgy-spatial-render``, ``swgy-task-viz``, ``swgy-kill-plot``).

Requires the ``[charts]`` extra.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .eventlog import EventLog
from .heatmap import bin_positions

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m episode_analysis", description=__doc__.split("\n", 1)[0]
    )
    parser.add_argument("events", help="canonical event-log parquet file")
    parser.add_argument("--out", default=".", help="output directory (default: cwd)")
    parser.add_argument("--width", type=float, default=None, help="world width (default: from data)")
    parser.add_argument("--height", type=float, default=None, help="world height")
    parser.add_argument("--position-key", default="position")
    parser.add_argument("--reward-key", default="reward")
    parser.add_argument("--death-key", default="death")
    args = parser.parse_args(argv)

    try:
        from .charts import Lane, Marker, density_layer, render_heatmap, render_swimlanes
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    log = EventLog.from_parquet(args.events)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    pts = [(x, y) for _, _, x, y in log.positions(key=args.position_key)]
    if pts:
        width = args.width or (max(x for x, _ in pts) + 1)
        height = args.height or (max(y for _, y in pts) + 1)
        layer = density_layer(bin_positions(pts, width, height))
        if layer is not None:
            png = render_heatmap(
                layer,
                title="occupancy — all players",
                cbar_label="samples per cell (log)",
                width=width,
                height=height,
            )
            path = out / "occupancy.png"
            path.write_bytes(png)
            written.append(path)

    lanes = []
    for player in log.players:
        markers = [
            Marker(ts, label=f"{value:+.0f}")
            for ts, value in log.numeric_series(args.reward_key, player=player, field="delta")
        ]
        deaths = [r.ts for r in log.filter(key=args.death_key, player=player)]
        lanes.append(
            Lane(
                label=f"player {player}",
                end_tick=log.max_ts,
                markers=markers,
                cross_tick=deaths[0] if deaths else None,
            )
        )
    if lanes:
        png = render_swimlanes(
            lanes,
            marker_label="reward",
            alt_label="(unused)",
            cross_label="death",
        )
        path = out / "timeline.png"
        path.write_bytes(png)
        written.append(path)

    if not written:
        print("no position/reward/death events found — nothing to render", file=sys.stderr)
        return 1
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
