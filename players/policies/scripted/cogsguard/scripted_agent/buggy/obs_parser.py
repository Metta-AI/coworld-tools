"""Observation parser for Planky policy.

Converts raw observation tokens into StateSnapshot and visible entities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policies.scripted.cogsguard.scripted_agent.utils import add_inventory_token, split_power_suffix

from .context import StateSnapshot
from .entity_map import Entity

if TYPE_CHECKING:
    from mettagrid.policy.policy_env_interface import PolicyEnvInterface
    from mettagrid.simulator.interface import AgentObservation


class ObsParser:
    """Parses observation tokens into state snapshot and visible entities."""

    def __init__(self, policy_env_info: PolicyEnvInterface) -> None:
        self._obs_hr = policy_env_info.obs_height // 2
        self._obs_wr = policy_env_info.obs_width // 2
        self._tag_names = policy_env_info.tag_id_to_name

        # Derive vibe names from action names
        self._vibe_names: list[str] = []
        for action_name in policy_env_info.all_action_names:
            if action_name.startswith("change_vibe_"):
                self._vibe_names.append(action_name[len("change_vibe_") :])

    def parse(
        self,
        obs: AgentObservation,
        step: int,
        spawn_pos: tuple[int, int],
    ) -> tuple[StateSnapshot, dict[tuple[int, int], Entity]]:
        """Parse observation into state snapshot and visible entities.

        Args:
            obs: Raw observation
            step: Current tick
            spawn_pos: Agent's spawn position for offset calculation

        Returns:
            (state_snapshot, visible_entities_dict)
        """
        state = StateSnapshot()

        # Read center cell for inventory/vibe and local position
        inv: dict[str, int] = {}
        vibe_id = 0
        # Local position tokens: lp:east/west for col offset, lp:north/south for row offset
        lp_col_offset = 0  # east is positive, west is negative
        lp_row_offset = 0  # south is positive, north is negative
        has_position = False

        center_r, center_c = self._obs_hr, self._obs_wr

        for tok in obs.tokens:
            feature_name = tok.feature.name
            loc = tok.location
            token_value_base = max(int(tok.feature.normalization), 1)
            if loc is None:
                # Global observations don't have a spatial location.
                if feature_name == "vibe":
                    vibe_id = tok.value
                elif feature_name == "lp:east":
                    lp_col_offset = tok.value
                    has_position = True
                elif feature_name == "lp:west":
                    lp_col_offset = -tok.value
                    has_position = True
                elif feature_name == "lp:south":
                    lp_row_offset = tok.value
                    has_position = True
                elif feature_name == "lp:north":
                    lp_row_offset = -tok.value
                    has_position = True
                elif feature_name.startswith("inv:"):
                    add_inventory_token(inv, feature_name, tok.value, token_value_base=token_value_base)
                continue

            if loc.row == center_r and loc.col == center_c:
                if feature_name.startswith("inv:"):
                    add_inventory_token(inv, feature_name, tok.value, token_value_base=token_value_base)
                elif feature_name == "vibe":
                    vibe_id = tok.value
                # Local position tokens from local_position observation feature (older encodings)
                elif feature_name == "lp:east":
                    lp_col_offset = tok.value
                    has_position = True
                elif feature_name == "lp:west":
                    lp_col_offset = -tok.value
                    has_position = True
                elif feature_name == "lp:south":
                    lp_row_offset = tok.value
                    has_position = True
                elif feature_name == "lp:north":
                    lp_row_offset = -tok.value
                    has_position = True

        # Build state - lp: tokens give offset from spawn
        if has_position:
            state.position = (spawn_pos[0] + lp_row_offset, spawn_pos[1] + lp_col_offset)
        else:
            state.position = spawn_pos

        state.hp = inv.get("hp", 100)
        state.energy = inv.get("energy", 100)
        state.carbon = inv.get("carbon", 0)
        state.oxygen = inv.get("oxygen", 0)
        state.germanium = inv.get("germanium", 0)
        state.silicon = inv.get("silicon", 0)
        state.heart = inv.get("heart", 0)
        state.influence = inv.get("influence", 0)
        state.miner_gear = inv.get("miner", 0) > 0
        state.scout_gear = inv.get("scout", 0) > 0
        state.aligner_gear = inv.get("aligner", 0) > 0
        state.scrambler_gear = inv.get("scrambler", 0) > 0
        state.vibe = self._get_vibe_name(vibe_id)

        # Team hub inventory is exposed via team:<resource> global obs tokens.
        team_inv: dict[str, int] = {}
        for tok in obs.tokens:
            feature_name = tok.feature.name
            if not feature_name.startswith("team:"):
                continue
            loc = tok.location
            if loc is not None:
                continue
            resource_name = feature_name[5:]
            resource_name, power = split_power_suffix(resource_name)
            token_value_base = max(int(tok.feature.normalization), 1)
            team_inv[resource_name] = team_inv.get(resource_name, 0) + tok.value * (token_value_base**power)

        state.team_carbon = team_inv.get("carbon", 0)
        state.team_oxygen = team_inv.get("oxygen", 0)
        state.team_germanium = team_inv.get("germanium", 0)
        state.team_silicon = team_inv.get("silicon", 0)
        state.team_heart = team_inv.get("heart", 0)
        state.team_influence = team_inv.get("influence", 0)

        # Parse visible entities
        visible_entities: dict[tuple[int, int], Entity] = {}
        position_features: dict[tuple[int, int], dict] = {}

        for tok in obs.tokens:
            loc = tok.location
            if loc is None:
                continue

            obs_r, obs_c = loc.row, loc.col
            # Skip center cell
            if obs_r == center_r and obs_c == center_c:
                continue

            world_r = obs_r - self._obs_hr + state.position[0]
            world_c = obs_c - self._obs_wr + state.position[1]
            world_pos = (world_r, world_c)

            if world_pos not in position_features:
                position_features[world_pos] = {"tags": [], "props": {}}

            feature_name = tok.feature.name
            if feature_name == "tag":
                position_features[world_pos]["tags"].append(tok.value)
            elif feature_name.startswith("inv:"):
                inv_dict = position_features[world_pos].setdefault("inventory", {})
                token_value_base = max(int(tok.feature.normalization), 1)
                add_inventory_token(inv_dict, feature_name, tok.value, token_value_base=token_value_base)

        # Convert to entities
        for world_pos, features in position_features.items():
            tags = features.get("tags", [])
            if not tags:
                continue

            obj_name = self._resolve_object_name(tags)
            if obj_name == "unknown":
                continue

            props = dict(features.get("props", {}))
            inv_data = features.get("inventory")

            resolved_tags = [self._tag_names.get(tid, "") for tid in tags]
            alignment = self._derive_alignment(obj_name, resolved_tags)
            if alignment:
                props["alignment"] = alignment

            # Inventory amount for extractors
            if inv_data:
                props["inventory_amount"] = sum(inv_data.values())
                props["has_inventory"] = True
            else:
                props.setdefault("inventory_amount", -1)

            visible_entities[world_pos] = Entity(
                type=obj_name,
                properties=props,
                last_seen=step,
            )

        return state, visible_entities

    def _resolve_object_name(self, tag_ids: list[int]) -> str:
        """Resolve tag IDs to an object name."""
        resolved = [self._tag_names.get(tid, "") for tid in tag_ids]

        # Priority: type:* tags
        for tag in resolved:
            if tag.startswith("type:"):
                return tag[5:]

        for tag in resolved:
            if tag and not tag.startswith(("team:", "net:")):
                return tag

        return "unknown"

    def _get_vibe_name(self, vibe_id: int) -> str:
        if 0 <= vibe_id < len(self._vibe_names):
            return self._vibe_names[vibe_id]
        return "default"

    def _derive_alignment(self, obj_name: str, tags: list[str]) -> str | None:
        for tag in tags:
            if tag in ("team:cogs", "net:cogs"):
                return "cogs"
            if tag in ("team:clips", "net:clips"):
                return "clips"
        if "c:" in obj_name:
            return "cogs"
        if "clips" in obj_name:
            return "clips"
        return None

    @property
    def obs_half_height(self) -> int:
        return self._obs_hr

    @property
    def obs_half_width(self) -> int:
        return self._obs_wr
