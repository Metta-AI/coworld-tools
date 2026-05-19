"""Toolsy: async LLM policy. LLM runs in a background thread, tools
produce actions consumed by step() each tick."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, AgentObservation

from toolsy_policy.goals import (
    active_goals_text as _active_goals_text,
    clean_goal_text as _clean_goal_text,
    goal_lines as _goal_lines,
    normalize_goal_tasks as _normalize_goal_tasks,
    public_goal_tasks as _public_goal_tasks,
)
from toolsy_policy.obs import EntityInfo, GameView, WorldMap, decode_view
from toolsy_policy.tools import (
    BLOCKING_TOOLS,
    INSTANT_TOOLS,
    TOOL_DESCRIPTIONS,
    ToolResult,
    _combat_eval_entity,
    _move_toward,
    _open_dirs,
    _refresh_entity,
    _step_toward_entity,
    _step_toward_coord,
    _use_target,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

ATTACK_GEAR_PRIORITY = ["core_a", "os_a", "gen_a", "storage_a"]
NODE_PRIORITY = ["datacenter", "observatory", "junction"]
NODE_REVENUE = {"datacenter": 100, "observatory": 50, "junction": 10}
HEART_RUN_STEP = 7500
LLM_REQUEST_TIMEOUT_SECONDS = 30.0

SYSTEM_PROMPT = """\
You are controlling a Cog in the game Cogony. Your goal is to accumulate hearts (victory points).

Getting started:
1. You spawn at the hub inside a walled compound. Use explore_compound() to map it out first.
2. The compound contains gear stations, market, heart altar, and stake stations.
3. Use join_team() to bump the hub — this joins the local team, heals you, and claims dividends.
4. Upgrade attack subsystems FIRST — you need attack power to kill extractors.
5. Decide: go broad (spread upgrades across attack channels) or narrow (stack one channel high).
   Narrow is cheaper early; broad is better against varied defenses.
6. Once you have attack gear, leave the compound to find extractors in the outer map.

The game loop (once you have attack gear):
1. Mine extractors to get cargo (carbon, oxygen, germanium, silicon)
2. Sell cargo at the market for creds
3. Buy more gear or hearts (100 creds each) at the heart altar
4. Stronger gear lets you mine faster and survive combat

Teams & staking:
- Bumping a hub joins that team, heals to full, and claims pending dividends.
- Buy stakes at the stake_buy_station (costs 10*n creds for the nth stake via bonding curve).
- Sell stakes at the stake_sell_station (refunds 10*s creds for your sth stake).
- Every 100 ticks, territory income is distributed: 30% to champion (most stakes), 70% to all stakers.
- Income = 10 per aligned junction + 50 per observatory + 100 per datacenter.

Aligning territory:
- Junctions, observatories, and datacenters can be aligned to your team.
- To align: bump a disabled one (coherence=0) with default vibe while on a team.
- You must be within 25 tiles of an existing aligned entity in your network.
- Attack a live junction to disable it first, then bump it again to align.

Key mechanics:
- Bumping an extractor with attack vibe deals damage. Kill it to get element drops.
- Bumping a dead extractor with default vibe collects the dropped elements.
- Bumping a gear station buys +1 to that subsystem (costs 2^(2+total_gear) creds).
- Bumping the market sells one element for creds. Price varies by rarity.
- You have 4 attack channels and 4 defense channels. Damage = max(0, my_atk - their_def) per channel.
- If coherence reaches 0, you reboot after a countdown.

Strategy tips:
- Explore the compound first to locate gear stations, market, altar, and stake stations.
- Join your team early for healing and dividends.
- Upgrade attack before venturing out — without it, extractors regenerate faster than you deal damage.
- Check combat_eval before attacking to make sure you can win.
- Sell cargo at market when nearly full.
- Buy stakes when you have spare creds — dividends are passive income.
- Align nearby junctions to grow your team's territory and income.
- Save up 100 creds for hearts once you have enough gear.

Tools (instant — return immediately):
  status()                                       — Your team, coherence, energy, creds, hearts, cargo, gear.
  nearby(max_entities=12)                        — Visible entities sorted by distance.
  find(type_contains, max_results=4, max_distance=20) — Find entities by type substring. E.g. find("extractor"), find("market"), find("_st") for gear stations, find("junction").
  combat_eval(dr, dc)                            — Evaluate combat vs entity at relative offset (dr,dc). Shows DPS, hits to kill, win/loss.
  gear_cost()                                    — Current gear count and cost of next upgrade.
  set_autopilocy(name="explore_compound", timeout=10) — Set current autopilocy. Timeout is optional.
  add_goal(goals=[...])                          — Add one or more active goals to the checklist.
  complete_goal(goal_id="", goal="")             — Mark one active goal complete so it leaves future prompts.
  update_goal(goal_id, text)                     — Update one active goal when the strategy changes.

Re-evaluate goals:
- At the start of each turn, review the active goals checklist.
- If an active goal is done, call complete_goal. Completed goals are omitted from future prompts.
- If a goal is stale or too vague, call update_goal before choosing an action policy.
- If a new goal is missing from the checklist, call add_goal(goals=[...]).

Autopilocy names:
  goto, explore, explore_compound, mine, use, collect, wait, join_team, align, go_to_spawn.

Only one autopilocy is active at a time. Calling set_autopilocy immediately overrides
the previous one. When the autopilocy completes or its timeout expires, it becomes Noop()
until you set another autopilocy.
"""

ADD_GOAL_TOOL_DESCRIPTION = {
    "name": "add_goal",
    "description": (
        "Add one or more active macro-strategy goals to the checklist included in future turns. "
        "Pass goals as a list of strings. Existing and completed goals are not duplicated. "
        "This does not move the cog; call an action policy tool separately."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "goals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Active strategy goals, one string per goal",
            },
        },
        "required": [],
    },
}

SET_AUTOPILOCY_TOOL_DESCRIPTION = {
    "name": "set_autopilocy",
    "description": (
        "Set the current autopilocy that will choose actions every tick until it completes or times out. "
        "Calling this replaces any current autopilocy. Timeout is optional."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": list(BLOCKING_TOOLS),
                "description": "Autopilocy to run",
            },
            "timeout": {
                "type": "integer",
                "description": "Optional maximum ticks before reverting to Noop()",
            },
            "type_contains": {
                "type": "string",
                "description": "Target type for goto, mine, use, or align autopilocy",
            },
            "team": {
                "type": "string",
                "description": "Optional requested team label for join_team",
            },
            "no_loot": {
                "type": "boolean",
                "description": "For mine autopilocy, skip collection after kill",
            },
        },
        "required": ["name"],
    },
}

COMPLETE_GOAL_TOOL_DESCRIPTION = {
    "name": "complete_goal",
    "description": (
        "Mark one active goal complete. Completed goals move to the diary and are omitted from future prompts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "Goal id from the Re-evaluate goals section"},
            "goal": {"type": "string", "description": "Goal text to complete if the id is unknown"},
        },
        "required": [],
    },
}

UPDATE_GOAL_TOOL_DESCRIPTION = {
    "name": "update_goal",
    "description": "Update one active goal when it is stale, too vague, or needs a sharper next objective.",
    "input_schema": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "Goal id from the Re-evaluate goals section"},
            "text": {"type": "string", "description": "Replacement active goal text"},
            "goal": {"type": "string", "description": "Alias for text"},
        },
        "required": ["goal_id"],
    },
}


class AutoPilocy:
    """Per-tick action driver for a Toolsy agent."""

    def __init__(self, name: str, timeout: int | None = None):
        self.name = name
        self.timeout = timeout
        self.ticks_used = 0

    @property
    def active(self) -> bool:
        return True

    @property
    def state(self) -> str:
        return "running"

    def status(self) -> dict:
        remaining = None
        if self.timeout is not None:
            remaining = max(self.timeout - self.ticks_used, 0)
        return {
            "name": self.name,
            "active": self.active,
            "state": self.state,
            "ticks_used": self.ticks_used,
            "timeout": self.timeout,
            "remaining": remaining,
        }

    def step(self, view: GameView) -> tuple[Action, ToolResult | None]:
        raise NotImplementedError


class Noop(AutoPilocy):
    def __init__(self):
        super().__init__("Noop")

    @property
    def active(self) -> bool:
        return False

    @property
    def state(self) -> str:
        return "idle"

    def step(self, view: GameView) -> tuple[Action, ToolResult | None]:
        return Action(name="noop"), None


class ToolAutoPilocy(AutoPilocy):
    def __init__(self, name: str, macro, timeout: int | None = None):
        super().__init__(name, timeout)
        self._macro = macro
        self._started = False

    @property
    def state(self) -> str:
        return "running" if self._started else "ready"

    def step(self, view: GameView) -> tuple[Action, ToolResult | None]:
        if self.timeout is not None and self.ticks_used >= self.timeout:
            return Action(name="noop"), ToolResult(False, f"Timed out after {self.timeout} ticks.", self.ticks_used)
        try:
            if self._started:
                action = self._macro.send(view)
            else:
                action = next(self._macro)
                self._started = True
        except StopIteration as e:
            result = e.value
            if result is None:
                result = ToolResult(True, "Complete.", self.ticks_used)
            return Action(name="noop"), result
        self.ticks_used += 1
        if self.timeout is not None and self.ticks_used >= self.timeout:
            return action, ToolResult(False, f"Timed out after {self.timeout} ticks.", self.ticks_used)
        return action, None


class ToolBridge:
    """Synchronization bridge between LLM thread (produces actions via tools)
    and game thread (consumes actions each tick via step()).

    Game thread calls:
        bridge.step(view) -> Action   (each tick)

    LLM thread (inside tool functions) calls:
        bridge.yield_action(action) -> GameView   (blocks until next tick)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._action: Action = Action(name="noop")
        self._view: GameView | None = None
        self._view_ready = threading.Event()
        self._action_ready = threading.Event()
        self._goal: str = "waiting"
        self._stopped = False
        self._had_action = False
        self.current_auto_pilocy: AutoPilocy = Noop()
        self._last_auto_pilocy_result = ""

    def step(self, view: GameView) -> Action:
        """Called by game thread each tick. Provides new view, returns action."""
        with self._lock:
            self._view = view
        self._view_ready.set()
        auto_action, auto_completed = self._step_auto_pilocy(view)
        if auto_action is not None:
            self._had_action = True
            return auto_action
        if auto_completed:
            self._had_action = True
            return Action(name="noop")
        # Wait briefly for an action that was already produced by a triggered LLM turn.
        timeout = 0.05
        has_fresh_action = self._action_ready.wait(timeout=timeout)
        if has_fresh_action:
            self._action_ready.clear()
            self._had_action = True
            auto_action, auto_completed = self._step_auto_pilocy(view)
            if auto_action is not None:
                return auto_action
            if auto_completed:
                return Action(name="noop")
        with self._lock:
            if has_fresh_action:
                return self._action
        return Action(name="noop")

    def yield_action(self, action: Action) -> GameView:
        """Called by tool functions in LLM thread. Sets action, waits for next view."""
        with self._lock:
            self._action = action
        self._action_ready.set()
        # Wait for next game tick.
        self._view_ready.wait()
        self._view_ready.clear()
        with self._lock:
            return self._view

    def get_view(self) -> GameView | None:
        """Get the latest view without blocking."""
        with self._lock:
            return self._view

    def wait_for_view(self) -> GameView:
        """Block until a view is available."""
        self._view_ready.wait()
        self._view_ready.clear()
        with self._lock:
            return self._view

    def wait_for_next_tick(self, current_step: int) -> GameView | None:
        """Block until the simulator reports a different step."""
        while not self._stopped:
            view = self.wait_for_view()
            if self._stopped:
                return None
            if view is not None and view.step != current_step:
                return view
        return None

    def set_idle(self):
        """Set action to noop (LLM thinking, no tool active)."""
        with self._lock:
            if not self.current_auto_pilocy.active:
                self._action = Action(name="noop")
        self._action_ready.set()

    def set_autopilocy(self, autopilocy: AutoPilocy) -> None:
        with self._lock:
            self.current_auto_pilocy = autopilocy
            self._last_auto_pilocy_result = ""
            self._goal = autopilocy.name
        self._action_ready.set()

    def _step_auto_pilocy(self, view: GameView) -> tuple[Action | None, bool]:
        with self._lock:
            autopilocy = self.current_auto_pilocy
        if not autopilocy.active:
            return None, False
        action, raw_result = autopilocy.step(view)
        if raw_result is not None:
            result = self._format_auto_pilocy_result(autopilocy.name, raw_result)
            with self._lock:
                if self.current_auto_pilocy is autopilocy:
                    self._last_auto_pilocy_result = result
                    self.current_auto_pilocy = Noop()
                    self._goal = "waiting"
            return action, True
        return action, False

    def _format_auto_pilocy_result(self, name: str, result: ToolResult | None) -> str:
        if result is None:
            return f"{name or 'autopilocy'} stopped."
        return f"{name}: {result.message} ({result.ticks_used} ticks)"

    @property
    def active_tool_name(self) -> str:
        with self._lock:
            return self.current_auto_pilocy.name if self.current_auto_pilocy.active else ""

    @property
    def last_tool_result(self) -> str:
        with self._lock:
            return self._last_auto_pilocy_result

    def auto_pilocy_status(self) -> dict:
        with self._lock:
            return self.current_auto_pilocy.status()

    def status_text(self) -> str:
        with self._lock:
            if self.current_auto_pilocy.active:
                return f"Active autopilocy: {self.current_auto_pilocy.name}. set_autopilocy overrides it."
            if self._last_auto_pilocy_result:
                return f"Active autopilocy: Noop. Last result: {self._last_auto_pilocy_result}"
        return "Active autopilocy: Noop."

    @property
    def goal(self) -> str:
        with self._lock:
            return self._goal

    @goal.setter
    def goal(self, value: str):
        with self._lock:
            if value == "thinking" and self.current_auto_pilocy.active:
                return
            self._goal = value

    def stop(self):
        self._stopped = True
        with self._lock:
            self.current_auto_pilocy = Noop()
        self._view_ready.set()
        self._action_ready.set()

    @property
    def stopped(self) -> bool:
        return self._stopped


class ToolsyAgentPolicy(AgentPolicy):
    """Per-agent LLM policy. LLM loop runs in a background thread."""

    def __init__(self, policy_env_info: PolicyEnvInterface, agent_id: int,
                 llm_client: Any | None):
        super().__init__(policy_env_info)
        self._agent_id = agent_id
        self._llm = llm_client
        self._step_num = 0
        self._infos: dict = {}
        self._bridge = ToolBridge()
        self._messages: list[dict] = []
        self._total_llm_calls = 0
        self._thread: threading.Thread | None = None
        self._last_decoded = None
        self._llm_log: list[str] = []
        self._diary: list[dict] = []
        self._last_diary_view: dict | None = None
        self._goals_lock = threading.Lock()
        self._current_goals = ""
        self._goal_tasks: list[dict] = []
        self._next_goal_id = 1
        self._pending_goal_updates: list[tuple[str, str]] = []
        self._llm_trigger_lock = threading.Lock()
        self._llm_trigger_ready = threading.Event()
        self._llm_trigger_id = 0
        self._llm_consumed_trigger_id = 0
        self._last_llm_trigger_source = ""
        self._llm_brain_state = "waiting"
        self._last_auto_llm_step: int | None = None
        self._spawn: tuple[int, int] | None = None
        self._world_map = WorldMap()
        self._infos["llm_system"] = SYSTEM_PROMPT
        self._infos["current_goals"] = self._current_goals
        self._infos["goal_tasks"] = []
        self._sync_llm_brain_info()
        self._sync_auto_pilocy_info()
        self._infos["world_model"] = self._world_map.snapshot(0, 0)

    @property
    def infos(self) -> dict:
        self._infos["policy_widgets"] = self.policy_widgets
        return self._infos

    @property
    def current_auto_pilocy(self) -> AutoPilocy:
        return self._bridge.current_auto_pilocy

    def _llm_brain_info_unlocked(self) -> dict:
        return {
            "state": self._llm_brain_state,
            "last_trigger_id": self._llm_trigger_id,
            "consumed_trigger_id": self._llm_consumed_trigger_id,
            "pending": self._llm_trigger_id > self._llm_consumed_trigger_id,
            "source": self._last_llm_trigger_source,
        }

    def _sync_llm_brain_info(self) -> None:
        with self._llm_trigger_lock:
            self._infos["llm_brain"] = self._llm_brain_info_unlocked()

    def _sync_auto_pilocy_info(self) -> None:
        self._infos["goal"] = self._bridge.goal
        self._infos["active_tool"] = self._bridge.active_tool_name
        self._infos["auto_pilocy"] = self._bridge.auto_pilocy_status()
        self._infos["current_auto_pilocy"] = self._bridge.active_tool_name or "Noop"
        if self._bridge.last_tool_result:
            self._infos["last_tool_result"] = self._bridge.last_tool_result

    def _set_llm_brain_state(self, state: str) -> None:
        with self._llm_trigger_lock:
            self._llm_brain_state = state
            self._infos["llm_brain"] = self._llm_brain_info_unlocked()

    def trigger_llm(self, source: str = "manual") -> int:
        with self._llm_trigger_lock:
            self._llm_trigger_id += 1
            trigger_id = self._llm_trigger_id
            self._last_llm_trigger_source = str(source or "manual")
            if self._llm_brain_state == "waiting":
                self._llm_brain_state = "queued"
            self._infos["llm_brain"] = self._llm_brain_info_unlocked()
        self._llm_trigger_ready.set()
        return trigger_id

    def _trigger_llm_for_new_tick(self, view: GameView) -> None:
        if self._last_auto_llm_step == view.step:
            return
        self._last_auto_llm_step = view.step
        self.trigger_llm(source="tick")

    def _wait_for_llm_trigger(self) -> dict | None:
        while not self._bridge.stopped:
            self._llm_trigger_ready.wait(0.1)
            if self._bridge.stopped:
                return None
            with self._llm_trigger_lock:
                if self._llm_trigger_id > self._llm_consumed_trigger_id:
                    self._llm_consumed_trigger_id = self._llm_trigger_id
                    trigger = {
                        "id": self._llm_consumed_trigger_id,
                        "source": self._last_llm_trigger_source,
                    }
                    self._llm_trigger_ready.clear()
                    self._infos["llm_brain"] = self._llm_brain_info_unlocked()
                    return trigger
                self._llm_trigger_ready.clear()
        return None

    @property
    def policy_widgets(self) -> list[dict]:
        return [
            {"id": "toolsy_autopilocy", "module": "toolsy_autopilocy", "title": "AutoPilocy()", "config": {}},
            {"id": "toolsy_goals", "module": "toolsy_goals", "title": "Goals", "config": {}},
            {"id": "toolsy_diary", "module": "toolsy_diary", "title": "Diary", "config": {}},
            {"id": "toolsy_world_model", "module": "toolsy_world_model", "title": "World Model", "config": {}},
        ]

    @property
    def current_goals(self) -> str:
        with self._goals_lock:
            return self._current_goals

    def _new_goal_id_locked(self) -> str:
        used = {str(task["id"]) for task in self._goal_tasks}
        while True:
            goal_id = f"goal-{self._next_goal_id}"
            self._next_goal_id += 1
            if goal_id not in used:
                return goal_id

    def _sync_goal_infos_locked(self) -> None:
        self._current_goals = _active_goals_text(self._goal_tasks)
        self._infos["current_goals"] = self._current_goals
        self._infos["goal_tasks"] = _public_goal_tasks(self._goal_tasks)

    def update_current_goals(self, prompt: str, source: str = "tool") -> bool:
        goals = _goal_lines(str(prompt or ""))
        with self._goals_lock:
            active = [task for task in self._goal_tasks if not task.get("completed")]
            completed = [task for task in self._goal_tasks if task.get("completed")]
            used_ids: set[str] = set()
            next_active: list[dict] = []
            for goal in goals:
                existing = next(
                    (task for task in active if task["text"] == goal and task["id"] not in used_ids),
                    None,
                )
                goal_id = existing["id"] if existing else self._new_goal_id_locked()
                used_ids.add(goal_id)
                next_active.append({"id": goal_id, "text": goal, "completed": False})
            next_tasks = next_active + completed
            if _public_goal_tasks(next_tasks) == _public_goal_tasks(self._goal_tasks):
                return False
            self._goal_tasks = next_tasks
            self._sync_goal_infos_locked()
            self._pending_goal_updates = [(source, self._current_goals)] if self._current_goals else [(source, "")]
        return True

    def add_current_goals(self, goals: list | str, source: str = "tool") -> bool:
        if isinstance(goals, list):
            goal_lines = [cleaned for goal in goals if (cleaned := _clean_goal_text(goal))]
        else:
            goal_lines = _goal_lines(str(goals or ""))
        if not goal_lines:
            return False
        with self._goals_lock:
            active = [task for task in self._goal_tasks if not task.get("completed")]
            completed = [task for task in self._goal_tasks if task.get("completed")]
            existing_texts = {str(task["text"]) for task in self._goal_tasks}
            changed = False
            for goal in goal_lines:
                if goal in existing_texts:
                    continue
                active.append({"id": self._new_goal_id_locked(), "text": goal, "completed": False})
                existing_texts.add(goal)
                changed = True
            if not changed:
                return False
            self._goal_tasks = active + completed
            self._sync_goal_infos_locked()
            self._pending_goal_updates = [(source, self._current_goals)] if self._current_goals else [(source, "")]
        return True

    def sync_goal_tasks(self, tasks: list[dict], source: str = "widget") -> bool:
        normalized = _normalize_goal_tasks(tasks)
        completed_events: list[str] = []
        with self._goals_lock:
            previous = {str(task["id"]): task for task in self._goal_tasks}
            for task in normalized:
                was_completed = bool(previous.get(str(task["id"]), {}).get("completed"))
                if task["completed"] and not was_completed:
                    completed_events.append(task["text"])
            if _public_goal_tasks(normalized) == _public_goal_tasks(self._goal_tasks):
                return False
            self._goal_tasks = normalized
            self._sync_goal_infos_locked()
        for goal in completed_events:
            self._add_diary_event(f"Completed goal: {goal}")
        return True

    def complete_goal(self, *, goal_id: str = "", goal: str = "") -> bool:
        completed_text = ""
        with self._goals_lock:
            goal_id = str(goal_id or "")
            goal_text = _clean_goal_text(goal)
            for task in self._goal_tasks:
                if task.get("completed"):
                    continue
                if (goal_id and str(task["id"]) == goal_id) or (goal_text and task["text"] == goal_text):
                    task["completed"] = True
                    completed_text = task["text"]
                    break
            if not completed_text:
                return False
            self._pending_goal_updates = []
            self._sync_goal_infos_locked()
        self._add_diary_event(f"Completed goal: {completed_text}")
        return True

    def update_goal(self, *, goal_id: str, text: str, source: str = "tool") -> bool:
        replacement = _clean_goal_text(text)
        if not replacement:
            return False
        with self._goals_lock:
            for task in self._goal_tasks:
                if str(task["id"]) != str(goal_id) or task.get("completed"):
                    continue
                if task["text"] == replacement:
                    return False
                task["text"] = replacement
                self._sync_goal_infos_locked()
                self._pending_goal_updates = [(source, self._current_goals)] if self._current_goals else [(source, "")]
                return True
        return False

    def step(self, obs: AgentObservation) -> Action:
        self._step_num += 1
        spawn = self._spawn or (0, 0)
        view = decode_view(obs, self.policy_env_info, self._step_num,
                           spawn=spawn, world_map=self._world_map)
        return self.step_view(view)

    def step_view(self, view: GameView) -> Action:
        self._step_num = view.step
        if self._spawn is None:
            self._spawn = (view.decoded.center_row, view.decoded.center_col)
        view.spawn_r = self._spawn[0]
        view.spawn_c = self._spawn[1]
        self._last_decoded = view.decoded
        self._update_world_model_info(view)
        self._record_diary_events(view)

        if view.coherence == 0:
            self._infos.update({"role": "toolsy", "goal": "rebooting"})
            return Action(name="noop")

        # Start LLM thread on first step.
        if self._thread is None and self._llm is not None:
            self._thread = threading.Thread(
                target=self._llm_loop, daemon=True, name=f"toolsy-a{self._agent_id}")
            self._thread.start()
        if self._llm is not None:
            self._trigger_llm_for_new_tick(view)

        action = self._bridge.step(view)
        self._sync_auto_pilocy_info()
        return action

    def _entity_key(self, entity) -> tuple:
        row = entity.row if entity.row is not None else entity.dr
        col = entity.col if entity.col is not None else entity.dc
        return (entity.type_name, row, col)

    def _diary_snapshot(self, view: GameView) -> dict:
        return {
            "coherence": view.coherence,
            "creds": view.creds,
            "cargo": dict(view.cargo),
            "gear": dict(view.gear),
            "inventory": dict(view.inventory),
            "entities": {
                self._entity_key(entity): {
                    "type": entity.type_name,
                    "coherence": entity.coherence,
                    "team": getattr(entity, "team", ""),
                }
                for entity in view.entities
            },
        }

    def _add_diary_event(self, event: str) -> None:
        self._diary.append({"step": self._step_num, "event": event})
        self._infos["diary"] = list(self._diary)

    def _update_world_model_info(self, view: GameView) -> None:
        self._infos["world_model"] = view.world_map.snapshot(
            view.decoded.center_row,
            view.decoded.center_col,
        )

    def _record_diary_events(self, view: GameView) -> None:
        current = self._diary_snapshot(view)
        previous = self._last_diary_view
        self._last_diary_view = current
        if previous is None:
            self._infos["diary"] = list(self._diary)
            return

        if previous["coherence"] > 0 and current["coherence"] == 0:
            self._add_diary_event("Lost fight: rebooting")

        for gear_name, current_value in current["gear"].items():
            previous_value = previous["gear"].get(gear_name, 0)
            if current_value > previous_value:
                self._add_diary_event(f"Upgraded {gear_name} to {current_value}")

        creds_delta = current["creds"] - previous["creds"]
        collected = []
        sold = []
        for cargo_name, current_value in current["cargo"].items():
            previous_value = previous["cargo"].get(cargo_name, 0)
            cargo_delta = current_value - previous_value
            if cargo_delta > 0:
                collected.append(f"+{cargo_delta} {cargo_name}")
            elif cargo_delta < 0 and creds_delta > 0:
                sold.append(f"{cargo_delta} {cargo_name}")
        if collected:
            self._add_diary_event(f"Collected cargo: {', '.join(collected)}")
        if sold:
            self._add_diary_event(f"Sold cargo: {', '.join(sold)}, +{creds_delta} creds")

        dividend_names = sorted({
            inv_name for inv_name in [*previous["inventory"].keys(), *current["inventory"].keys()]
            if inv_name.endswith("_dividends")
        })
        for inv_name in dividend_names:
            previous_value = previous["inventory"].get(inv_name, 0)
            current_value = current["inventory"].get(inv_name, 0)
            if not inv_name.endswith("_dividends"):
                continue
            team = inv_name[:-len("_dividends")]
            if current_value > previous_value:
                self._add_diary_event(f"Got dividends: +{current_value - previous_value} from {team}")
            if previous_value > current_value and creds_delta > 0:
                self._add_diary_event(f"Claimed dividends: +{previous_value - current_value} creds from {team}")

        for key, previous_entity in previous["entities"].items():
            current_entity = current["entities"].get(key)
            if current_entity is None:
                continue
            type_name = current_entity["type"]
            previous_team = previous_entity.get("team", "")
            current_team = current_entity.get("team", "")
            if previous_entity["coherence"] > 0 and current_entity["coherence"] == 0:
                self._add_diary_event(f"Won fight: disabled {type_name}")
            if current_team and current_team != previous_team:
                self._add_diary_event(f"Aligned {type_name} to {current_team}")

    # ── LLM thread ────────────────────────────────────────────────

    def _llm_loop(self):
        """Runs in background thread. Calls LLM, dispatches tools."""
        # Wait for first view.
        view = self._bridge.wait_for_view()

        while not self._bridge.stopped:
            if view is None:
                break
            trigger = self._wait_for_llm_trigger()
            if trigger is None:
                break
            latest_view = self._bridge.get_view()
            if latest_view is not None:
                view = latest_view
            try:
                self._set_llm_brain_state("thinking")
                view = self._do_llm_turn(view)
                self._set_llm_brain_state("waiting")
            except Exception as e:
                logger.exception("Toolsy agent %s LLM loop error", self._agent_id)
                self._log(f"LLM ERROR {type(e).__name__}: {str(e)[:200]}")
                self._infos["llm_error"] = str(e)[:200]
                self._bridge.goal = "error"
                self._bridge.set_idle()
                self._set_llm_brain_state("error")
                view = self._bridge.get_view() or view

    def _log(self, *lines: str):
        for line in lines:
            self._llm_log.append(line)
        # Keep last 100 lines.
        if len(self._llm_log) > 100:
            self._llm_log = self._llm_log[-100:]
        self._infos["llm_log"] = "\n".join(self._llm_log[-40:])

    def _fmt_msg(self, msg: dict) -> list[str]:
        """Format a message for logging."""
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            return [f"  {role}: {content}"]
        lines = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("type", "?")
                if t == "text":
                    lines.append(f"  {role}: {block['text']}")
                elif t == "tool_use":
                    args = ", ".join(f"{k}={v!r}" for k, v in block["input"].items())
                    lines.append(f"  {role}: CALL {block['name']}({args})")
                elif t == "tool_result":
                    text = block["content"]
                    lines.append(f"  {role}: RESULT {text[:200]}")
        return lines

    def _separator(self):
        self._log("=" * 50)

    def _divider(self):
        self._log("-" * 50)

    def _consume_goal_updates(self) -> list[str]:
        with self._goals_lock:
            updates = self._pending_goal_updates
            self._pending_goal_updates = []
        messages = []
        for source, goals in updates:
            if goals:
                messages.append(f"Active goals updated by {source}:\n{goals}")
            else:
                messages.append(f"Active goals cleared by {source}.")
        return messages

    def _goals_context_text(self) -> str:
        with self._goals_lock:
            active = [dict(task) for task in self._goal_tasks if not task.get("completed")]
        lines = ["Re-evaluate goals:"]
        if active:
            lines.append("Active goals, one per line. Completed goals are intentionally omitted:")
            for task in active:
                lines.append(f"- {task['id']}: {task['text']}")
            lines.append("If a goal is complete, call complete_goal(goal_id=...).")
            lines.append("If a goal is stale, call update_goal(goal_id=..., text=...).")
            lines.append("If a new goal is missing, call add_goal(goals=[...]).")
        else:
            lines.append("No active goals. If strategy is unclear, call add_goal(goals=[...]) with a short checklist.")
        return "\n".join(lines)

    def _current_context_text(self, view: GameView) -> str:
        context = (
            f"{self._goals_context_text()}\n\n"
            f"Situation:\n"
            f"Step {view.step}. {view.status_text()}\n"
            f"{self._bridge.status_text()}\n"
            "Use set_autopilocy(name=\"explore_compound\", timeout=10) to hand tick-by-tick control to an autopilocy.\n"
            f"Nearby:\n{view.nearby_summary(6)}"
        )
        return context

    def _append_user_context(self, context_blocks: list[dict]) -> None:
        if (self._messages and
                self._messages[-1]["role"] == "user" and
                isinstance(self._messages[-1]["content"], list)):
            self._messages[-1]["content"].extend(context_blocks)
            return
        if len(context_blocks) == 1:
            self._messages.append({"role": "user", "content": context_blocks[0]["text"]})
            return
        self._messages.append({"role": "user", "content": context_blocks})

    def _log_llm_request(self, context_blocks: list[dict]) -> None:
        self._separator()
        self._log(f"LLM CALL #{self._total_llm_calls + 1}  (msgs={len(self._messages)})")
        self._divider()
        for block in context_blocks:
            for line in self._fmt_msg({"role": "user", "content": [block]}):
                self._log(line)
        self._divider()

    def _do_llm_turn(self, view: GameView) -> GameView:
        """One LLM call + tool dispatch. Returns the view after tools complete."""
        context = self._current_context_text(view)
        context_blocks = [
            {"type": "text", "text": update}
            for update in self._consume_goal_updates()
        ]
        context_blocks.append({"type": "text", "text": context})
        self._append_user_context(context_blocks)
        if len(self._messages) > 16:
            content = context_blocks if len(context_blocks) > 1 else context
            self._messages = [{"role": "user", "content": content}]

        self._log_llm_request(context_blocks)

        self._bridge.goal = "thinking"
        t0 = time.time()
        self._total_llm_calls += 1
        response = self._llm.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            tools=self._tool_descriptions(),
            messages=self._messages,
            timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        )
        latency = time.time() - t0

        # Parse response.
        assistant_content = []
        response_text = ""
        tool_blocks = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
                response_text += block.text
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use", "id": block.id,
                    "name": block.name, "input": block.input,
                })
                tool_blocks.append(block)
        self._messages.append({"role": "assistant", "content": assistant_content})

        # Log response.
        tool_str = ""
        if tool_blocks:
            calls = []
            for tool_block in tool_blocks:
                args = ", ".join(f"{k}={v!r}" for k, v in tool_block.input.items())
                calls.append(f"{tool_block.name}({args})")
            tool_str = "; ".join(calls)
        self._log(f"RESPONSE ({latency:.1f}s)")
        if response_text:
            self._log(f"  text: {response_text}")
        if tool_str:
            self._log(f"  tool: {tool_str}")
        self._separator()

        self._infos.update({
            "role": "toolsy",
            "llm_calls": self._total_llm_calls,
            "llm_latency": f"{latency:.1f}s",
            "llm_response": response_text[:200] if response_text else "",
            "llm_tool": tool_str if tool_str else "",
        })

        if tool_blocks:
            results = []
            scheduled_action_policy = False
            for tool_block in tool_blocks:
                view, result = self._dispatch_tool(tool_block.name, tool_block.input, view)
                results.append((tool_block.id, result))
                scheduled_action_policy = scheduled_action_policy or (
                    tool_block.name == "set_autopilocy" and bool(self._bridge.active_tool_name)
                )
            self._add_tool_results(results)
            if scheduled_action_policy:
                return self._wait_for_action_policy_completion(view)
            return view

        self._bridge.set_idle()
        return view

    def _wait_for_action_policy_completion(self, view: GameView) -> GameView:
        current_view = view
        current_step = view.step
        while self._bridge.active_tool_name and not self._bridge.stopped:
            next_view = self._bridge.wait_for_next_tick(current_step)
            if next_view is None:
                return current_view
            current_view = next_view
            current_step = next_view.step
        return current_view

    def _add_tool_result(self, tool_use_id: str, content: str):
        self._add_tool_results([(tool_use_id, content)])

    def _add_tool_results(self, results: list[tuple[str, str]]):
        self._messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
                for tool_use_id, content in results
            ],
        })

    def _autopilocy_timeout(self, raw_timeout: Any) -> int | None:
        if raw_timeout is None or raw_timeout == "":
            return None
        return max(0, int(raw_timeout))

    def _autopilocy_tool_kwargs(self, autopilocy_name: str, kwargs: dict, timeout: int | None) -> dict:
        tool_kwargs = {}
        if "type_contains" in kwargs:
            tool_kwargs["type_contains"] = str(kwargs["type_contains"])
        if autopilocy_name == "join_team":
            tool_kwargs["name"] = str(kwargs.get("team", kwargs.get("target_team", "")))
        if autopilocy_name == "mine" and "no_loot" in kwargs:
            tool_kwargs["no_loot"] = bool(kwargs["no_loot"])
        if timeout is not None:
            if autopilocy_name in {"explore", "wait"}:
                tool_kwargs["num_ticks"] = timeout
            else:
                tool_kwargs["max_ticks"] = timeout
        return tool_kwargs

    def _set_autopilocy(self, view: GameView, kwargs: dict) -> str:
        autopilocy_name = str(kwargs.get("name", kwargs.get("autopilocy", ""))).strip()
        if autopilocy_name == "Noop":
            self._bridge.set_autopilocy(Noop())
            self._sync_auto_pilocy_info()
            return "Set autopilocy Noop."
        if autopilocy_name not in BLOCKING_TOOLS:
            return f"Unknown autopilocy: {autopilocy_name}"
        timeout = self._autopilocy_timeout(kwargs.get("timeout"))
        tool_kwargs = self._autopilocy_tool_kwargs(autopilocy_name, kwargs, timeout)
        macro = BLOCKING_TOOLS[autopilocy_name](view, **tool_kwargs)
        self._bridge.set_autopilocy(ToolAutoPilocy(autopilocy_name, macro, timeout=timeout))
        self._sync_auto_pilocy_info()
        if timeout is None:
            return f"Set autopilocy {autopilocy_name}."
        return f"Set autopilocy {autopilocy_name} for up to {timeout} ticks."

    def _dispatch_tool(self, name: str, args: dict,
                       view: GameView) -> tuple[GameView, str]:
        """Dispatch a tool. Returns the view after the tool completes and result text."""
        kwargs = {k: v for k, v in args.items() if k != "view"}

        if name == "add_goal":
            goals = kwargs.get("goals", kwargs.get("current_goals"))
            if goals is None:
                return view, self.current_goals or "No active goals set."
            changed = self.add_current_goals(goals, source="tool")
            result = "Goals added." if changed else "No new goals added."
            self._infos["llm_result"] = result
            return view, result

        if name == "complete_goal":
            self._step_num = view.step
            ok = self.complete_goal(
                goal_id=str(kwargs.get("goal_id", "")),
                goal=str(kwargs.get("goal", kwargs.get("text", ""))),
            )
            result = "Goal marked complete." if ok else "No matching active goal found."
            self._infos["llm_result"] = result
            return view, result

        if name == "update_goal":
            ok = self.update_goal(
                goal_id=str(kwargs.get("goal_id", "")),
                text=str(kwargs.get("text", kwargs.get("goal", kwargs.get("prompt", "")))),
                source="tool",
            )
            result = "Goal updated." if ok else "No matching active goal updated."
            self._infos["llm_result"] = result
            return view, result

        if name == "set_autopilocy":
            result = self._set_autopilocy(view, kwargs)
            self._log(f"TOOL set_autopilocy => {result}")
            self._infos["llm_result"] = result
            return view, result

        if name in INSTANT_TOOLS:
            result = INSTANT_TOOLS[name](view, **kwargs)
            self._log(f"TOOL {name} => {result}")
            self._infos["llm_result"] = result[:200]
            return view, result

        return view, f"Unknown tool: {name}"

    def _tool_descriptions(self) -> list[dict]:
        instant_tools = [tool for tool in TOOL_DESCRIPTIONS if tool["name"] in INSTANT_TOOLS]
        return [
            ADD_GOAL_TOOL_DESCRIPTION,
            COMPLETE_GOAL_TOOL_DESCRIPTION,
            UPDATE_GOAL_TOOL_DESCRIPTION,
            SET_AUTOPILOCY_TOOL_DESCRIPTION,
            *instant_tools,
        ]

    def reset(self) -> None:
        if self._bridge:
            self._bridge.stop()
        self._bridge = ToolBridge()
        self._messages.clear()
        self._step_num = 0
        self._thread = None
        self._diary.clear()
        self._last_diary_view = None
        self._infos["diary"] = []
        self._world_map = WorldMap()
        self._infos["world_model"] = self._world_map.snapshot(0, 0)
        with self._goals_lock:
            self._current_goals = ""
            self._goal_tasks = []
            self._next_goal_id = 1
            self._pending_goal_updates = []
        with self._llm_trigger_lock:
            self._llm_trigger_id = 0
            self._llm_consumed_trigger_id = 0
            self._last_llm_trigger_source = ""
            self._llm_brain_state = "waiting"
            self._last_auto_llm_step = None
            self._llm_trigger_ready.clear()
            self._infos["llm_brain"] = self._llm_brain_info_unlocked()
        self._infos["current_goals"] = ""
        self._infos["goal_tasks"] = []


class ToolsyAutopilotAgentPolicy(AgentPolicy):
    """Deterministic Toolsy fallback for fast headless evaluation.

    The LLM-backed policy remains the interactive GUI path. This policy uses the
    same observation decoder and action macros so it can be evaluated without a
    model key or coworld websocket process.
    """

    def __init__(self, policy_env_info: PolicyEnvInterface, agent_id: int):
        super().__init__(policy_env_info)
        self._agent_id = agent_id
        self._step_num = 0
        self._spawn = (0, 0)
        self._world_map = WorldMap()
        self._macro = None
        self._macro_name = ""
        self._macro_started = False
        self._macro_age = 0
        self._mine_cooldown_until = 0
        self._gear_cooldown_until = 0
        self._node_cooldown_until = 0
        self._blocked_mine_targets: dict[tuple[int, int], int] = {}
        self._blocked_node_targets: dict[tuple[int, int], int] = {}
        self._infos: dict = {"role": "toolsy-autopilot", "goal": "init"}

    @property
    def infos(self) -> dict:
        return self._infos

    def step(self, obs: AgentObservation) -> Action:
        self._step_num += 1
        view = decode_view(
            obs,
            self.policy_env_info,
            self._step_num,
            spawn=self._spawn,
            world_map=self._world_map,
        )
        self._infos["world_model"] = view.world_map.snapshot(
            view.decoded.center_row,
            view.decoded.center_col,
        )
        if view.coherence == 0:
            self._infos.update({"goal": "rebooting", "heart": view.heart, "creds": view.creds})
            self._clear_macro()
            return Action(name="noop")

        if self._macro_name == "explore" and self._known("extractor", view):
            self._clear_macro()
        if self._macro_name == "mine_extractors" and view.total_cargo >= 4:
            self._clear_macro()
        if self._macro_name == "mine_extractors" and self._macro_age >= 90:
            self._block_visible_extractors(view, until=view.step + 600)
            self._mine_cooldown_until = view.step + 120
            self._clear_macro()

        action = self._step_existing_macro(view)
        if action is not None:
            self._update_status(view)
            return action

        action = None
        for _attempt in range(3):
            self._schedule_next_macro(view)
            action = self._step_existing_macro(view)
            if action is not None:
                break
        self._update_status(view)
        return action or Action(name=self._fallback_action(view))

    def _update_status(self, view: GameView) -> None:
        self._infos.update({
            "goal": self._macro_name or "explore",
            "heart": view.heart,
            "creds": view.creds,
            "team": view.team or "none",
            "cargo": view.total_cargo,
            "atk": view.total_atk,
        })

    def _clear_macro(self) -> None:
        self._macro = None
        self._macro_name = ""
        self._macro_started = False
        self._macro_age = 0

    def _schedule(self, name: str, macro) -> None:
        self._macro = macro
        self._macro_name = name
        self._macro_started = False
        self._macro_age = 0

    def _step_existing_macro(self, view: GameView) -> Action | None:
        if self._macro is None:
            return None
        try:
            self._macro_age += 1
            if self._macro_started:
                return self._macro.send(view)
            self._macro_started = True
            return next(self._macro)
        except StopIteration as stopped:
            macro_name = self._macro_name
            result = stopped.value
            if (
                macro_name.startswith("buy_")
                and isinstance(result, ToolResult)
                and not result.success
            ):
                self._gear_cooldown_until = view.step + 300
            if (
                macro_name.startswith("hack_")
                and isinstance(result, ToolResult)
                and not result.success
            ):
                self._node_cooldown_until = view.step + 200
            if (
                macro_name == "mine_extractors"
                and isinstance(result, ToolResult)
                and not result.success
            ):
                self._block_visible_extractors(view, until=view.step + 600)
                self._mine_cooldown_until = view.step + 180
            self._clear_macro()
            return None

    def _schedule_next_macro(self, view: GameView) -> None:
        if view.heart >= 100:
            self._schedule("done_100_hearts", BLOCKING_TOOLS["wait"](view, num_ticks=50))
            return

        if self._should_buy_hearts(view):
            if self._known("heart", view):
                self._schedule("buy_hearts", self._repeat_use(view, "heart", max_uses=view.creds // 100))
            else:
                self._schedule("search_for_heart", BLOCKING_TOOLS["explore"](view, num_ticks=80))
            return

        if not view.team and self._known("hub", view):
            self._schedule("join_team", BLOCKING_TOOLS["join_team"](view, max_ticks=35))
            return

        if self._stake_count(view) == 0 and view.total_atk >= 4 and view.creds >= 10:
            if self._known("stake_buy", view):
                self._schedule("buy_stake", BLOCKING_TOOLS["use"](view, "stake_buy", max_ticks=45))
            elif self._near_spawn(view):
                self._schedule("map_compound_for_stake", BLOCKING_TOOLS["explore_compound"](view, max_ticks=35))
            else:
                self._schedule("return_for_stake", self._goto_coord(view, self._spawn, 120))
            return

        if (
            self._can_afford_gear(view)
            and (self._needs_more_attack_spread(view) or view.step < 2500)
            and view.total_atk < 7
            and view.step >= self._gear_cooldown_until
        ):
            gear_target = self._gear_target(view)
            if gear_target is not None:
                self._schedule(
                    f"buy_{gear_target.type_name}",
                    self._use_entity(view, gear_target, max_ticks=70),
                )
                return
            if self._near_spawn(view):
                self._schedule("map_compound", BLOCKING_TOOLS["explore_compound"](view, max_ticks=35))
                return
            self._schedule("return_for_gear", self._goto_coord(view, self._spawn, 120))
            return

        if view.total_cargo >= 4:
            if self._known("market", view):
                self._schedule("sell_cargo", BLOCKING_TOOLS["use"](view, "market", max_ticks=90))
            else:
                self._schedule("return_for_market", self._goto_coord(view, self._spawn, 160))
            return

        node_target = self._node_target_entity(view)
        if (
            node_target
            and self._stake_count(view) > 0
            and view.total_atk >= 6
            and view.step >= self._node_cooldown_until
            and view.step < HEART_RUN_STEP
        ):
            self._schedule(f"hack_{node_target.type_name}", self._hack_and_align_entity(view, node_target))
            return

        if view.total_atk > 0:
            visible_extractors = [
                entity for entity in view.entities
                if "extractor" in entity.type_name
                and not self._mine_target_blocked(view, entity)
            ]
            winnable_visible = any(
                entity.coherence == 0 or (
                    (ev := _combat_eval_entity(view, entity)).my_dps > 0 and ev.i_win
                )
                for entity in visible_extractors
            )
            if winnable_visible and view.step >= self._mine_cooldown_until:
                self._schedule("mine_extractors", BLOCKING_TOOLS["mine"](view, "extractor", max_ticks=80))
            elif view.nearest("extractor", max_distance=40):
                self._schedule("seek_extractors", self._goto_coord(view, self._scout_target(view), 120))
            else:
                self._schedule("seek_extractors", self._goto_coord(view, self._scout_target(view), 120))
            return

        heart_pos = self._target_position("heart", view)
        if heart_pos is not None and not self._near_center(view) and view.step < HEART_RUN_STEP:
            self._schedule("move_toward_center", self._goto_coord(view, heart_pos, 220))
            return

        self._schedule("explore", BLOCKING_TOOLS["explore"](view, num_ticks=40))

    def _should_buy_hearts(self, view: GameView) -> bool:
        if view.creds < 100:
            return False
        return view.step >= HEART_RUN_STEP

    def _stake_count(self, view: GameView) -> int:
        return sum(value for name, value in view.inventory.items() if name.endswith("_stake"))

    def _gear_cost(self, view: GameView) -> int:
        return 1 << (2 + view.total_gear)

    def _can_afford_gear(self, view: GameView) -> bool:
        return view.creds >= self._gear_cost(view)

    def _needs_more_attack_spread(self, view: GameView) -> bool:
        attack_channels = sum(1 for gear_name in ATTACK_GEAR_PRIORITY if view.gear.get(gear_name, 0) > 0)
        return view.total_atk < 8 or attack_channels < 4

    def _gear_target(self, view: GameView) -> EntityInfo | None:
        for gear_name in sorted(
            ATTACK_GEAR_PRIORITY,
            key=lambda name: (view.gear.get(name, 0), ATTACK_GEAR_PRIORITY.index(name)),
        ):
            target = view.nearest(f"{gear_name}_station", max_distance=24)
            if target is not None:
                return target
        return None

    def _node_target(self, view: GameView) -> str:
        for target in NODE_PRIORITY:
            if view.find(target, max_results=1, max_distance=18):
                return target
        if not self._near_center(view):
            return ""
        for target in NODE_PRIORITY:
            if self._known(target, view):
                return target
        return ""

    def _node_kind(self, type_name: str) -> str:
        for kind in NODE_PRIORITY:
            if kind in type_name:
                return kind
        return ""

    def _entity_position(self, view: GameView, entity: EntityInfo) -> tuple[int, int]:
        if entity.row is not None and entity.col is not None:
            return entity.row, entity.col
        return view.decoded.center_row + entity.dr, view.decoded.center_col + entity.dc

    def _mine_target_blocked(self, view: GameView, entity: EntityInfo) -> bool:
        pos = self._entity_position(view, entity)
        until = self._blocked_mine_targets.get(pos, 0)
        if until <= view.step:
            self._blocked_mine_targets.pop(pos, None)
            return False
        return True

    def _block_visible_extractors(self, view: GameView, until: int) -> None:
        for entity in view.entities:
            if "extractor" in entity.type_name:
                self._blocked_mine_targets[self._entity_position(view, entity)] = until

    def _network_anchors(self, view: GameView) -> list[tuple[int, int]]:
        anchors: list[tuple[int, int]] = []
        for entity in view.entities:
            if entity.type_name == "hub" and (not view.team or entity.team == view.team):
                anchors.append(self._entity_position(view, entity))

        for pos, type_name in view.world_map.entities.items():
            metadata = view.world_map.entity_metadata.get(pos)
            if metadata is None:
                continue
            if type_name == "hub" and (not view.team or metadata.team == view.team):
                anchors.append(pos)
            elif metadata.alignment == view.team:
                anchors.append(pos)

        return list(dict.fromkeys(anchors))

    def _node_target_entity(self, view: GameView) -> EntityInfo | None:
        anchors = self._network_anchors(view)
        if not anchors:
            return None

        candidates = []
        visible_positions = set()
        for entity in view.entities:
            kind = self._node_kind(entity.type_name)
            if not kind or entity.team == view.team:
                continue
            pos = self._entity_position(view, entity)
            visible_positions.add(pos)
            if self._node_target_blocked(pos, view):
                continue
            if not any((pos[0] - row) ** 2 + (pos[1] - col) ** 2 <= 25 * 25 for row, col in anchors):
                continue
            if entity.coherence > 0:
                ev = _combat_eval_entity(view, entity)
                if ev.my_dps <= 0 or not ev.i_win:
                    continue
            candidates.append((0 if entity.coherence == 0 else 1, -NODE_REVENUE[kind], entity.dist, entity))

        for pos, type_name in view.world_map.entities.items():
            if pos in visible_positions:
                continue
            kind = self._node_kind(type_name)
            if not kind:
                continue
            if self._node_target_blocked(pos, view):
                continue
            metadata = view.world_map.entity_metadata.get(pos)
            if metadata is not None and metadata.alignment == view.team:
                continue
            if not any((pos[0] - row) ** 2 + (pos[1] - col) ** 2 <= 25 * 25 for row, col in anchors):
                continue
            dr = pos[0] - view.decoded.center_row
            dc = pos[1] - view.decoded.center_col
            candidates.append((
                2,
                -NODE_REVENUE[kind],
                abs(dr) + abs(dc),
                EntityInfo(
                    type_name=type_name,
                    dr=dr,
                    dc=dc,
                    dist=abs(dr) + abs(dc),
                    row=pos[0],
                    col=pos[1],
                    visible=False,
                ),
            ))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[:3])
        return candidates[0][3]

    def _known(self, type_contains: str, view: GameView) -> bool:
        return bool(view.find(type_contains, max_results=1, max_distance=999))

    def _near_spawn(self, view: GameView) -> bool:
        return abs(view.decoded.center_row - self._spawn[0]) + abs(view.decoded.center_col - self._spawn[1]) <= 12

    def _near_center(self, view: GameView) -> bool:
        target = self._target_position("heart", view)
        if target is None:
            return False
        row, col = target
        return abs(view.decoded.center_row - row) + abs(view.decoded.center_col - col) <= 16

    def _target_position(self, type_contains: str, view: GameView) -> tuple[int, int] | None:
        target = view.nearest(type_contains, max_distance=999)
        if target is None:
            return None
        return view.decoded.center_row + target.dr, view.decoded.center_col + target.dc

    def _scout_target(self, view: GameView) -> tuple[int, int]:
        waypoints = [
            (-24, 24),
            (24, 24),
            (-24, -24),
            (24, -24),
            (0, 42),
            (42, 0),
            (-42, 0),
            (0, -42),
        ]
        return waypoints[(view.step // 120) % len(waypoints)]

    def _fallback_action(self, view: GameView) -> str:
        open_dirs = _open_dirs(view)
        return open_dirs[view.step % len(open_dirs)] if open_dirs else "noop"

    def _repeat_use(self, view: GameView, type_contains: str, max_uses: int):
        uses = 0
        ticks = 0
        per_use_budget = 900 if type_contains == "heart" else 40
        while uses < max_uses and ticks < max_uses * per_use_budget:
            before_heart = view.heart
            result = yield from BLOCKING_TOOLS["use"](view, type_contains, max_ticks=per_use_budget)
            ticks += result.ticks_used
            uses += 1
            view = yield Action(name="noop")
            ticks += 1
            if type_contains == "heart" and view.heart <= before_heart:
                break
        return ToolResult(True, f"Used {type_contains} {uses} times.", ticks)

    def _hack_and_align(self, view: GameView, type_contains: str):
        ticks = 0
        result = yield from BLOCKING_TOOLS["mine"](view, type_contains, max_ticks=80, no_loot=True)
        ticks += result.ticks_used
        view = yield Action(name="change_vibe_default")
        ticks += 1
        if not result.success:
            return result
        align = yield from BLOCKING_TOOLS["align"](view, type_contains, max_ticks=40)
        ticks += align.ticks_used
        return ToolResult(align.success, align.message, ticks)

    def _hack_and_align_entity(self, view: GameView, target: EntityInfo):
        ticks = 0
        attack_vibe = False
        while ticks < 120:
            refreshed = _refresh_entity(view, target)
            if refreshed is None:
                return self._fail_node_target(view, target, f"Lost target {target.type_name}.", ticks)
            target = refreshed

            if target.visible and target.team == view.team:
                return ToolResult(True, f"{target.type_name} already aligned.", ticks)
            if target.visible and target.coherence == 0:
                break
            if not target.visible or target.dist > 1:
                action_name = _step_toward_entity(view, target)
                ticks += 1
                view = yield Action(name=action_name)
                continue

            ev = _combat_eval_entity(view, target)
            if ev.my_dps <= 0 or not ev.i_win:
                return self._fail_node_target(view, target, f"{target.type_name} is not winnable.", ticks)
            if not attack_vibe:
                attack_vibe = True
                ticks += 1
                view = yield Action(name="change_vibe_attack")
                continue
            ticks += 1
            view = yield Action(name=_move_toward(target.dr, target.dc))

        if ticks >= 120:
            return self._fail_node_target(view, target, f"Timed out hacking {target.type_name}.", ticks)

        view = yield Action(name="change_vibe_default")
        ticks += 1
        align = yield from _use_target(view, target, max_ticks=50, label=target.type_name)
        ticks += align.ticks_used
        if not align.success:
            return self._fail_node_target(view, target, align.message, ticks)
        return ToolResult(align.success, align.message, ticks)

    def _node_target_blocked(self, pos: tuple[int, int], view: GameView) -> bool:
        until = self._blocked_node_targets.get(pos, 0)
        if until <= view.step:
            self._blocked_node_targets.pop(pos, None)
            return False
        return True

    def _fail_node_target(self, view: GameView, target: EntityInfo, message: str, ticks: int) -> ToolResult:
        self._blocked_node_targets[self._entity_position(view, target)] = view.step + 1200
        return ToolResult(False, message, ticks)

    def _use_entity(self, view: GameView, entity: EntityInfo, max_ticks: int):
        return (yield from _use_target(view, entity, max_ticks, entity.type_name))

    def _goto_coord(
        self,
        view: GameView,
        target: tuple[int, int],
        max_ticks: int,
        arrive_distance: int = 2,
    ):
        ticks = 0
        while ticks < max_ticks:
            row, col = view.decoded.center_row, view.decoded.center_col
            if abs(row - target[0]) + abs(col - target[1]) <= arrive_distance:
                return ToolResult(True, f"Reached {target}.", ticks)
            action_name = _step_toward_coord(view, target, arrive_distance=arrive_distance)
            open_dirs = _open_dirs(view)
            if action_name not in open_dirs:
                action_name = open_dirs[ticks % len(open_dirs)] if open_dirs else "noop"
            ticks += 1
            view = yield Action(name=action_name)
        return ToolResult(False, f"Timed out moving to {target}.", ticks)

    def reset(self) -> None:
        self._step_num = 0
        self._world_map = WorldMap()
        self._clear_macro()


class ToolsyPolicy(MultiAgentPolicy):
    """LLM policy for every agent when an LLM client is available."""

    short_names = ["toolsy"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        llm_client: Any | None = None,
        enable_llm: bool = True,
        **kwargs,
    ):
        super().__init__(policy_env_info, device=device)
        self._agents: dict[int, AgentPolicy] = {}
        self._llm = llm_client
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if enable_llm and self._llm is None and api_key:
            import anthropic
            self._llm = anthropic.Anthropic(
                api_key=api_key,
                timeout=LLM_REQUEST_TIMEOUT_SECONDS,
                max_retries=0,
            )

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        if agent_id not in self._agents:
            if self._llm is not None:
                self._agents[agent_id] = ToolsyAgentPolicy(
                    self._policy_env_info, agent_id, self._llm)
            else:
                self._agents[agent_id] = ToolsyAutopilotAgentPolicy(
                    self._policy_env_info, agent_id)
        return self._agents[agent_id]
