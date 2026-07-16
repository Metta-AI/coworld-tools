"""Offline nav-mesh construction: walkability mask -> waypoint graph -> JSON.

Pipeline (all offline; nothing here runs per-tick):

1. Obtain a boolean walkability mask (and optionally a wall/occluder mask)
   for your map — from game assets, a rendered frame, or by hand.
2. ``build.build_graph(mask, params, tagger, seeds)`` lays a lattice of
   waypoint nodes over walkable space and connects them with
   corridor-checked edges (union-find stitching, bridge routing, dropped-
   corridor recovery, long-edge subdivision).
3. Optionally ``visibility.enrich_nodes(...)`` bakes per-node line-of-sight
   ``exposure``/``witnesses`` coefficients (engine-faithful DDA raycast,
   parameterized by :class:`~.visibility.SightParams`).
4. ``interchange.write_interchange(...)`` emits the self-described JSON that
   the runtime ingests (``nav_mesh.io.mesh_from_interchange``) or compiles
   to the canonical binary pair (``python -m players.player_sdk.nav_mesh
   compile``).

The JSON interchange is a deliberate seam: the builder never imports the
runtime model, so mesh construction can evolve independently of the format
owner. Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(swgy-crewrift, ``swgy_tools.navmesh``).
"""

from .build import BuildParams, build_graph
from .interchange import INTERCHANGE_FORMAT, build_interchange, write_interchange, pack_bits
from .visibility import (
    RayTemplates,
    SightParams,
    build_ray_templates,
    enrich_nodes,
    exposure_counts,
    is_visible,
    visibility_matrix,
    witness_counts,
)

__all__ = [
    "INTERCHANGE_FORMAT",
    "BuildParams",
    "RayTemplates",
    "SightParams",
    "build_graph",
    "build_interchange",
    "build_ray_templates",
    "enrich_nodes",
    "exposure_counts",
    "is_visible",
    "pack_bits",
    "visibility_matrix",
    "witness_counts",
    "write_interchange",
]
