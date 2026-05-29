"""CLI entry point for the default commissioner server.

The container's `run` command points here. The platform polls `/healthz` and
then drives the round over `WEBSOCKET /round`; see
https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/roles/COMMISSIONER.md
"""

from __future__ import annotations

import argparse

import uvicorn

from server import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Default Coworld commissioner server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Listen port (default: 8080)")
    parser.add_argument(
        "--strategy",
        choices=["round_robin"],
        default="round_robin",
        help="Matchup strategy (only round_robin is implemented today)",
    )
    parser.add_argument("--episodes-per-pair", type=int, default=1, help="Episodes scheduled per matchup")
    parser.add_argument(
        "--graduation",
        choices=["none", "percentile"],
        default="none",
        help="Graduation strategy applied at round end",
    )
    parser.add_argument("--promote-top-pct", type=int, default=0, help="Percent of top policies to promote")
    parser.add_argument("--relegate-bottom-pct", type=int, default=0, help="Percent of bottom policies to relegate")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    app = create_app(
        strategy=args.strategy,
        episodes_per_pair=args.episodes_per_pair,
        graduation=args.graduation,
        promote_top_pct=args.promote_top_pct,
        relegate_bottom_pct=args.relegate_bottom_pct,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
