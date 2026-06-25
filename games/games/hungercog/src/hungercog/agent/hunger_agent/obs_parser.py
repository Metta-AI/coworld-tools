"""Observation parser for the Hunger agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .entity_map import Entity

if TYPE_CHECKING:
    from mettagrid.policy.policy_env_interface import PolicyEnvInterface
    from mettagrid.simulator.interface import AgentObservation


@dataclass
class HungerState:
    """Rebuilt every tick from observation tokens."""

    position: tuple[int, int] = (0, 0)
    food: int = 20
    energy: int = 100
    solar: int = 1
    carnivore: int = 0
    herbivore: int = 0
    egg: int = 0

    @property
    def has_gear(self) -> bool:
        return self.carnivore > 0 or self.herbivore > 0

    @property
    def is_predator(self) -> bool:
        return self.carnivore > 0

    @property
    def is_prey(self) -> bool:
        return self.herbivore > 0


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
        self, obs: AgentObservation, step: int, spawn: tuple[int, int]
    ) -> tuple[HungerState, dict[tuple[int, int], Entity]]:
        state = HungerState()
        inv: dict[str, int] = {}
        row_off = col_off = 0
        has_pos = False
        cr, cc = self._hr, self._wr

        # First pass: extract self inventory and position
        for tok in obs.tokens:
            fn = tok.feature.name
            loc = tok.location

            if loc is None:
                if fn.startswith("lp:"):
                    has_pos, row_off, col_off = self._parse_lp(fn[3:], tok.value, row_off, col_off)
                elif fn.startswith("inv:"):
                    _accum_inv(inv, fn[4:], tok.value)
                continue

            if loc.row == cr and loc.col == cc:
                if fn.startswith("inv:"):
                    _accum_inv(inv, fn[4:], tok.value)
                elif fn.startswith("lp:"):
                    has_pos, row_off, col_off = self._parse_lp(fn[3:], tok.value, row_off, col_off)

        state.position = (spawn[0] + row_off, spawn[1] + col_off) if has_pos else spawn
        state.food = inv.get("food", 20)
        state.energy = inv.get("energy", 100)
        state.solar = inv.get("solar", 1)
        state.carnivore = inv.get("carnivore", 0)
        state.herbivore = inv.get("herbivore", 0)
        state.egg = inv.get("egg", 0)

        # Second pass: extract visible entities
        cell_data: dict[tuple[int, int], dict] = {}
        for tok in obs.tokens:
            loc = tok.location
            if loc is None or (loc.row == cr and loc.col == cc):
                continue
            wr = loc.row - self._hr + state.position[0]
            wc = loc.col - self._wr + state.position[1]
            wp = (wr, wc)
            if wp not in cell_data:
                cell_data[wp] = {"tags": [], "inv": {}}
            fn = tok.feature.name
            if fn == "tag":
                cell_data[wp]["tags"].append(tok.value)
            elif fn.startswith("inv:"):
                _accum_inv(cell_data[wp]["inv"], fn[4:], tok.value)

        visible: dict[tuple[int, int], Entity] = {}
        for wp, data in cell_data.items():
            if not data["tags"]:
                continue
            obj_type = self._resolve_type(data["tags"])
            if obj_type == "unknown":
                continue
            props: dict = {}
            if data["inv"]:
                props.update(data["inv"])
            visible[wp] = Entity(type=obj_type, properties=props, last_seen=step)

        return state, visible

    def _parse_lp(self, direction: str, value: int, row_off: int, col_off: int) -> tuple[bool, int, int]:
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
        for tid in tag_ids:
            name = self._tags.get(tid, "")
            if name.startswith("type:"):
                return name[5:]
        for tid in tag_ids:
            name = self._tags.get(tid, "")
            if name and not name.startswith(("team:", "net:", "collective:")):
                return name
        return "unknown"


def _accum_inv(inv: dict[str, int], suffix: str, value: int) -> None:
    if ":p" in suffix:
        base, ps = suffix.rsplit(":p", 1)
        inv[base] = inv.get(base, 0) + value * (256 ** int(ps))
    else:
        inv[suffix] = inv.get(suffix, 0) + value
