"""Observation parser for the Overcogged scripted policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .entity_map import Entity

if TYPE_CHECKING:
    from mettagrid.policy.policy_env_interface import PolicyEnvInterface
    from mettagrid.simulator.interface import AgentObservation


@dataclass
class OvercookedObservationState:
    position: tuple[int, int] = (0, 0)
    inventory: dict[str, int] = field(default_factory=dict)


class ObsParser:
    def __init__(self, pei: PolicyEnvInterface) -> None:
        self._hr = pei.obs_height // 2
        self._wr = pei.obs_width // 2
        self._tags = pei.tag_id_to_name

    @property
    def obs_half_h(self) -> int:
        return self._hr

    @property
    def obs_half_w(self) -> int:
        return self._wr

    def parse(
        self,
        obs: AgentObservation,
        *,
        fallback_position: tuple[int, int],
    ) -> tuple[OvercookedObservationState, dict[tuple[int, int], Entity]]:
        state = OvercookedObservationState(position=fallback_position)
        row_off = col_off = 0
        has_position = False
        center_row, center_col = self._hr, self._wr

        for tok in obs.tokens:
            feature_name = tok.feature.name
            loc = tok.location

            if loc is None:
                if feature_name.startswith("lp:"):
                    has_position, row_off, col_off = self._parse_local_position(
                        feature_name[3:], tok.value, row_off, col_off
                    )
                elif feature_name.startswith("inv:"):
                    _accum_inv(state.inventory, feature_name[4:], tok.value)
                continue

            if loc.row == center_row and loc.col == center_col:
                if feature_name.startswith("inv:"):
                    _accum_inv(state.inventory, feature_name[4:], tok.value)
                elif feature_name.startswith("lp:"):
                    has_position, row_off, col_off = self._parse_local_position(
                        feature_name[3:], tok.value, row_off, col_off
                    )

        if has_position:
            state.position = (row_off, col_off)

        cell_data: dict[tuple[int, int], dict] = {}
        for tok in obs.tokens:
            loc = tok.location
            if loc is None or (loc.row == center_row and loc.col == center_col):
                continue

            world_row = loc.row - self._hr + state.position[0]
            world_col = loc.col - self._wr + state.position[1]
            world_pos = (world_row, world_col)
            if world_pos not in cell_data:
                cell_data[world_pos] = {"tags": [], "inv": {}}

            feature_name = tok.feature.name
            if feature_name == "tag":
                cell_data[world_pos]["tags"].append(tok.value)
            elif feature_name.startswith("inv:"):
                _accum_inv(cell_data[world_pos]["inv"], feature_name[4:], tok.value)

        visible: dict[tuple[int, int], Entity] = {}
        for world_pos, data in cell_data.items():
            if not data["tags"]:
                continue
            obj_type = self._resolve_type(data["tags"])
            if obj_type == "unknown":
                continue
            visible[world_pos] = Entity(type=obj_type, properties=data["inv"])

        return state, visible

    def _parse_local_position(
        self,
        direction: str,
        value: int,
        row_off: int,
        col_off: int,
    ) -> tuple[bool, int, int]:
        if direction == "east":
            return True, row_off, value
        if direction == "west":
            return True, row_off, -value
        if direction == "south":
            return True, value, col_off
        if direction == "north":
            return True, -value, col_off
        return False, row_off, col_off

    def _resolve_type(self, tag_ids: list[int]) -> str:
        for tag_id in tag_ids:
            name = self._tags.get(tag_id, "")
            if name.startswith("type:"):
                return name[5:]
        return "unknown"


def _accum_inv(inv: dict[str, int], suffix: str, value: int) -> None:
    if ":p" in suffix:
        base, power = suffix.rsplit(":p", 1)
        inv[base] = inv.get(base, 0) + value * (256 ** int(power))
    else:
        inv[suffix] = inv.get(suffix, 0) + value
