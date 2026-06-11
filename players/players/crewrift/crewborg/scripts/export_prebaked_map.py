#!/usr/bin/env python3
"""Generate Crewborg's checked-in Croatoan map/nav/tracking artifact.

The static semantic map comes from the vendored ``croatoan.resources`` file. The
walkability mask comes from the current CrewRift simulation because it is derived
from the map image's walk layer, not from the semantic rectangles alone.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

import numpy as np

from players.crewrift.crewborg.agent_tracking import build_occupancy_substrate
from players.crewrift.crewborg.map import (
    DEFAULT_MAP_HEIGHT,
    DEFAULT_MAP_WIDTH,
    load_croatoan_map,
)
from players.crewrift.crewborg.map.prebaked import PrebakedMap, save_prebaked_map
from players.crewrift.crewborg.nav import DEFAULT_CELL_SIZE, build_nav_graph

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = REPO_ROOT / "players/crewrift/crewborg/map/croatoan_prebaked.npz"
DEFAULT_COWORLD_ROOT = Path("~/coding/coworlds/coworld-crewrift").expanduser()

_NIM_EXPORTER = """
import std/[os]
import crewrift/sim

if paramCount() < 1:
  quit("usage: export_walkability OUT_PATH", QuitFailure)

let outPath = paramStr(paramCount())
var server = initSimServer(defaultGameConfig())
var data = newString(server.walkMask.len)
for index, walkable in server.walkMask:
  data[index] = if walkable: char(1) else: char(0)
writeFile(outPath, data)
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coworld-root",
        type=Path,
        default=DEFAULT_COWORLD_ROOT,
        help="CrewRift checkout used to export the authoritative walkability mask.",
    )
    parser.add_argument(
        "--walkability-npz",
        type=Path,
        default=None,
        help="Optional .npz with a boolean 'walkability' array; skips Coworld/Nim export.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output .npz artifact path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    map_data = load_croatoan_map()
    if args.walkability_npz is not None:
        walkability = _load_walkability_npz(args.walkability_npz)
        source = args.walkability_npz.name
        coworld_commit = ""
    else:
        walkability = _export_walkability_from_coworld(args.coworld_root)
        source = "coworld-crewrift"
        coworld_commit = _git_commit(args.coworld_root)

    expected_shape = (map_data.height, map_data.width)
    if walkability.shape != expected_shape:
        raise ValueError(f"walkability shape {walkability.shape} does not match map {expected_shape}")

    nav = build_nav_graph(walkability, map_data=map_data)
    tracking_substrate = build_occupancy_substrate(nav, map_data)
    metadata = {
        "source": source,
        "coworld_commit": coworld_commit,
        "cell_size": str(DEFAULT_CELL_SIZE),
        "map_width": str(map_data.width),
        "map_height": str(map_data.height),
        "tracking_anchors": str(len(tracking_substrate.anchors)),
        "tracking_polylines": str(len(tracking_substrate.polylines)),
        "tracking_grid_cells": str(len(tracking_substrate.cells)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    save_prebaked_map(
        args.out,
        PrebakedMap(
            map_data=map_data,
            nav=nav,
            tracking_substrate=tracking_substrate,
            metadata=metadata,
        ),
    )
    print(
        f"wrote {args.out} with {len(nav.node_point)} nav nodes, "
        f"{sum(len(edges) for edges in nav.adjacency.values())} directed walk edges, "
        f"{len(tracking_substrate.polylines)} tracking polylines"
    )


def _load_walkability_npz(path: Path) -> np.ndarray:
    with np.load(path, allow_pickle=False) as archive:
        return archive["walkability"].astype(bool, copy=False)


def _export_walkability_from_coworld(coworld_root: Path) -> np.ndarray:
    if not coworld_root.exists():
        raise FileNotFoundError(f"Coworld root does not exist: {coworld_root}")
    if not (coworld_root / "src/crewrift/sim.nim").exists():
        raise FileNotFoundError(f"Coworld root does not look like CrewRift: {coworld_root}")

    tmp_dir = coworld_root / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    exporter = tmp_dir / f"crewborg_export_walkability_{os.getpid()}.nim"
    raw = tmp_dir / f"crewborg_walkability_{os.getpid()}.bin"
    try:
        exporter.write_text(_NIM_EXPORTER)
        subprocess.run(
            ["nim", "r", "--path:src", str(exporter), "--", str(raw)],
            cwd=coworld_root,
            check=True,
        )
        data = np.frombuffer(raw.read_bytes(), dtype=np.uint8).astype(bool)
    finally:
        exporter.unlink(missing_ok=True)
        raw.unlink(missing_ok=True)

    expected = DEFAULT_MAP_WIDTH * DEFAULT_MAP_HEIGHT
    if data.size != expected:
        raise ValueError(f"Coworld walkability size {data.size} does not match expected {expected}")
    return data.reshape((DEFAULT_MAP_HEIGHT, DEFAULT_MAP_WIDTH))


def _git_commit(cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


if __name__ == "__main__":
    main()
