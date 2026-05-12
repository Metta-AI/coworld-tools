"""Scripted economy-chain teacher for kickstarting (dinky-style).

Teaches the miner/aligner economy chain:
  Miners:   extractor → hub (deposit)
  Aligners: hub (withdraw hearts) → craft station → junction (capture)

No scout role (dropped per PI meeting 2026-03-13).
Half miners, half aligners (dinky's 50/50 split).

Compatible with cogames 0.22.2 (sentinel-based token iteration,
works with both 200 and 300 token obs spaces).

Tag/feature/inventory IDs are for cogames 0.22.2 arena/machina_1 maps
(21 tags, alphabetically sorted). Verify with:
    from mettagrid.policy.policy_env_interface import PolicyEnvInterface
    pei = PolicyEnvInterface(env)
    print(sorted(pei.tags.items(), key=lambda x: x[1]))
    print(sorted(pei.features.items(), key=lambda x: x[1]))

Transport-encoded actions (VIBE_ACTIONS=1, Phase 2 R24):
  N_primary=5, N_vibe=7 (default, heart, gear, scrambler, aligner, miner, scout)
  transport = N_PRIMARY + direction * N_VIBE + vibe_idx
  When VIBE_ACTIONS=1, teacher returns transport actions + 40-dim logits for KL.
"""

import os

import numpy as np
import torch

# ── Observation encoding (cogames 0.22.2) ─────────────────────
TAG_FEAT = 6              # "tag" feature index (was 7 in 0.18)
CENTER = 6                # center of 13x13 egocentric grid
COORD_EMPTY = 255
COORD_GLOBAL = 254

# Actions: 0=noop, 1=north, 2=south, 3=west, 4=east
ACT_NOOP = 0
ACT_NORTH = 1
ACT_SOUTH = 2
ACT_WEST = 3
ACT_EAST = 4

# ── Tag IDs (cogames 0.22.2, arena/machina_1, alphabetically sorted) ──
TAG_HUB = 15              # type:hub (was 17 in 0.18)
TAG_JUNCTION = 16         # type:junction (was 18)
TAG_C_ALIGNER = 9         # type:c:aligner (was 11)
TAG_C_MINER = 10          # type:c:miner (was 12)
TAG_CARBON_EXT = 13       # type:carbon_extractor (was 15)
TAG_GERMANIUM_EXT = 14    # type:germanium_extractor (was 16)
TAG_OXYGEN_EXT = 17       # type:oxygen_extractor (was 19)
TAG_SILICON_EXT = 19      # type:silicon_extractor (was 21)

EXTRACTOR_TAGS = {TAG_CARBON_EXT, TAG_GERMANIUM_EXT, TAG_OXYGEN_EXT, TAG_SILICON_EXT}

# ── Inventory feature IDs (cogames 0.22.2, arena) ──
INV_HEART = 32            # inv:heart (was 17 in 0.18)
INV_ALIGNER = 22          # inv:aligner gear (was 31)
INV_CARBON = 14           # inv:carbon (was 25)
INV_OXYGEN = 12           # inv:oxygen (was 23)
INV_GERMANIUM = 16        # inv:germanium (was 27)
INV_SILICON = 18          # inv:silicon (was 29)

RESOURCE_FEATS = {INV_CARBON, INV_OXYGEN, INV_GERMANIUM, INV_SILICON}

# Wander directions (cycle through when no target visible)
WANDER_ACTIONS = [ACT_EAST, ACT_SOUTH, ACT_WEST, ACT_NORTH]
WANDER_PERIOD = 8  # steps per direction

# ── Transport encoding (Phase 2 R24) ─────────────────────────
# Vibes: 0=default, 1=heart, 2=gear, 3=scrambler, 4=aligner, 5=miner, 6=scout
N_PRIMARY = 5
N_VIBE = 7
VIBE_MINER = 5
VIBE_ALIGNER = 4
_TRANSPORT_MODE = os.environ.get("VIBE_ACTIONS", "") == "1"


def _encode_transport(direction, vibe_idx):
    """Encode direction + vibe into transport action index.

    transport = N_PRIMARY + direction * N_VIBE + vibe_idx
    """
    return N_PRIMARY + direction * N_VIBE + vibe_idx


def _move_toward(target_row, target_col):
    """Move toward target tile from center."""
    dr = target_row - CENTER
    dc = target_col - CENTER
    if dr == 0 and dc == 0:
        return ACT_NOOP
    if abs(dr) >= abs(dc):
        return ACT_SOUTH if dr > 0 else ACT_NORTH
    return ACT_EAST if dc > 0 else ACT_WEST


def _find_nearest(tokens, target_tags):
    """Find nearest tile matching any of the target tags.

    Returns (row, col) or None.
    """
    best_dist = 999
    best_loc = None
    for t in range(tokens.shape[0]):
        coord = tokens[t, 0]
        if coord == COORD_EMPTY:
            break
        if coord == COORD_GLOBAL:
            continue
        feat, val = tokens[t, 1], tokens[t, 2]
        if feat != TAG_FEAT:
            continue
        if val in target_tags:
            row = (coord >> 4) & 0x0F
            col = coord & 0x0F
            dist = abs(row - CENTER) + abs(col - CENTER)
            if dist < best_dist:
                best_dist = dist
                best_loc = (row, col)
    return best_loc


def _has_inventory(tokens, feat_id):
    """Check if agent has any amount of the given inventory item."""
    for t in range(tokens.shape[0]):
        coord = tokens[t, 0]
        if coord == COORD_EMPTY:
            break
        row = (coord >> 4) & 0x0F
        col = coord & 0x0F
        if row == CENTER and col == CENTER and tokens[t, 1] == feat_id and tokens[t, 2] > 0:
            return True
    return False


def _has_any_resource(tokens):
    """Check if agent has any resource (carbon, oxygen, germanium, silicon)."""
    for feat_id in RESOURCE_FEATS:
        if _has_inventory(tokens, feat_id):
            return True
    return False


def _teacher_miner(tokens, step):
    """Miner: extractor → hub (deposit). Repeat."""
    has_resource = _has_any_resource(tokens)

    if has_resource:
        # Go deposit at hub
        loc = _find_nearest(tokens, {TAG_HUB})
        if loc:
            direction = _move_toward(*loc)
            return _encode_transport(direction, VIBE_MINER) if _TRANSPORT_MODE else direction
    else:
        # Go mine at nearest extractor
        loc = _find_nearest(tokens, EXTRACTOR_TAGS)
        if loc:
            direction = _move_toward(*loc)
            return _encode_transport(direction, VIBE_MINER) if _TRANSPORT_MODE else direction

    # Wander if no target visible
    direction = WANDER_ACTIONS[(step // WANDER_PERIOD) % 4]
    return _encode_transport(direction, VIBE_MINER) if _TRANSPORT_MODE else direction


def _teacher_aligner(tokens, step):
    """Aligner: hub (get hearts) → craft station (craft gear) → junction (capture)."""
    has_gear = _has_inventory(tokens, INV_ALIGNER)
    has_hearts = _has_inventory(tokens, INV_HEART)

    if has_gear:
        # Go capture junction
        loc = _find_nearest(tokens, {TAG_JUNCTION})
        if loc:
            direction = _move_toward(*loc)
            return _encode_transport(direction, VIBE_ALIGNER) if _TRANSPORT_MODE else direction
    elif has_hearts:
        # Go craft gear
        loc = _find_nearest(tokens, {TAG_C_ALIGNER})
        if loc:
            direction = _move_toward(*loc)
            return _encode_transport(direction, VIBE_ALIGNER) if _TRANSPORT_MODE else direction
    else:
        # Go get hearts from hub
        loc = _find_nearest(tokens, {TAG_HUB})
        if loc:
            direction = _move_toward(*loc)
            return _encode_transport(direction, VIBE_ALIGNER) if _TRANSPORT_MODE else direction

    # Wander
    direction = WANDER_ACTIONS[(step // WANDER_PERIOD) % 4]
    return _encode_transport(direction, VIBE_ALIGNER) if _TRANSPORT_MODE else direction


def teacher_action(tokens, agent_idx, step):
    """Compute teacher action for one agent.

    Args:
        tokens: [200, 3] int array (coord, feature_id, value)
        agent_idx: agent index in the environment (0-based)
        step: current step count (for wander cycling)

    Returns:
        int action index (0-4 if standard, 0-39 if VIBE_ACTIONS=1)
    """
    # Dinky pattern: first half miners, second half aligners
    if agent_idx % 2 == 0:
        return _teacher_miner(tokens, step)
    else:
        return _teacher_aligner(tokens, step)


def teacher_logits(tokens, agent_idx, step, n_actions=None):
    """Compute teacher logits (soft targets) for KL kickstarting.

    Returns a 1D numpy array of length n_actions with high weight on the
    chosen action and small uniform weight elsewhere.

    Args:
        tokens: [N, 3] int array
        agent_idx: agent index
        step: step count
        n_actions: total number of actions (5 or 40)

    Returns:
        np.ndarray of shape [n_actions] (unnormalized log-probs)
    """
    action = teacher_action(tokens, agent_idx, step)
    if n_actions is None:
        n_actions = (N_PRIMARY + N_PRIMARY * N_VIBE) if _TRANSPORT_MODE else N_PRIMARY
    logits = np.full(n_actions, -5.0, dtype=np.float32)  # small uniform
    logits[action] = 5.0  # high confidence on chosen action
    return logits


def compute_teacher_actions(observations, device, step=0):
    """Compute teacher actions for all agents in a training batch.

    Args:
        observations: [segments, horizon, N, 3] tensor (N=200 for 0.18-0.19, N=300 for 0.22+)
        device: torch device
        step: global step count (for wander cycling)

    Returns:
        [segments, horizon] long tensor of action indices
    """
    S, H = observations.shape[:2]
    actions = torch.zeros(S, H, dtype=torch.long, device=device)
    obs_np = observations.cpu().numpy().astype(np.int32)

    for s in range(S):
        for h in range(H):
            # Agent index cycles through num_agents
            agent_idx = s % 8  # max 8 agents per env
            actions[s, h] = teacher_action(obs_np[s, h], agent_idx, step + h)

    return actions
