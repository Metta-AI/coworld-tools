"""Compile a tool interchange into the canonical two-file nav-mesh.

    python -m players.player_sdk.nav_mesh compile <in.json> <out.walk> <out.graph>

The offline ``builder`` subpackage emits the JSON interchange; this package
(the format owner) compiles it to the canonical binary pair.
"""

from __future__ import annotations

import argparse
import sys

from .io import load_mesh, mesh_from_interchange, save_mesh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m players.player_sdk.nav_mesh")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compile", help="interchange JSON -> canonical .walk + .graph")
    c.add_argument("interchange")
    c.add_argument("walk_out")
    c.add_argument("graph_out")
    args = parser.parse_args(argv)

    if args.cmd == "compile":
        mesh = mesh_from_interchange(args.interchange)
        save_mesh(mesh, args.walk_out, args.graph_out)
        # Round-trip to prove the canonical files are readable.
        rt = load_mesh(args.walk_out, args.graph_out)
        comps = _component_count(rt)
        print(
            f"compiled {len(rt)} nodes, {len(rt.edges)} edges, "
            f"grid {rt.grid.width}x{rt.grid.height}, {comps} component(s) "
            f"-> {args.walk_out}, {args.graph_out}",
            file=sys.stderr,
        )
    return 0


def _component_count(mesh) -> int:
    """Connected-component count over the (undirected view of the) graph."""
    seen: set[int] = set()
    comps = 0
    for start in (n.id for n in mesh.nodes):
        if start in seen:
            continue
        comps += 1
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for nbr, _w, _t in mesh.neighbors(cur):
                if nbr not in seen:
                    stack.append(nbr)
    return comps


if __name__ == "__main__":
    raise SystemExit(main())
