"""Crewborg static map: the offline-baked resource map, nav graph, and tracking substrate.

Vent, emergency-button, room, and task-station locations are not in the Sprite-v1
stream — they live in the game's map resource file, which crewborg vendors
(``croatoan.resources``). The player ships a prebuilt ``croatoan_prebaked.npz``
artifact so episode startup does not parse the resource file, build the nav
graph, or precompute tracking routes.
"""

from players.crewrift.crewborg.map.bake import (
    DEFAULT_MAP_HEIGHT,
    DEFAULT_MAP_WIDTH,
    bake_map,
    load_croatoan_map,
    walkability_matches,
)
from players.crewrift.crewborg.map.prebaked import (
    PrebakedMap,
    load_croatoan_prebaked,
    load_prebaked_map,
    save_prebaked_map,
)
from players.crewrift.crewborg.map.types import (
    MapData,
    MapPoint,
    MapRect,
    Room,
    TaskStation,
    Vent,
)

__all__ = [
    "DEFAULT_MAP_HEIGHT",
    "DEFAULT_MAP_WIDTH",
    "MapData",
    "MapPoint",
    "MapRect",
    "PrebakedMap",
    "Room",
    "TaskStation",
    "Vent",
    "bake_map",
    "load_croatoan_map",
    "load_croatoan_prebaked",
    "load_prebaked_map",
    "save_prebaked_map",
    "walkability_matches",
]
