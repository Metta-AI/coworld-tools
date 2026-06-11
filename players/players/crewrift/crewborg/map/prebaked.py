"""Load and save Crewborg's offline-baked Croatoan artifact."""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import BinaryIO

import numpy as np

from players.crewrift.crewborg.agent_tracking import OccupancySubstrate
from players.crewrift.crewborg.map.types import MapData
from players.crewrift.crewborg.nav import NavGraph

PREBAKED_FORMAT_VERSION = 2
DEFAULT_PREBAKED_FILENAME = "croatoan_prebaked.npz"


@dataclass(frozen=True)
class PrebakedMap:
    """Static map-derived data generated before the player image is built."""

    map_data: MapData
    nav: NavGraph
    tracking_substrate: OccupancySubstrate | None = None
    metadata: dict[str, str] = field(default_factory=dict)


def load_croatoan_prebaked() -> PrebakedMap:
    """Load the checked-in map/nav/tracking artifact shipped with the package."""

    path = resources.files("players.crewrift.crewborg.map").joinpath(DEFAULT_PREBAKED_FILENAME)
    with path.open("rb") as handle:
        return load_prebaked_map(handle)


def load_prebaked_map(path_or_file: str | Path | BinaryIO) -> PrebakedMap:
    """Load one prebuilt map artifact from a filesystem path or binary file."""

    with np.load(path_or_file, allow_pickle=False) as archive:
        payload = archive["payload"].tobytes()
    data = pickle.loads(payload)
    version = data.get("format_version")
    if version != PREBAKED_FORMAT_VERSION:
        raise ValueError(f"unsupported prebuilt map format {version!r}")
    map_data = data["map_data"]
    nav = data["nav"]
    if not isinstance(map_data, MapData):
        raise TypeError("prebuilt map payload does not contain MapData")
    if not isinstance(nav, NavGraph):
        raise TypeError("prebuilt map payload does not contain NavGraph")
    tracking_substrate = data.get("tracking_substrate")
    if tracking_substrate is not None and not isinstance(tracking_substrate, OccupancySubstrate):
        raise TypeError("prebuilt map payload does not contain OccupancySubstrate")
    return PrebakedMap(
        map_data=map_data,
        nav=nav,
        tracking_substrate=tracking_substrate,
        metadata=dict(data.get("metadata") or {}),
    )


def save_prebaked_map(path: str | Path, prebaked: PrebakedMap) -> None:
    """Write one prebuilt map artifact."""

    payload = pickle.dumps(
        {
            "format_version": PREBAKED_FORMAT_VERSION,
            "map_data": prebaked.map_data,
            "nav": prebaked.nav,
            "tracking_substrate": prebaked.tracking_substrate,
            "metadata": prebaked.metadata,
        },
        protocol=pickle.HIGHEST_PROTOCOL,
    )
    np.savez_compressed(path, payload=np.frombuffer(payload, dtype=np.uint8))
