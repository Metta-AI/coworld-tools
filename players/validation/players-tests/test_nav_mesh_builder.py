"""Tests for the offline mesh builder (players.player_sdk.nav_mesh.builder).

Ported from swgy-crewrift ``packages/swgy-tools/tests/test_navmesh.py`` —
the graph-build and pack_bits subset. The aseprite/resources asset-extraction
tests did not port (those input formats stayed with the origin game).
"""

from __future__ import annotations

import pathlib
import re

import numpy as np

from players.player_sdk.nav_mesh.builder.build import BuildParams, build_graph
from players.player_sdk.nav_mesh.builder.interchange import pack_bits


def test_pack_bits_lsb_first():
    mask = np.zeros((1, 9), dtype=bool)
    mask[0, 0] = mask[0, 8] = True  # bit 0 and bit 8
    packed = pack_bits(mask)
    assert packed == bytes([0b00000001, 0b00000001])


# --- graph build ----------------------------------------------------------


def _connected(nodes, edges) -> int:
    from collections import defaultdict

    adj = defaultdict(list)
    for e in edges:
        adj[e["src"]].append(e["dst"])
        adj[e["dst"]].append(e["src"])
    seen: set[int] = set()
    comps = 0
    for n in nodes:
        if n["id"] in seen:
            continue
        comps += 1
        stack = [n["id"]]
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            stack.extend(adj[c])
    return comps


def test_build_lattice_connected():
    mask = np.ones((9, 9), dtype=bool)
    nodes, edges = build_graph(mask, BuildParams(grid=3, edge_max=4, node_clear=0, edge_clear=0))
    assert len(nodes) == 9  # 3x3 lattice
    assert _connected(nodes, edges) == 1
    # every edge is corridor-clear on an all-walkable mask -> weights positive
    assert all(e["weight"] > 0 for e in edges)


def test_tagger_applied_to_nodes():
    mask = np.ones((6, 6), dtype=bool)
    nodes, _ = build_graph(mask, BuildParams(grid=3, edge_max=4), tagger=lambda x, y: {"corridor"})
    assert all("corridor" in n["tags"] for n in nodes)


def test_seed_adds_node_when_isolated():
    mask = np.zeros((20, 20), dtype=bool)
    mask[15, 15] = True  # lone walkable pixel
    # grid larger than the map => no lattice nodes; the seed must add one.
    nodes, _ = build_graph(
        mask, BuildParams(grid=100, edge_max=4), seeds=[(15, 15, frozenset({"vent"}))]
    )
    assert len(nodes) == 1
    assert (nodes[0]["x"], nodes[0]["y"]) == (15, 15)
    assert "vent" in nodes[0]["tags"]


def test_seed_skipped_when_non_walkable():
    mask = np.ones((6, 6), dtype=bool)
    mask[5, 5] = False
    nodes, _ = build_graph(
        mask, BuildParams(grid=3, edge_max=4), seeds=[(5, 5, frozenset({"vent"}))]
    )
    assert all("vent" not in n["tags"] for n in nodes)


# --- isolation ------------------------------------------------------------


def test_builder_does_not_import_the_runtime_model():
    """The builder stays independent of the runtime nav model — the JSON
    interchange is the boundary (ported invariant; was
    ``test_navmesh_does_not_import_swgy_base_nav``)."""
    import players.player_sdk.nav_mesh.builder as pkg

    pkg_dir = pathlib.Path(pkg.__file__).parent
    pat = re.compile(
        r"^\s*(from|import)\s+(players\.player_sdk\.nav_mesh\.(model|astar|follow|io|params|plan)|\.\.(model|astar|follow|io|params|plan))",
        re.M,
    )
    offenders = [f.name for f in pkg_dir.glob("*.py") if pat.search(f.read_text())]
    assert offenders == [], f"builder must not import the runtime model: {offenders}"
