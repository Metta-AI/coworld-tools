"""RobotAgent + RobotPolicy -- the control loop.

Each call to step() is one cycle:
  1. PERCEIVE   raw tokens + talk -> FrameScan
  2. LISTEN     FrameScan.heard_messages -> TeammateMemory
  3. UPDATE     FrameScan -> Memory
  4. DRAFT      (ticks 0-14) negotiate role on shared DraftBoard
  5. SNAPSHOT   Memory + role + teammates -> WorldSnapshot
  6. DECIDE     WorldSnapshot -> MacroCommand + pending_talk
  7. EXECUTE    MacroCommand -> action_name (via A* navigator)
  8. RECORD     (snapshot, action) -> BlackBox

Each agent has its own independent SpatialMemory. Agents share
information only through in-game talk messages (via TeammateMemory).
"""

from __future__ import annotations

import sys
from typing import Optional

from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

from policies.cyborg.cogsguard.cvc_debugger_robot.robot.types import Coord, MacroCommand, NavState
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.perception import parse_observation
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.memory import SpatialMemory, SelfState, GameClock
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.pathfinding import Navigator
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.state import build_snapshot
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.brain import RobotBrain, EXPLORE_PHASE_END
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.blackbox import BlackBox
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.roster import DraftBoard, TeammateMemory, DRAFT_DEADLINE
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.observability import (
  ObservabilityHub, start_server, get_hub, is_debug_enabled, build_tick_payload,
)
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.policy_specs import ROBOT_POLICY_SPEC
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.llm_coordinator import LLMCoordinator


class RobotAgent(AgentPolicy):
  """One tick = one cycle of the robotic control loop."""

  def __init__(
    self,
    policy_env_info: PolicyEnvInterface,
    draft_board: DraftBoard,
    agent_id: int,
    max_steps: int = 10000,
    obs_hub: ObservabilityHub | None = None,
    heart_curve: list[tuple[int, int]] | None = None,
    llm_model: str = "",
    llm_budget: int = 7,
    llm_interval: int = 300,
  ):
    super().__init__(policy_env_info)

    self._agent_id = agent_id
    self._draft_board = draft_board
    self._obs_hub = obs_hub
    self._heart_curve = heart_curve
    self._llm_model = llm_model
    self._llm_budget = llm_budget
    self._llm_interval = llm_interval
    self._coordinator: LLMCoordinator | None = None
    self._talk_enabled = policy_env_info.talk.enabled
    self._max_steps = max_steps
    self._num_agents = policy_env_info.num_agents

    # Build tag name lookup: {tag_id: tag_name}
    self._tag_names: dict[int, str] = dict(enumerate(policy_env_info.tags))
    self._action_names = set(policy_env_info.action_names)

    # Observation geometry
    center_r = policy_env_info.obs_height // 2
    center_c = policy_env_info.obs_width // 2
    self._center: Coord = (center_r, center_c)

    # Subsystems
    self._memory = SpatialMemory(self._center, self._tag_names)
    self._self_state = SelfState()
    self._clock = GameClock(max_steps=max_steps)
    self._navigator = Navigator()
    self._teammate_memory = TeammateMemory()
    self._blackbox = BlackBox()

    # Brain is created after initial claim
    self._brain: Optional[RobotBrain] = None
    self._role: Optional[str] = None
    self._draft_announced = False
    self._last_talk_tick: int = -100  # tracks cooldown locally
    self._talk_cooldown: int = 50     # default, matches TalkConfig

    # Per-tick state
    self._pending_move: Optional[str] = None
    self._nav_state = NavState()
    self._active_cmd: Optional[MacroCommand] = None
    self._cmd_history: list[str] = []

  def step(self, obs: AgentObservation) -> Action:
    # 0. GROUND TRUTH POSITION -- extract before parsing so entity
    #    coordinates are computed from the real position, not a drifted one.
    from policies.cyborg.cogsguard.cvc_debugger_robot.robot.perception import extract_local_position
    true_pos = extract_local_position(obs)
    agent_pos = true_pos if true_pos is not None else self._memory.position

    # 1. PERCEIVE
    frame = parse_observation(
      obs, agent_pos, self._center, self._tag_names,
    )

    # 2. LISTEN
    for msg in frame.heard_messages:
      self._teammate_memory.hear(
        msg.agent_id, msg.text, msg.position, self._clock.tick + 1,
      )

    # 3. UPDATE
    self._clock.advance()
    self._memory.update(frame, self._pending_move, self._clock.tick)
    self._self_state = SelfState.from_inventory(frame.inventory, self._self_state)

    # 4. DRAFT -- negotiate role on shared board, returns talk message
    talk_text = self._run_draft()

    if self._clock.tick == DRAFT_DEADLINE and not self._draft_board.is_finalized:
      self._draft_board.finalize()

    # 5. SNAPSHOT
    teammate_records = self._teammate_memory.get_teammates()
    teammate_positions = [rec.last_position for rec in teammate_records.values()]
    snapshot = build_snapshot(
      self._memory, self._self_state, self._clock,
      self._nav_state, self._active_cmd, self._cmd_history,
      self._tag_names,
      role=self._role,
      agent_id=self._agent_id,
      teammates=self._teammate_memory.known_roles(),
      teammate_positions=teammate_positions,
      shared_extractors=self._teammate_memory.get_shared_extractors(),
      shared_hub=self._teammate_memory.get_shared_hub(),
      resource_needs=self._teammate_memory.get_resource_needs(),
      hub_resources=frame.hub_resources,
    )

    # 5.5. LLM COORDINATOR -- per-agent: create coordinator on first miner tick, consult
    if self._llm_model and self._brain is not None and self._role == "miner":
      if self._coordinator is None:
        self._coordinator = LLMCoordinator(
          agent_id=self._agent_id,
          model=self._llm_model,
          budget=self._llm_budget,
          consult_interval=self._llm_interval,
          obs_hub=self._obs_hub,
          num_agents=self._num_agents,
          max_steps=self._max_steps,
        )
      self._coordinator.maybe_consult(
        self._clock.tick, snapshot, self._brain.debug_state(),
      )
      self._brain.directive = self._coordinator.directive

    # 6. DECIDE
    command = self._brain.decide(snapshot)
    self._active_cmd = command
    self._cmd_history.append(command.reason)
    if len(self._cmd_history) > 20:
      self._cmd_history.pop(0)

    # DEBUG: trace agent decisions (all roles after draft)
    ss = snapshot.self_state
    if self._role and self._clock.tick >= DRAFT_DEADLINE:
      label = f"cargo={ss.cargo}" if ss.gear == "miner" else f"gear={ss.gear}"
      if ss.heart_count > 0:
        label += f" HEART={ss.heart_count}"
      extra = ""
      if command.target and command.target == snapshot.position:
        extra = " ON_TARGET!"
      elif command.target:
        mem_ent = self._memory.entities.get(command.target)
        if mem_ent:
          extra = f" tags={mem_ent.tag_names[:3]}"
      print(f"  [A{self._agent_id} t{self._clock.tick}] pos={snapshot.position} "
            f"{label} "
            f"cmd={command.kind.name}:{command.reason} "
            f"target={command.target}{extra}")

    # Brain may also want to talk (role re-announcements after draft)
    if talk_text is None and self._brain.pending_talk:
      talk_text = self._brain.pending_talk
    if self._brain.pending_talk:
      self._brain.pending_talk = None

    # Enforce cooldown: only send if enough ticks have passed
    if talk_text is not None:
      if self._clock.tick - self._last_talk_tick < self._talk_cooldown:
        talk_text = None
      else:
        self._last_talk_tick = self._clock.tick

    # 7. EXECUTE
    action_name, self._nav_state = self._navigator.execute(command, self._memory)

    # 8. RECORD
    self._blackbox.record(snapshot, action_name)
    self._pending_move = action_name

    # 9. OBSERVE -- push enriched data to the debug dashboard
    if self._obs_hub is not None:
      payload = build_tick_payload(
        snapshot.to_dict(),
        action_name,
        brain_debug=self._brain.debug_state() if self._brain else None,
        memory_stats=self._memory.stats(),
        nav_path_len=len(self._nav_state.path),
      )
      self._obs_hub.push(self._agent_id, payload)
      self._obs_hub.push_map(self._agent_id, self._memory.map_data())
      self._obs_hub.push_offsets({})

    if not self._talk_enabled:
      talk_text = None

    if action_name in self._action_names:
      return Action(name=action_name, talk=talk_text)
    return Action(name="noop", talk=talk_text)

  def _run_draft(self) -> str | None:
    """Handle draft negotiation. Returns talk message or None.

    Tick 0:  make initial claim on the shared board, announce via talk.
    Ticks 1-14: listen for teammates, check for conflicts, switch if needed.
    Tick 15: draft finalizes, announce confirmed role.

    Note: talk cooldown is 50 ticks, so we only get one broadcast per draft.
    The shared DraftBoard resolves conflicts atomically; talk is the
    in-game signal so teammates know what happened.
    """
    tick = self._clock.tick

    # First tick: make initial claim
    if self._brain is None:
      self._role = self._draft_board.claim(self._agent_id)
      self._brain = RobotBrain(self._role, self._agent_id,
                               heart_curve=self._heart_curve)
      return f"draft:{self._role}"

    # During draft period, check for conflicts via what we've heard
    if tick <= DRAFT_DEADLINE and not self._draft_board.is_finalized:
      heard = self._teammate_memory.known_roles()
      my_role = self._role

      # Count how many heard teammates share our role
      same_role_count = sum(1 for r in heard.values() if r == my_role)
      target_counts = self._draft_board.targets()
      target_for_my_role = target_counts.get(my_role, 0)

      # If we hear more agents on our role than allowed, switch
      if same_role_count >= target_for_my_role and target_for_my_role > 0:
        role_counts = self._draft_board.role_counts()
        for role in ("aligner", "scrambler", "miner"):
          target = target_counts.get(role, 0)
          current = role_counts.get(role, 0)
          if current < target and role != my_role:
            new_role = self._draft_board.reclaim(self._agent_id, role)
            if new_role:
              self._role = new_role
              self._brain = RobotBrain(new_role, self._agent_id,
                                       heart_curve=self._heart_curve)
              return f"switch:{new_role}"

    # At the deadline, announce final confirmed role
    if tick == DRAFT_DEADLINE:
      return f"role:{self._role}"

    return None


_DEFAULT_GRID_SIZE = 88

_MISSION_GRID_SIZES: dict[str, int] = {
  "machina_1": 88,
  "arena": 88,
  "machina_2": 100,
  "machina_3": 150,
}


def _infer_mission_from_argv() -> str | None:
  """Extract the mission name from sys.argv (last -m flag wins)."""
  argv = sys.argv
  mission = None
  for i, arg in enumerate(argv):
    if arg == "-m" and i + 1 < len(argv):
      mission = argv[i + 1]
  return mission


def _infer_map_size_from_argv() -> int:
  """Extract grid size from the mission name, with fallback to default 88."""
  mission = _infer_mission_from_argv()
  if mission and mission in _MISSION_GRID_SIZES:
    return _MISSION_GRID_SIZES[mission]
  return _DEFAULT_GRID_SIZE


class RobotPolicy(MultiAgentPolicy):
  """Multi-agent wrapper with shared DraftBoard for role negotiation."""

  short_names = ["robot"]

  def __init__(
    self,
    policy_env_info: PolicyEnvInterface,
    device: str = "cpu",
    max_steps: int = 10000,
    debug: str | bool = False,
    debug_port: int = 8777,
    heart_curve: str = "",
    llm_model: str = "",
    llm_budget: int = 25,
    llm_interval: int = 300,
    **kwargs,
  ):
    super().__init__(policy_env_info, device=device, **kwargs)
    self._policy_env_info = policy_env_info
    self._max_steps = max_steps
    self._draft_board = DraftBoard(policy_env_info.num_agents)

    self._heart_curve: list[tuple[int, int]] | None = None
    if heart_curve:
      self._heart_curve = [
        (int(p.split(":")[0]), int(p.split(":")[1]))
        for p in heart_curve.split(";")
      ]

    self._obs_hub: ObservabilityHub | None = None
    if is_debug_enabled(debug=debug):
      existing = get_hub()
      if existing is not None:
        self._obs_hub = existing
      else:
        self._obs_hub = ObservabilityHub()
        start_server(self._obs_hub, port=int(debug_port), open_browser=False)

      self._obs_hub.set_game_config({
        "num_agents": policy_env_info.num_agents,
        "max_steps": max_steps,
        "obs_size": [policy_env_info.obs_height, policy_env_info.obs_width],
        "actions": list(policy_env_info.action_names),
        "policy": ROBOT_POLICY_SPEC,
        "mission": _infer_mission_from_argv(),
        "map_size": _infer_map_size_from_argv(),
        "policy_kwargs": {
          k: v for k, v in kwargs.items()
          if k not in ("device",) and isinstance(v, (str, int, float, bool))
        },
      })
      self._obs_hub.set_game_status("running")

    self._llm_model = llm_model
    self._llm_budget = int(llm_budget)
    self._llm_interval = int(llm_interval)
    if llm_model:
      print(f"\n  >>> Per-Agent LLM active: model={llm_model} budget={llm_budget}/agent interval={llm_interval} <<<\n")

  def agent_policy(self, agent_id: int) -> AgentPolicy:
    return RobotAgent(
      self._policy_env_info,
      draft_board=self._draft_board,
      agent_id=agent_id,
      max_steps=self._max_steps,
      obs_hub=self._obs_hub,
      heart_curve=self._heart_curve,
      llm_model=self._llm_model,
      llm_budget=self._llm_budget,
      llm_interval=self._llm_interval,
    )
