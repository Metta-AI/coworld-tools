"""Continuous-world navigation end to end, with no game server.

Executable documentation for the ``nav_mesh`` + ``simulation`` stack:

    walkability mask
      -> builder.build_graph          (offline lattice waypoint graph)
      -> builder.build_interchange    (the JSON seam)
      -> nav_mesh.mesh_from_interchange
      -> find_path                    (inertia-aware A*)
      -> NavState                     (hold-to-waypoint follower)
      -> simulation.Engine            (byte-faithful reference physics)

The body accelerates, carries momentum, slides along walls, and — per the
follower contract — is released within ``arrival_radius`` of the goal so
residual velocity coasts it to rest ON the goal. ``heading() == (0, 0)`` is
the arrival signal.

Run from the repo root with:

    python players/player_sdk/docs/metta_cogames_framework/examples/inertial_nav_demo.py
"""

from __future__ import annotations

import math

import numpy as np

from players.player_sdk import nav_mesh as nav
from players.player_sdk.nav_mesh import builder
from players.player_sdk.simulation import Body, Engine


def make_map() -> np.ndarray:
    """A 140x100 pixel map with a wall bar that forces a detour."""
    mask = np.ones((100, 140), dtype=bool)  # (rows=y, cols=x)
    mask[0:70, 65:75] = False  # wall bar from the top edge; gap at the bottom
    return mask


def build_mesh(mask: np.ndarray) -> nav.NavMesh:
    params = builder.BuildParams(grid=10, edge_max=22)
    nodes, edges = builder.build_graph(mask, params)
    interchange = builder.build_interchange(mask, nodes, edges, params, source="demo")
    return nav.mesh_from_interchange(interchange)


def main() -> None:
    mask = make_map()
    mesh = build_mesh(mask)
    print(f"mesh: {len(mesh.nodes)} nodes / {len(mesh.edges)} edges from a "
          f"{mask.shape[1]}x{mask.shape[0]} mask")

    start, goal = (20, 20), (120, 20)  # straight line is blocked by the bar
    engine = Engine(mesh.grid)  # default InertiaParams = reference physics
    body = Body(x=start[0], y=start[1])
    follower = nav.NavState(params=nav.NavParams(), grid=mesh.grid)
    plan = follower.replan(mesh, start, goal)
    assert plan is not None
    print(f"plan: {len(plan)} waypoints, cost {plan.cost:.0f}")

    for tick in range(1, 601):
        follower.update(body.pos)
        if follower.needs_replan:
            follower.replan(mesh, body.pos, goal)
        dx, dy = follower.heading(body.pos)
        if (dx, dy) == (0, 0) and follower.arrived:
            print(f"tick {tick:3d}: heading (0,0) -> ARRIVED (controls released)")
            break
        engine.step(body, dx, dy)
        if tick % 25 == 0:
            print(
                f"tick {tick:3d}: pos={body.pos} vel=({body.velX / 256:+.2f},"
                f"{body.velY / 256:+.2f}) px/tick heading=({dx:+d},{dy:+d})"
            )
    else:
        raise SystemExit("never arrived — increase the tick budget?")

    # Residual momentum coasts to rest on the goal (friction only).
    for _ in range(20):
        engine.step(body, 0, 0)
    dist = math.hypot(body.x - goal[0], body.y - goal[1])
    print(f"settled at {body.pos}, {dist:.1f}px from the goal "
          f"(arrival_radius={follower.params.arrival_radius})")


if __name__ == "__main__":
    main()
