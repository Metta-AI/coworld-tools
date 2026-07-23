"""Dev CLI: render the four CrewRift figures straight from JSONL files.

    python -m crewrift_analysis contrast-table <dir>  [--glob '*.jsonl'] [--out DIR]
    python -m crewrift_analysis vote-ladder  <ep.jsonl> [--out DIR]
    python -m crewrift_analysis missed-blend <ep.jsonl> [--slot N] [--radius PX]
                                             [--map-image PATH] [--out DIR]
    python -m crewrift_analysis fog-of-war   <ep.jsonl> --observer N [--phases 1,2]
                                             [--map-image PATH] [--out DIR]

Inputs are `expand_replay --format jsonl --snapshot-every N` files (see the
README). `--map-image` optionally puts the Croatoan backdrop under the two
map figures; without it they render on the dark surface. Requires the
``[charts]`` extra.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .events import CrewriftLogError, load_episode
from .metrics import aggregate_contrast

__all__ = ["main"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m crewrift_analysis", description=__doc__.split("\n", 1)[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    contrast = sub.add_parser("contrast-table", help="aggregate crew/imposter contrast table")
    contrast.add_argument("directory", help="directory of per-episode .jsonl files")
    contrast.add_argument("--glob", default="*.jsonl")
    contrast.add_argument("--out", default=".")

    ladder = sub.add_parser("vote-ladder", help="who voted for whom, per meeting")
    ladder.add_argument("episode", help="one episode's .jsonl")
    ladder.add_argument("--out", default=".")

    blend = sub.add_parser("missed-blend", help="near-a-station-and-unwatched map overlay")
    blend.add_argument("episode")
    blend.add_argument("--slot", type=int, default=None, help="player slot (default: first imposter)")
    blend.add_argument("--radius", type=float, default=26.0, help="blend radius in px")
    blend.add_argument("--map-image", default=None, help="optional Croatoan backdrop image")
    blend.add_argument("--out", default=".")

    fog = sub.add_parser("fog-of-war", help="what one observer actually saw, per Playing phase")
    fog.add_argument("episode")
    fog.add_argument("--observer", type=int, required=True, help="observer slot")
    fog.add_argument("--phases", default=None, help="comma-separated 1-based Playing phases")
    fog.add_argument("--map-image", default=None)
    fog.add_argument("--out", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        from . import figures
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "contrast-table":
            files = sorted(Path(args.directory).glob(args.glob))
            if not files:
                print(f"no files match {args.glob!r} in {args.directory}", file=sys.stderr)
                return 1
            episodes = [load_episode(f) for f in files]
            png = figures.render_contrast_table(
                aggregate_contrast(episodes), n_episodes=len(episodes)
            )
            path = out / "contrast_table.png"
        elif args.command == "vote-ladder":
            ep = load_episode(args.episode)
            png = figures.render_vote_ladder(ep)
            path = out / f"vote_ladder_{ep.episode_id}.png"
        elif args.command == "missed-blend":
            ep = load_episode(args.episode)
            slot = args.slot
            if slot is None:
                if not ep.imposters:
                    print("episode has no imposters; pass --slot", file=sys.stderr)
                    return 1
                slot = ep.imposters[0]
                player = ep.players[slot]
                print(f"--slot not given; using imposter slot {slot} ({player.color})")
            png = figures.render_missed_blend(
                ep, slot, map_image=args.map_image, radius=args.radius
            )
            path = out / f"missed_blend_{ep.episode_id}_slot{slot}.png"
        else:  # fog-of-war
            ep = load_episode(args.episode)
            phases = (
                [int(p) for p in args.phases.split(",") if p.strip()] if args.phases else None
            )
            png = figures.render_fog_of_war(
                ep, args.observer, phases=phases, map_image=args.map_image
            )
            path = out / f"fog_of_war_{ep.episode_id}_obs{args.observer}.png"
    except (CrewriftLogError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    path.write_bytes(png)
    print(path)
    return 0
