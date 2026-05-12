"""Scripted scout teacher for kickstarting.

Parses observation tokens to find c:scout station and navigates toward it.
Used for post-hoc reward shaping in the training loop.
"""

import numpy as np

# Tag IDs (from PolicyEnvInterface.tag_id_to_name on COGSGUARD_ARENA)
TAG_C_SCOUT = 13
TAG_HUB = 17
TAG_CARBON_EXT = 15
TAG_GERMANIUM_EXT = 16
TAG_OXYGEN_EXT = 19
TAG_SILICON_EXT = 21

EXTRACTOR_TAGS = {TAG_CARBON_EXT, TAG_GERMANIUM_EXT, TAG_OXYGEN_EXT, TAG_SILICON_EXT}

# Observation feature indices
FEAT_TAG = 7
FEAT_INV_SCOUT = 37   # inv:scout
FEAT_INV_CARBON = 25  # inv:carbon
FEAT_INV_OXYGEN = 23  # inv:oxygen
FEAT_INV_GERMANIUM = 27
FEAT_INV_SILICON = 29

RESOURCE_FEATS = {FEAT_INV_CARBON, FEAT_INV_OXYGEN, FEAT_INV_GERMANIUM, FEAT_INV_SILICON}

# Actions
ACT_NOOP = 0
ACT_NORTH = 1
ACT_SOUTH = 2
ACT_WEST = 3
ACT_EAST = 4

# Observation grid center (13x13, center at 6,6)
CENTER_ROW = 6
CENTER_COL = 6

COORD_GLOBAL = 254
COORD_EMPTY = 255


def get_teacher_action(obs: np.ndarray) -> int:
    """Compute optimal action for a single agent from its observation tokens.

    Args:
        obs: [num_tokens, 3] uint8 array. Each token is [packed_coord, feature_id, value].

    Returns:
        Action index (0-4).
    """
    has_scout_gear = False
    has_resources = False
    scout_pos = None
    hub_pos = None
    nearest_ext = None
    nearest_ext_dist = 999

    for t in range(obs.shape[0]):
        coord, feat_id, val = int(obs[t, 0]), int(obs[t, 1]), int(obs[t, 2])
        if coord == COORD_EMPTY:
            break
        if coord == COORD_GLOBAL:
            continue

        row = (coord >> 4) & 0x0F
        col = coord & 0x0F

        if feat_id == FEAT_TAG:
            if val == TAG_C_SCOUT:
                scout_pos = (row, col)
            elif val == TAG_HUB:
                hub_pos = (row, col)
            elif val in EXTRACTOR_TAGS:
                dist = abs(row - CENTER_ROW) + abs(col - CENTER_COL)
                if dist < nearest_ext_dist:
                    nearest_ext_dist = dist
                    nearest_ext = (row, col)
        elif feat_id == FEAT_INV_SCOUT:
            if row == CENTER_ROW and col == CENTER_COL and val > 0:
                has_scout_gear = True
        elif feat_id in RESOURCE_FEATS:
            if row == CENTER_ROW and col == CENTER_COL and val > 0:
                has_resources = True

    # Decision: get scout gear first, then gather resources
    if not has_scout_gear:
        if scout_pos is not None:
            return _navigate_to(scout_pos)
        if hub_pos is not None:
            return _navigate_to(hub_pos)
    else:
        if has_resources and hub_pos is not None:
            return _navigate_to(hub_pos)
        if nearest_ext is not None:
            return _navigate_to(nearest_ext)
        if hub_pos is not None:
            return _navigate_to(hub_pos)

    # Fallback: move east (deterministic, no state needed)
    return ACT_EAST


def _navigate_to(target: tuple[int, int]) -> int:
    """Move toward target position relative to observation grid center."""
    dr = target[0] - CENTER_ROW
    dc = target[1] - CENTER_COL

    if dr == 0 and dc == 0:
        return ACT_NOOP

    if abs(dr) >= abs(dc):
        return ACT_SOUTH if dr > 0 else ACT_NORTH
    else:
        return ACT_EAST if dc > 0 else ACT_WEST
