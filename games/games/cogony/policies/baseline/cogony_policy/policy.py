"""Baseline Cogony policy: mine extractors, sell cargo, upgrade subsystems."""

from __future__ import annotations

import random
from dataclasses import dataclass

from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent.runtime.observation import (
    DecodedObservation,
    ObservationCell,
    ObservationEnvelope,
    decode_observation,
)
from mettagrid.simulator import Action, AgentObservation

ELEMENTS = ["carbon", "oxygen", "germanium", "silicon"]
GEAR_STATS = ["core_a", "core_d", "os_a", "os_d", "gen_a", "gen_d", "storage_a", "storage_d"]
ATK_STATS = ["core_a", "os_a", "gen_a", "storage_a"]
DEF_STATS = ["core_d", "os_d", "gen_d", "storage_d"]
CHANNELS = list(zip(ATK_STATS, DEF_STATS))


def _inv(cell: ObservationCell, key: str) -> int:
    return cell.features.get(f"inv:{key}", 0)


def _type_tag(cell: ObservationCell) -> str:
    for t in cell.tags:
        if t.startswith("type:"):
            return t[5:]
    return ""


def _move_toward(dr: int, dc: int, alt: bool = False) -> str:
    if alt:
        if abs(dr) < abs(dc):
            return "move_north" if dr < 0 else "move_south"
        return "move_west" if dc < 0 else "move_east"
    if abs(dr) >= abs(dc):
        return "move_north" if dr < 0 else "move_south"
    return "move_west" if dc < 0 else "move_east"


def _gear_cost(gear_held: int) -> int:
    return 1 << (2 + gear_held)


@dataclass
class CombatResult:
    my_dps: int
    their_dps: int
    hits_to_kill: int
    hits_to_die: int
    i_win: bool
    coh_cost: int


def _combat_eval(me: ObservationCell, target: ObservationCell) -> CombatResult:
    my_dps = their_dps = 0
    for atk, def_ in CHANNELS:
        my_dps += max(0, _inv(me, atk) - _inv(target, def_))
        their_dps += max(0, _inv(target, atk) - _inv(me, def_))
    target_coh = max(_inv(target, "coherence"), 1)
    my_coh = max(_inv(me, "coherence"), 1)
    hits_to_kill = (target_coh + max(my_dps, 1) - 1) // max(my_dps, 1) if my_dps > 0 else 9999
    hits_to_die = (my_coh + max(their_dps, 1) - 1) // max(their_dps, 1) if their_dps > 0 else 9999
    i_win = hits_to_kill < hits_to_die or (hits_to_kill == hits_to_die and my_dps >= their_dps)
    coh_cost = min(their_dps * hits_to_kill, my_coh)
    return CombatResult(my_dps, their_dps, hits_to_kill, hits_to_die, i_win, coh_cost)


@dataclass
class AgentState:
    current_vibe: str = "default"
    wander_dir: str = "move_east"
    wander_steps: int = 0
    last_row: int = -1
    last_col: int = -1
    stuck_count: int = 0
    flee_ticks: int = 0
    flee_dir: str = ""
    recent_positions: list = None
    oscillating: bool = False

    def __post_init__(self):
        if self.recent_positions is None:
            self.recent_positions = []


class CogonyAgentPolicy(AgentPolicy):

    def __init__(self, policy_env_info: PolicyEnvInterface, agent_id: int):
        super().__init__(policy_env_info)
        self._agent_id = agent_id
        self._st = AgentState()
        self._step = 0
        self._infos: dict = {}
        self._last_decoded: DecodedObservation | None = None

    @property
    def infos(self) -> dict:
        return self._infos

    def _info(self, goal: str, dr: int = 0, dc: int = 0, **kw) -> None:
        d: dict = {"role": "baseline", "goal": goal, **kw}
        if dr != 0 or dc != 0:
            d["target"] = f"{dr},{dc}"
        self._infos = d

    def step(self, obs: AgentObservation) -> Action:
        self._step += 1
        decoded = decode_observation(
            ObservationEnvelope(raw_observation=obs, policy_env_info=self.policy_env_info, step=self._step)
        )
        self._last_decoded = decoded
        me = decoded.self_cell
        cr, cc = decoded.center_row, decoded.center_col

        if (cr, cc) == (self._st.last_row, self._st.last_col):
            self._st.stuck_count += 1
        else:
            self._st.stuck_count = 0
        self._st.last_row, self._st.last_col = cr, cc

        # Track recent positions to detect oscillation.
        self._st.recent_positions.append((cr, cc))
        if len(self._st.recent_positions) > 10:
            self._st.recent_positions.pop(0)
        self._st.oscillating = (
            len(self._st.recent_positions) >= 8 and
            len(set(self._st.recent_positions[-8:])) <= 2
        )

        my_coh = _inv(me, "coherence")
        if my_coh == 0:
            self._info("rebooting")
            return Action(name="noop")

        # Oscillation breakout: force random walk for several ticks.
        if self._st.oscillating:
            self._st.flee_ticks = random.randint(5, 12)
            self._st.oscillating = False
            self._st.recent_positions.clear()

        # Committed wander (breakout or withdraw).
        if self._st.flee_ticks > 0:
            self._st.flee_ticks -= 1
            open_dirs = self._open_dirs(decoded, cr, cc)
            # Each tick: pick a random open direction (true random walk).
            d = random.choice(open_dirs)
            return Action(name=d)

        creds = _inv(me, "creds")
        cargo = sum(_inv(me, e) for e in ELEMENTS)
        gear_held = sum(_inv(me, g) for g in GEAR_STATS)
        can_afford_gear = creds >= _gear_cost(gear_held)
        total_atk = sum(_inv(me, a) for a in ATK_STATS)
        self._open = self._open_dirs(decoded, cr, cc)

        # 1. Opportunistic buy/sell when adjacent.
        a = self._adjacent_opportunity(decoded, cr, cc, me, can_afford_gear, cargo > 0, gear_held)
        if a:
            return a

        max_cargo = max(_inv(me, "max_cargo"), 1)
        cargo_pct = cargo * 100 // max_cargo

        # 2. Sell cargo when near full.
        if cargo_pct >= 80:
            a = self._goto(decoded, cr, cc, lambda c: _type_tag(c) == "market_station", "sell")
            if a:
                return a

        # 3. Collect from dead extractors.
        a = self._collect(decoded, cr, cc)
        if a:
            return a

        # 4. Mine live extractors.
        a = self._mine(decoded, cr, cc, me, my_coh)
        if a:
            return a

        # 5. Sell any remaining cargo.
        if cargo > 0:
            a = self._goto(decoded, cr, cc, lambda c: _type_tag(c) == "market_station", "sell")
            if a:
                return a

        # 5. Buy gear if affordable.
        if can_afford_gear:
            a = self._goto_gear(decoded, cr, cc, gear_held)
            if a:
                return a

        # 6. Explore.
        self._info("explore")
        return self._wander_with_obs(decoded, cr, cc)

    def _find(self, decoded, cr, cc, match):
        best, best_dr, best_dc, best_dist = None, 0, 0, 999
        for (r, c), cell in decoded.cells_by_location.items():
            if not match(cell):
                continue
            dr, dc = r - cr, c - cc
            d = abs(dr) + abs(dc)
            if 0 < d < best_dist:
                best, best_dr, best_dc, best_dist = cell, dr, dc, d
        return best, best_dr, best_dc

    def _vibe(self, v: str) -> Action | None:
        if self._st.current_vibe != v:
            self._st.current_vibe = v
            return Action(name=f"change_vibe_{v}")
        return None

    def _move(self, dr: int, dc: int) -> Action:
        preferred = _move_toward(dr, dc, self._st.stuck_count >= 2)
        if preferred not in self._open:
            alt = _move_toward(dr, dc, not (self._st.stuck_count >= 2))
            if alt in self._open:
                return Action(name=alt)
        return Action(name=preferred)

    def _open_dirs(self, decoded, cr, cc) -> list[str]:
        dirs = []
        for name, dr, dc in [("move_north", -1, 0), ("move_south", 1, 0),
                              ("move_west", 0, -1), ("move_east", 0, 1)]:
            cell = decoded.cells_by_location.get((cr + dr, cc + dc))
            if cell is None or _type_tag(cell) != "wall":
                dirs.append(name)
        return dirs if dirs else ["move_north", "move_south", "move_east", "move_west"]

    def _adjacent_opportunity(self, decoded, cr, cc, me, can_buy, has_cargo, gear_held):
        for (r, c), cell in decoded.cells_by_location.items():
            dr, dc = r - cr, c - cc
            if abs(dr) + abs(dc) != 1:
                continue
            t = _type_tag(cell)
            if can_buy and any(g + "_st" in t for g in GEAR_STATS):
                self._info(f"buy({_gear_cost(gear_held)})", dr, dc)
                v = self._vibe("default")
                return v if v else self._move(dr, dc)
            if has_cargo and t == "market_station":
                self._info("sell", dr, dc)
                v = self._vibe("default")
                return v if v else self._move(dr, dc)
        return None

    def _collect(self, decoded, cr, cc):
        target, dr, dc = self._find(decoded, cr, cc,
            lambda c: "extractor" in _type_tag(c) and _inv(c, "coherence") == 0)
        if target is None:
            return None
        self._info("collect", dr, dc)
        if abs(dr) + abs(dc) == 1:
            v = self._vibe("default")
            if v:
                return v
        return self._move(dr, dc)

    def _mine(self, decoded, cr, cc, me, my_coh):
        candidates = []
        for (r, c), cell in decoded.cells_by_location.items():
            if "extractor" not in _type_tag(cell):
                continue
            if _inv(cell, "coherence") <= 0:
                continue
            dr, dc = r - cr, c - cc
            dist = abs(dr) + abs(dc)
            if dist == 0:
                continue
            ev = _combat_eval(me, cell)
            if ev.my_dps == 0:
                continue
            candidates.append((ev, dist, dr, dc))

        if not candidates:
            return None

        # Sort: winnable first, then cheapest, then closest.
        candidates.sort(key=lambda x: (not x[0].i_win, x[0].coh_cost, x[1]))
        ev, dist, dr, dc = candidates[0]

        if not ev.i_win:
            # Withdraw: flee away for a while.
            self._info("withdraw", dr, dc, dps=ev.my_dps, take=ev.their_dps)
            flee_dir = _move_toward(-dr, -dc)
            self._st.flee_dir = flee_dir
            self._st.flee_ticks = random.randint(8, 20)
            return Action(name=flee_dir)

        self._info("mine", dr, dc, dps=ev.my_dps, hits=ev.hits_to_kill, cost=ev.coh_cost)
        if dist == 1:
            v = self._vibe("attack")
            if v:
                return v
        return self._move(dr, dc)

    def _goto_gear(self, decoded, cr, cc, gear_held):
        def is_gear_station(cell):
            t = _type_tag(cell)
            return any(g + "_st" in t for g in GEAR_STATS)
        target, dr, dc = self._find(decoded, cr, cc, is_gear_station)
        if target is None:
            return None
        self._info(f"gear({_gear_cost(gear_held)})", dr, dc)
        return self._move(dr, dc)

    def _goto(self, decoded, cr, cc, match, goal):
        target, dr, dc = self._find(decoded, cr, cc, match)
        if target is None:
            return None
        self._info(goal, dr, dc)
        if abs(dr) + abs(dc) == 1:
            v = self._vibe("default")
            if v:
                return v
        return self._move(dr, dc)

    def _wander_with_obs(self, decoded, cr, cc) -> Action:
        open_dirs = self._open_dirs(decoded, cr, cc)
        if self._st.stuck_count > 2 or self._st.wander_steps <= 0 or self._st.wander_dir not in open_dirs:
            self._st.wander_dir = random.choice(open_dirs)
            self._st.wander_steps = random.randint(8, 25)
            self._st.stuck_count = 0
        self._st.wander_steps -= 1
        return Action(name=self._st.wander_dir)

    def reset(self) -> None:
        self._st = AgentState()
        self._step = 0


class CogonyPolicy(MultiAgentPolicy):
    short_names = ["cogony", "cogony-baseline"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **kwargs):
        super().__init__(policy_env_info, device=device)
        self._agents: dict[int, CogonyAgentPolicy] = {}

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        if agent_id not in self._agents:
            self._agents[agent_id] = CogonyAgentPolicy(self._policy_env_info, agent_id)
        return self._agents[agent_id]
