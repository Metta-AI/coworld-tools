"""Decision engine -- role-locked strategy with talk announcements.

Flow: WorldSnapshot -> RobotBrain.decide() -> MacroCommand
      (also sets self.pending_talk for the policy to attach to Action)

Phases:
  ticks 0-4:    draft -- wander ungeared while negotiating roles
  tick 5+:      gear up -- equip role gear, then role-locked specialization
  tick 50+:     report findings via talk

Anti-congestion: a timeout breaks out of stuck command loops after 15 ticks.
Heart pacing: after using a heart, agents explore briefly before collecting
another, giving teammates access to the shared supply.

Solo mode (1 agent): cycles mine -> deposit -> aligner -> capture as before.
"""

from __future__ import annotations

from robot.types import Coord, MacroCommand, MacroKind, ELEMENTS, manhattan
from robot.state import WorldSnapshot, JunctionInfo
from robot.roster import DRAFT_DEADLINE

EXPLORE_PHASE_END = 50
CARGO_DEPOSIT_THRESHOLD = 40
DEPOSITS_BEFORE_TERRITORY = 2
TALK_REANNOUNCE_INTERVAL = 60
CONGESTION_TIMEOUT = 15
HEART_COOLDOWN_TICKS = 0
JUNCTION_AOE_RANGE = 10

# Frontier probing: aligners push toward these offsets from the hub to
# discover junctions in the neutral zone. Closer than full corners so
# the aligner doesn't waste 30+ ticks walking to the map edge.
CORNER_PROBE_OFFSETS: list[Coord] = [
  (-12, -12),
  (-12, 12),
  (12, -12),
  (12, 12),
]

HEART_RECIPE_PER_ELEMENT = 7

# Heart capacity curve: list of (tick_threshold, max_hearts) pairs.
# Before the first threshold, capacity is 1. Each threshold unlocks
# a higher carry limit for aligners and scramblers.
# Tunable via _heart_capacity() — sweep tests will vary these.
DEFAULT_HEART_CURVE: list[tuple[int, int]] = [
  (100, 3),
  (300, 10),
]


def _any_resource_at_threshold(ss) -> bool:
  """True when cargo should be deposited.

  Miners commit to one resource per trip, so this checks if any single
  resource hit the threshold. Also triggers on total cargo as a safety
  net in case the miner picked up mixed resources from the environment.
  """
  if ss.cargo_total >= CARGO_DEPOSIT_THRESHOLD:
    return True
  return any(v >= CARGO_DEPOSIT_THRESHOLD for v in ss.cargo.values())


class RobotBrain:
  """Role-locked decision engine with talk communication."""

  JUNCTION_BOUNCE_THRESHOLD = 6

  def __init__(self, role: str, agent_id: int,
               heart_curve: list[tuple[int, int]] | None = None):
    self._role = role
    self._agent_id = agent_id

    self._deposit_count: int = 0
    self._prev_cargo: int = 0
    self._prev_gear: str | None = None
    self._prev_has_heart: bool = False
    self._prev_heart_count: int = 0
    self._junctions_captured: int = 0
    self._junctions_scrambled: int = 0
    self._last_enemy_area: Coord | None = None

    self._last_talk_tick: int = -TALK_REANNOUNCE_INTERVAL
    self._explore_reported: bool = False

    # Congestion timeout tracking
    self._last_cmd_reason: str | None = None
    self._same_cmd_ticks: int = 0

    # Heart capacity curve (sorted by tick ascending)
    self._heart_curve = sorted(
      heart_curve or DEFAULT_HEART_CURVE, key=lambda t: t[0],
    )

    # Heart pacing
    self._heart_cooldown: int = 0
    self._hub_wait_ticks: int = 0

    # Resource round-robin: each miner cycles through elements independently.
    # Offset by agent_id so miners don't all start on the same resource.
    self._resource_idx: int = agent_id % len(ELEMENTS)
    self._resource_target: str | None = None

    # Cumulative deposits per element — tracks what this miner has fed the hub
    # over the entire game so the miner can detect global resource imbalances.
    self._deposited: dict[str, int] = {e: 0 for e in ELEMENTS}
    self._prev_cargo_detail: dict[str, int] = {}

    # Starvation search budget: explore for a missing resource for up to
    # this many ticks before falling back to mining what's available.
    self._starve_search_ticks: int = 0
    self._starve_search_budget: int = 30

    # Depleted extractor tracking: blacklisted positions where the miner
    # arrived but cargo never increased.
    self._depleted_extractors: set[Coord] = set()
    # Per-target fruitless tick counter: total ticks spent targeting each
    # extractor (including travel) without gaining any cargo from it.
    self._extractor_fruitless: dict[Coord, int] = {}
    # Tracks the command target from the *previous* decision to detect when
    # the miner switches targets (resets the counter for the old target).
    self._last_mining_target: Coord | None = None

    # Event-driven broadcast flags
    self._just_deposited: bool = False
    self._just_used_heart: bool = False

    # Unalignable junction tracking: junctions where the aligner arrived
    # and bounced without the heart being consumed (alignment failed).
    self._unalignable_junctions: set[Coord] = set()
    self._junction_bounce_ticks: int = 0
    self._junction_bounce_target: Coord | None = None

    # Corner probe rotation for aligners: cycle through map quadrants
    # so we don't keep revisiting the same corners.
    self._corner_probe_idx: int = agent_id % len(CORNER_PROBE_OFFSETS)
    self._corners_visited: set[int] = set()
    self._last_probe_tick: int = 0

    self.pending_talk: str | None = None

    # LLM directive (set externally by the coordinator via policy.py)
    self._directive = None  # FlexDirective | None
    self._original_role: str = role
    self._off_role_ticks: int = 0

  @property
  def role(self) -> str:
    return self._role

  @role.setter
  def role(self, value: str) -> None:
    self._role = value

  @property
  def directive(self):
    return self._directive

  @directive.setter
  def directive(self, value) -> None:
    self._directive = value

  def decide(self, snapshot: WorldSnapshot) -> MacroCommand:
    self._detect_transitions(snapshot)
    self.pending_talk = None

    if self._role != "solo" and snapshot.tick > DRAFT_DEADLINE:
      # Event-driven broadcasts take priority over periodic updates
      event_talk = self._check_event_broadcasts(snapshot)
      if event_talk:
        self.pending_talk = event_talk
        self._last_talk_tick = snapshot.tick
      else:
        ticks_since_talk = snapshot.tick - self._last_talk_tick
        if ticks_since_talk >= TALK_REANNOUNCE_INTERVAL:
          self.pending_talk = self._build_intel_update(snapshot)
          self._last_talk_tick = snapshot.tick

    if self._role == "solo":
      return self._decide_solo(snapshot)

    return self._decide_role(snapshot)

  # --- Role-locked dispatch ---

  def _decide_role(self, snapshot: WorldSnapshot) -> MacroCommand:
    ss = snapshot.self_state
    tick = snapshot.tick

    # Emergency overrides
    if snapshot.threat.level == "CRITICAL":
      return MacroCommand(MacroKind.FLEE, reason="HP critical")

    # Phase 1: Draft -- wander ungeared while negotiating roles
    if tick < DRAFT_DEADLINE:
      return MacroCommand(MacroKind.EXPLORE, reason="drafting")

    # Stuck-as-wrong-role recovery: if we've been off our original role
    # for 200+ ticks without an active directive, revert to original role.
    if self._role != self._original_role:
      if self._directive is None or self._directive.is_complete:
        self._off_role_ticks += 1
        if self._off_role_ticks > 100:
          self._role = self._original_role
          self._off_role_ticks = 0
      else:
        self._off_role_ticks = 0
    else:
      self._off_role_ticks = 0

    # Phase 2: Gear up -- equip role gear immediately
    if ss.gear is None or ss.gear != self._role:
      cmd = self._cmd_gear_station(snapshot, self._role,
                                   f"equipping {self._role} gear")

    # Phase 3.5: LLM directive -- follows gear-up, overrides normal role work
    elif self._directive is not None and not self._directive.is_complete:
      # Opportunistic capture during explore directives
      step = self._directive.active_step
      if (step and step.action == "explore_area"
          and ss.has_heart and ss.gear == "aligner"):
        target = self._find_alignable_junction(snapshot)
        if target and manhattan(snapshot.position, target) <= 5:
          self._directive.advance()
          cmd = MacroCommand(MacroKind.NAVIGATE_TO, target=target,
                             reason="directive: opportunistic junction capture")
        else:
          cmd = self._execute_directive_step(snapshot)
      else:
        cmd = self._execute_directive_step(snapshot)

    else:
      # Report findings once after the early-game explore window
      if not self._explore_reported and tick > EXPLORE_PHASE_END:
        self._explore_reported = True
        self.pending_talk = self._build_explore_report(snapshot)

      # All roles go straight to work after gearing up
      if self._role == "miner":
        cmd = self._decide_miner(snapshot)
      elif self._role == "aligner":
        cmd = self._decide_aligner(snapshot)
      elif self._role == "scrambler":
        cmd = self._decide_scrambler(snapshot)
      else:
        cmd = MacroCommand(MacroKind.EXPLORE, reason="fallback explore")

    # Congestion timeout: if the brain keeps issuing the same stuck
    # command, break out with an idle/explore to let traffic clear.
    if cmd.reason == self._last_cmd_reason:
      self._same_cmd_ticks += 1
    else:
      self._same_cmd_ticks = 0
    self._last_cmd_reason = cmd.reason

    if self._same_cmd_ticks >= CONGESTION_TIMEOUT:
      self._same_cmd_ticks = 0
      return MacroCommand(MacroKind.EXPLORE, reason="congestion break")

    return cmd

  # --- LLM directive execution ---

  def _execute_directive_step(self, snapshot: WorldSnapshot) -> MacroCommand:
    """Execute the current active step of the LLM directive."""
    step = self._directive.active_step
    if step is None:
      return self._continue_directive_or_fallback(snapshot)

    ss = snapshot.self_state

    if step.action == "switch_gear":
      target_gear = step.params.get("gear", "aligner")
      if ss.gear == target_gear:
        self._directive.advance()
        return self._continue_directive_or_fallback(snapshot)
      self._role = target_gear
      return self._cmd_gear_station(snapshot, target_gear,
                                    f"directive: switching to {target_gear}")

    if step.action == "collect_heart":
      if ss.has_heart:
        self._directive.advance()
        return self._continue_directive_or_fallback(snapshot)
      hub = self._find_hub(snapshot)
      if hub:
        dist = manhattan(snapshot.position, hub)
        return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                            reason=f"directive: collecting heart d={dist}")
      return MacroCommand(MacroKind.EXPLORE,
                          reason="directive: searching for hub")

    if step.action == "capture_junction":
      if self._just_used_heart:
        self._directive.advance()
        return self._continue_directive_or_fallback(snapshot)
      if ss.gear != "aligner":
        self._role = "aligner"
        return self._cmd_gear_station(snapshot, "aligner",
                                      "directive: need aligner gear for capture")
      if not ss.has_heart:
        hub = self._find_hub(snapshot)
        if hub:
          return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                              reason="directive: need heart for capture")
        return MacroCommand(MacroKind.EXPLORE,
                            reason="directive: searching for hub (capture)")
      target = step.target
      if not target:
        target = self._find_alignable_junction(snapshot)
      if target:
        dist = manhattan(snapshot.position, target)
        return MacroCommand(MacroKind.NAVIGATE_TO, target=target,
                            reason=f"directive: capture junction d={dist}")
      return MacroCommand(MacroKind.EXPLORE,
                          reason="directive: searching for junction")

    if step.action == "scramble_junction":
      if self._just_used_heart:
        self._directive.advance()
        return self._continue_directive_or_fallback(snapshot)
      if ss.gear != "scrambler":
        self._role = "scrambler"
        return self._cmd_gear_station(snapshot, "scrambler",
                                      "directive: need scrambler gear for scramble")
      if not ss.has_heart:
        hub = self._find_hub(snapshot)
        if hub:
          return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                              reason="directive: need heart for scramble")
        return MacroCommand(MacroKind.EXPLORE,
                            reason="directive: searching for hub (scramble)")
      target = step.target or self._find_enemy_junction(snapshot)
      if target:
        dist = manhattan(snapshot.position, target)
        return MacroCommand(MacroKind.NAVIGATE_TO, target=target,
                            reason=f"directive: scramble junction d={dist}")
      return MacroCommand(MacroKind.EXPLORE,
                          reason="directive: searching for enemy junction")

    if step.action == "explore_area" and step.target:
      dist = manhattan(snapshot.position, step.target)
      if dist <= 3:
        self._directive.advance()
        return self._continue_directive_or_fallback(snapshot)
      return MacroCommand(MacroKind.NAVIGATE_TO, target=step.target,
                          reason=f"directive: explore area d={dist}")

    self._directive.advance()
    return self._continue_directive_or_fallback(snapshot)

  def _continue_directive_or_fallback(self, snapshot: WorldSnapshot) -> MacroCommand:
    """Advance to the next directive step or fall back to normal role work."""
    if self._directive and not self._directive.is_complete:
      return self._execute_directive_step(snapshot)
    # Directive complete -- fall back to current role's autonomous logic.
    if self._directive and self._directive.is_complete:
      self._directive = None
    if self._role == "miner":
      return self._decide_miner(snapshot)
    elif self._role == "aligner":
      return self._decide_aligner(snapshot)
    elif self._role == "scrambler":
      return self._decide_scrambler(snapshot)
    return MacroCommand(MacroKind.EXPLORE, reason="directive complete, exploring")

  def _find_enemy_junction(self, snapshot: WorldSnapshot) -> Coord | None:
    """Find the nearest enemy junction for scrambling."""
    best = None
    best_dist = float("inf")
    for j in snapshot.known_junctions:
      if j.owner in ("enemy", "clips"):
        d = manhattan(snapshot.position, j.position)
        if d < best_dist:
          best_dist = d
          best = j.position
    return best

  # --- Per-role strategies ---

  def _decide_miner(self, snapshot: WorldSnapshot) -> MacroCommand:
    ss = snapshot.self_state
    safe = {"safe_mode": True}

    if _any_resource_at_threshold(ss):
      hub = self._find_hub(snapshot)
      if hub:
        return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                            params=safe, reason=f"depositing c={ss.cargo_total}")
      return MacroCommand(MacroKind.EXPLORE, reason="searching for hub")

    target_resource = self._choose_mining_target(ss, snapshot)
    self._resource_target = target_resource

    cmd = self._find_mining_command(snapshot, target_resource)
    if cmd and cmd.target:
      self._track_mining_result(cmd.target, snapshot)
      if cmd.target not in self._depleted_extractors:
        return cmd

    starved = self._get_starved_resource()
    if starved and self._starve_search_ticks < self._starve_search_budget:
      self._starve_search_ticks += 1
      return MacroCommand(MacroKind.EXPLORE,
                          reason=f"need {target_resource} ({self._starve_search_ticks}/{self._starve_search_budget}) t{snapshot.tick}")

    cmd = self._find_mining_command_fallback(snapshot, target_resource)
    if cmd and cmd.target:
      self._track_mining_result(cmd.target, snapshot)
      if cmd.target not in self._depleted_extractors:
        return cmd

    return MacroCommand(MacroKind.EXPLORE, reason="exploring for extractors")

  def _find_mining_command(
    self, snapshot: WorldSnapshot, target_resource: str,
  ) -> MacroCommand | None:
    """Find best mining target for the desired resource."""
    ss = snapshot.self_state
    safe = {"safe_mode": True}

    extractor = self._find_extractor_for_resource(snapshot, target_resource)
    if extractor:
      self._starve_search_ticks = 0
      return MacroCommand(MacroKind.NAVIGATE_TO, target=extractor,
                          params=safe, reason=f"mining {target_resource} c={ss.cargo_total}")

    shared_ext = self._find_shared_extractor(snapshot, target_resource)
    if shared_ext:
      self._starve_search_ticks = 0
      dist = manhattan(snapshot.position, shared_ext)
      return MacroCommand(MacroKind.NAVIGATE_TO, target=shared_ext,
                          params=safe, reason=f"mining(shared) {target_resource} d={dist}")

    return None

  def _find_mining_command_fallback(
    self, snapshot: WorldSnapshot, target_resource: str,
  ) -> MacroCommand | None:
    """Fallback: find any extractor when the preferred resource isn't available."""
    ss = snapshot.self_state
    safe = {"safe_mode": True}

    extractor = self._find_nearest_extractor(snapshot)
    if extractor:
      return MacroCommand(MacroKind.NAVIGATE_TO, target=extractor,
                          params=safe, reason=f"mining(any) c={ss.cargo_total}")

    shared_any = self._find_shared_extractor(snapshot, None)
    if shared_any:
      dist = manhattan(snapshot.position, shared_any)
      return MacroCommand(MacroKind.NAVIGATE_TO, target=shared_any,
                          params=safe, reason=f"mining(shared-any) d={dist}")

    return None

  def _decide_aligner(self, snapshot: WorldSnapshot) -> MacroCommand:
    ss = snapshot.self_state
    desired = self._fair_heart_share(snapshot)

    if ss.heart_count == 0:
      hub = self._find_hub(snapshot)
      if hub:
        dist = manhattan(snapshot.position, hub)
        if dist <= 1:
          self._hub_wait_ticks += 1
        else:
          self._hub_wait_ticks = 0
        if self._hub_wait_ticks > 5:
          self._hub_wait_ticks = 0
          return MacroCommand(MacroKind.EXPLORE,
                              reason=f"hub empty, exploring t{snapshot.tick}")
        return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                            reason=f"getting heart {ss.heart_count}/{desired} d={dist}")
      return MacroCommand(MacroKind.EXPLORE, reason="searching for hub")
    self._hub_wait_ticks = 0

    target = self._find_alignable_junction(snapshot)
    if target:
      if self._detect_junction_bounce(snapshot, target):
        self._unalignable_junctions.add(target)
        target = self._find_alignable_junction(snapshot)

    if target:
      dist = manhattan(snapshot.position, target)
      return MacroCommand(MacroKind.NAVIGATE_TO, target=target,
                          reason=f"aligning junction d={dist} h={ss.heart_count}")

    fallback = self._find_junction_near_hub(snapshot)
    if fallback:
      dist = manhattan(snapshot.position, fallback)
      return MacroCommand(MacroKind.NAVIGATE_TO, target=fallback,
                          reason=f"heading to junction d={dist} h={ss.heart_count}")

    # Still has hearts but no known junctions — explore to find more
    # before returning to hub for a refill.
    probe = self._next_corner_probe(snapshot)
    if probe:
      dist = manhattan(snapshot.position, probe)
      return MacroCommand(MacroKind.NAVIGATE_TO, target=probe,
                          reason=f"probing corner q{self._corner_probe_idx} d={dist}")

    return MacroCommand(MacroKind.EXPLORE,
                        reason=f"exploring for junctions t{snapshot.tick}")

    # Only top up hearts when returning to hub anyway (heart_count == 0
    # handled above). This avoids wasteful round-trips when the aligner
    # still has hearts to spend on nearby junctions.

  def _detect_junction_bounce(self, snapshot: WorldSnapshot, target: Coord) -> bool:
    """Detect if the aligner is stuck bouncing at a junction without aligning.

    Returns True if the junction should be blacklisted.
    """
    dist = manhattan(snapshot.position, target)
    if dist > 1:
      if target != self._junction_bounce_target:
        self._junction_bounce_ticks = 0
        self._junction_bounce_target = target
      return False

    if target != self._junction_bounce_target:
      self._junction_bounce_ticks = 0
      self._junction_bounce_target = target

    self._junction_bounce_ticks += 1
    return self._junction_bounce_ticks >= self.JUNCTION_BOUNCE_THRESHOLD

  def _decide_scrambler(self, snapshot: WorldSnapshot) -> MacroCommand:
    ss = snapshot.self_state
    desired = self._fair_heart_share(snapshot)

    if ss.heart_count == 0:
      hub = self._find_hub(snapshot)
      if hub:
        dist = manhattan(snapshot.position, hub)
        if dist <= 1:
          self._hub_wait_ticks += 1
        else:
          self._hub_wait_ticks = 0
        if self._hub_wait_ticks > 5:
          self._hub_wait_ticks = 0
          return MacroCommand(MacroKind.EXPLORE,
                              reason=f"hub empty, exploring t{snapshot.tick}")
        return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                            reason=f"getting heart {ss.heart_count}/{desired} d={dist}")
      return MacroCommand(MacroKind.EXPLORE, reason="searching for hub")
    self._hub_wait_ticks = 0

    # Has heart -> navigate toward nearest enemy junction from ALL memory.
    # known_junctions is built from the full entity map, not just the 13x13
    # view, so this works even across neutral zone gaps.
    target = self._find_enemy_junction(snapshot)
    if target:
      self._last_enemy_area = target
      dist = manhattan(snapshot.position, target)
      return MacroCommand(MacroKind.NAVIGATE_TO, target=target,
                          reason=f"scrambling enemy junction d={dist}")

    # If we're in enemy AOE (HP drain or near enemy junction) but haven't
    # found the junction yet, record position for future return trips and
    # explore locally to discover it.
    if self._is_in_enemy_territory(snapshot):
      self._last_enemy_area = snapshot.position
      return MacroCommand(MacroKind.EXPLORE,
                          reason=f"in enemy aoe, searching for junction t{snapshot.tick}")

    # Keep heading toward last known enemy area (for returning after hub trips).
    # Clear it once we're close -- it's served its purpose of getting us here.
    if self._last_enemy_area:
      dist = manhattan(snapshot.position, self._last_enemy_area)
      if dist <= 3:
        self._last_enemy_area = None
      else:
        return MacroCommand(MacroKind.NAVIGATE_TO, target=self._last_enemy_area,
                            reason=f"pushing toward enemy area d={dist}")

    return MacroCommand(MacroKind.EXPLORE,
                        reason=f"exploring for enemy junctions t{snapshot.tick}")

  # --- Solo mode (single agent cycles through everything) ---

  def _decide_solo(self, snapshot: WorldSnapshot) -> MacroCommand:
    ss = snapshot.self_state

    if snapshot.threat.level == "CRITICAL":
      return MacroCommand(MacroKind.FLEE, reason="HP critical")

    # Holding heart with right gear -> execute mission
    if ss.has_heart and ss.gear == "aligner":
      target = self._find_alignable_junction(snapshot)
      if target:
        return MacroCommand(MacroKind.NAVIGATE_TO, target=target,
                            reason="capturing alignable junction")
      fallback = self._find_junction_near_hub(snapshot)
      if fallback:
        return MacroCommand(MacroKind.NAVIGATE_TO, target=fallback,
                            reason="heading toward junction near hub")
      return MacroCommand(MacroKind.EXPLORE, reason="exploring for junctions")

    if ss.has_heart and ss.gear == "scrambler":
      target = self._find_enemy_junction(snapshot)
      if target:
        return MacroCommand(MacroKind.NAVIGATE_TO, target=target,
                            reason=f"scrambling enemy junction d={manhattan(snapshot.position, target)}")
      return MacroCommand(MacroKind.EXPLORE,
                          reason=f"exploring for enemy junctions t{snapshot.tick}")

    # Right gear, need more hearts -> go to hub
    desired_hearts = self._fair_heart_share(snapshot)
    if ss.gear == "aligner" and ss.heart_count < desired_hearts:
      if self._has_alignable_targets(snapshot):
        hub = self._find_hub(snapshot)
        if hub:
          return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                              reason=f"getting heart {ss.heart_count}/{desired_hearts} (aligner)")
        return MacroCommand(MacroKind.EXPLORE, reason="searching for hub")

    if ss.gear == "scrambler" and ss.heart_count < desired_hearts:
      if self._has_enemy_targets(snapshot):
        hub = self._find_hub(snapshot)
        if hub:
          return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                              reason=f"getting heart {ss.heart_count}/{desired_hearts} (scrambler)")
        return MacroCommand(MacroKind.EXPLORE, reason="searching for hub")

    # Cargo full -> deposit
    if ss.gear == "miner" and _any_resource_at_threshold(ss):
      hub = self._find_hub(snapshot)
      if hub:
        return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                            reason=f"depositing {ss.cargo_total} cargo")
      return MacroCommand(MacroKind.EXPLORE, reason="searching for hub")

    # No gear -> pick one
    if ss.gear is None:
      desired = self._choose_gear_solo(snapshot)
      return self._cmd_gear_station(snapshot, desired, f"equipping {desired}")

    # Switch to territory after enough mining
    if ss.gear == "miner" and ss.cargo_total == 0 and self._should_switch_to_territory(snapshot):
      desired = self._choose_territory_gear(snapshot)
      return self._cmd_gear_station(snapshot, desired, f"switching to {desired}")

    # Mine
    if ss.gear == "miner":
      target_resource = self._choose_mining_target(ss)
      self._resource_target = target_resource
      extractor = self._find_extractor_for_resource(snapshot, target_resource)
      if extractor:
        self._starve_search_ticks = 0
        return MacroCommand(MacroKind.NAVIGATE_TO, target=extractor,
                            reason=f"mining {target_resource} c={ss.cargo_total}")
      starved = self._get_starved_resource()
      if starved and self._starve_search_ticks < self._starve_search_budget:
        self._starve_search_ticks += 1
        return MacroCommand(MacroKind.EXPLORE,
                            reason=f"need {target_resource} ({self._starve_search_ticks}/{self._starve_search_budget}) t{snapshot.tick}")
      extractor = self._find_nearest_extractor(snapshot)
      if extractor:
        return MacroCommand(MacroKind.NAVIGATE_TO, target=extractor,
                            reason=f"mining(any) c={ss.cargo_total}")
      return MacroCommand(MacroKind.EXPLORE, reason="exploring for extractors")

    return MacroCommand(MacroKind.EXPLORE, reason="exploring")

  # --- Solo gear selection ---

  def _choose_gear_solo(self, snapshot: WorldSnapshot) -> str:
    if self._deposit_count < DEPOSITS_BEFORE_TERRITORY:
      return "miner"
    return self._choose_territory_gear(snapshot)

  def _choose_territory_gear(self, snapshot: WorldSnapshot) -> str:
    if self._has_alignable_targets(snapshot):
      return "aligner"
    if self._has_enemy_targets(snapshot):
      return "scrambler"
    if snapshot.phase in ("MID", "LATE", "CLOSING"):
      return "aligner"
    return "miner"

  def _should_switch_to_territory(self, snapshot: WorldSnapshot) -> bool:
    if self._deposit_count < DEPOSITS_BEFORE_TERRITORY:
      return False
    if self._has_alignable_targets(snapshot) or self._has_enemy_targets(snapshot):
      return True
    if snapshot.phase in ("LATE", "CLOSING"):
      return True
    return False

  # --- Target finders ---

  def _has_alignable_targets(self, snapshot: WorldSnapshot) -> bool:
    return any(j.owner == "neutral" and j.alignable for j in snapshot.known_junctions)

  def _has_enemy_targets(self, snapshot: WorldSnapshot) -> bool:
    return any(j.owner in ("clips", "enemy") for j in snapshot.known_junctions)

  def _score_junction(self, snapshot: WorldSnapshot, j: JunctionInfo) -> float:
    """Score a junction by round-trip efficiency: agent → junction → hub.

    Lower score = better target. Balances reaching the junction quickly
    with keeping the return trip to hub short for the next heart pickup.
    """
    hub = self._find_hub(snapshot)
    hub_dist = manhattan(j.position, hub) if hub else 0
    return j.distance + hub_dist

  def _find_alignable_junction(self, snapshot: WorldSnapshot) -> Coord | None:
    candidates = [
      j for j in snapshot.known_junctions
      if j.owner == "neutral" and j.alignable
      and j.position not in self._unalignable_junctions
    ]
    if not candidates:
      return None

    # When multiple aligners exist, add repulsion from teammates so
    # they spread out to different junctions instead of competing.
    aligner_positions = [
      pos for pos in snapshot.teammate_positions
      if manhattan(snapshot.position, pos) > 2
    ]

    def scored(j: JunctionInfo) -> float:
      base = self._score_junction(snapshot, j)
      if not aligner_positions:
        return base
      nearest_mate = min(manhattan(j.position, tp) for tp in aligner_positions)
      return base - 0.3 * nearest_mate

    best = min(candidates, key=scored)
    return best.position

  def _find_junction_near_hub(self, snapshot: WorldSnapshot) -> Coord | None:
    neutrals = [
      j for j in snapshot.known_junctions
      if j.owner == "neutral"
      and j.position not in self._unalignable_junctions
    ]
    if not neutrals:
      return None

    aligner_positions = [
      pos for pos in snapshot.teammate_positions
      if manhattan(snapshot.position, pos) > 2
    ]

    def scored(j: JunctionInfo) -> float:
      base = self._score_junction(snapshot, j)
      if not aligner_positions:
        return base
      nearest_mate = min(manhattan(j.position, tp) for tp in aligner_positions)
      return base - 0.3 * nearest_mate

    best = min(neutrals, key=scored)
    return best.position

  def _find_enemy_junction(self, snapshot: WorldSnapshot) -> Coord | None:
    enemies = [
      j for j in snapshot.known_junctions
      if j.owner in ("clips", "enemy")
    ]
    if not enemies:
      return None
    best = min(enemies, key=lambda j: self._score_junction(snapshot, j))
    return best.position

  def _next_corner_probe(self, snapshot: WorldSnapshot) -> Coord | None:
    """Pick the next unexplored corner to probe for junctions.

    Rotates through map quadrants relative to the hub position. Each
    aligner starts at a different index (offset by agent_id) so multiple
    aligners naturally split across corners. Advances to the next corner
    once close enough or after spending enough ticks.
    """
    hub = self._find_hub(snapshot)
    if not hub:
      return None

    pos = snapshot.position
    n = len(CORNER_PROBE_OFFSETS)

    # Advance if we reached the current probe target or spent 60+ ticks
    current_offset = CORNER_PROBE_OFFSETS[self._corner_probe_idx % n]
    current_target = (hub[0] + current_offset[0], hub[1] + current_offset[1])
    dist_to_current = manhattan(pos, current_target)

    if dist_to_current <= 5 or (snapshot.tick - self._last_probe_tick) > 60:
      self._corners_visited.add(self._corner_probe_idx % n)
      self._corner_probe_idx = (self._corner_probe_idx + 1) % n
      self._last_probe_tick = snapshot.tick

      if len(self._corners_visited) >= n:
        self._corners_visited.clear()

    offset = CORNER_PROBE_OFFSETS[self._corner_probe_idx % n]
    return (hub[0] + offset[0], hub[1] + offset[1])

  def _cmd_gear_station(self, snapshot: WorldSnapshot, gear: str, reason: str) -> MacroCommand:
    station = self._find_nearest(snapshot, gear)
    if station:
      return MacroCommand(MacroKind.NAVIGATE_TO, target=station,
                          params={"gear": gear}, reason=reason)
    hub = self._find_hub(snapshot)
    if hub:
      return MacroCommand(MacroKind.NAVIGATE_TO, target=hub,
                          reason=f"heading to hub to find {gear} station")
    return MacroCommand(MacroKind.EXPLORE,
                        params={"gear": gear},
                        reason=f"searching for {gear} station t{snapshot.tick}")

  # --- Explore report ---

  def _build_explore_report(self, snapshot: WorldSnapshot) -> str:
    """Compact summary of what we found during exploration.

    Packs as much intel as possible into the 140-char talk limit:
    role, junction details (position + owner), extractor count, hub
    position, territory coverage, and threat level.
    """
    MAX_TALK_LEN = 140
    parts = [f"r:{self._role}"]

    for j in sorted(snapshot.known_junctions, key=lambda j: j.distance):
      tag = "o" if j.owner == "own" else "e" if j.owner in ("enemy", "clips") else "n"
      parts.append(f"j{tag}@{j.position[0]},{j.position[1]}")

    ext_count = sum(
      1 for e in snapshot.nearby_entities
      if any("extractor" in t for t in e.tags)
    )
    if ext_count:
      parts.append(f"{ext_count}ext")

    for e in snapshot.nearby_entities:
      if any("hub" in t for t in e.tags):
        parts.append(f"hub@{e.position[0]},{e.position[1]}")
        break

    friendly = sum(1 for v in snapshot.territory.values() if v == 1)
    enemy = sum(1 for v in snapshot.territory.values() if v == 2)
    if friendly or enemy:
      parts.append(f"ter:f{friendly}e{enemy}")

    parts.append(f"hp:{snapshot.self_state.hp}")
    parts.append(f"pos:{snapshot.position[0]},{snapshot.position[1]}")
    parts.append(f"t:{snapshot.tick}")

    report = "report:" + ",".join(parts)
    return report[:MAX_TALK_LEN]

  def _build_status_update(self, snapshot: WorldSnapshot) -> str:
    """Periodic status broadcast using the full 140-char talk capacity."""
    MAX_TALK_LEN = 140
    ss = snapshot.self_state
    parts = [f"role:{self._role}"]

    parts.append(f"pos:{snapshot.position[0]},{snapshot.position[1]}")
    parts.append(f"hp:{ss.hp}")
    parts.append(f"e:{ss.energy}")

    if self._role == "miner":
      parts.append(f"dep:{self._deposit_count}")
      if ss.cargo_total > 0:
        cargo_str = "/".join(f"{v}{k[0]}" for k, v in ss.cargo.items() if v > 0)
        parts.append(f"cargo:{cargo_str}")
    elif self._role in ("aligner", "scrambler"):
      parts.append(f"cap:{self._junctions_captured}")
      parts.append(f"scr:{self._junctions_scrambled}")
      parts.append(f"heart:{'y' if ss.has_heart else 'n'}")

    for j in sorted(snapshot.known_junctions, key=lambda j: j.distance)[:4]:
      tag = "o" if j.owner == "own" else "e" if j.owner in ("enemy", "clips") else "n"
      parts.append(f"j{tag}@{j.position[0]},{j.position[1]}")

    if snapshot.active_command:
      cmd_summary = snapshot.active_command.reason[:30]
      parts.append(f"do:{cmd_summary}")

    parts.append(f"t:{snapshot.tick}")

    msg = ",".join(parts)
    return msg[:MAX_TALK_LEN]

  def _check_event_broadcasts(self, snapshot: WorldSnapshot) -> str | None:
    """Trigger an immediate intel broadcast on important state changes.

    Fires when: a miner just deposited resources, a heart was just used,
    or the hub is detected as starved on any element (< 7 means no hearts
    can be crafted).
    """
    if self._just_deposited:
      return self._build_intel_update(snapshot)

    if self._just_used_heart:
      return self._build_intel_update(snapshot)

    # Detect hub starvation from our own deposit history
    starved = self._get_starved_resource()
    if starved:
      return self._build_need_message(snapshot, starved)

    return None

  def _build_need_message(self, snapshot: WorldSnapshot, starved: str) -> str:
    """Broadcast that the hub needs a specific resource."""
    MAX_TALK_LEN = 140
    parts = [f"need:{starved}"]

    # Include extractor locations for the needed resource so miners
    # hearing this know WHERE to go mine it.
    for ent in snapshot.nearby_entities:
      resource_tag = f"{starved}_extractor"
      if any(resource_tag in t for t in ent.tags):
        if snapshot.is_friendly_territory(ent.position):
          parts.append(f"{starved[0]}X@{ent.position[0]}/{ent.position[1]}")

    parts.append(f"dep:{','.join(f'{e[0]}:{self._deposited.get(e, 0)}' for e in ELEMENTS)}")
    parts.append(f"t:{snapshot.tick}")

    return ",".join(parts)[:MAX_TALK_LEN]

  def _build_intel_update(self, snapshot: WorldSnapshot) -> str:
    """Rich intel broadcast: hub position, extractors by type, resource needs.

    Packs the most actionable teammate intel into 140 chars:
    hub location, resource extractor positions (coded by element initial),
    starved resources, and own status.
    """
    MAX_TALK_LEN = 140
    parts = []

    # Hub position — critical for all roles
    for ent in snapshot.nearby_entities:
      if any("hub" in t for t in ent.tags):
        parts.append(f"hub@{ent.position[0]}/{ent.position[1]}")
        break

    # Extractor positions by resource type (only in friendly territory)
    ext_seen = 0
    for ent in snapshot.nearby_entities:
      if ext_seen >= 6:
        break
      for elem in ELEMENTS:
        if any(f"{elem}_extractor" in t for t in ent.tags):
          if snapshot.is_friendly_territory(ent.position):
            parts.append(f"{elem[0]}X@{ent.position[0]}/{ent.position[1]}")
            ext_seen += 1
          break

    # Starved resources — alert teammates so miners can prioritize
    starved = self._get_starved_resource()
    if starved:
      parts.append(f"low:{starved}")

    # Deposit totals so teammates understand hub balance
    dep_str = "/".join(f"{e[0]}{self._deposited.get(e, 0)}" for e in ELEMENTS)
    parts.append(f"d:{dep_str}")

    parts.append(f"r:{self._role}")
    parts.append(f"t:{snapshot.tick}")

    msg = "intel:" + ",".join(parts)
    return msg[:MAX_TALK_LEN]

  # --- Transition detection ---

  def _detect_transitions(self, snapshot: WorldSnapshot) -> None:
    ss = snapshot.self_state
    self._just_deposited = False
    self._just_used_heart = False

    if ss.gear == "miner" and self._prev_cargo > 0 and ss.cargo_total < self._prev_cargo:
      self._deposit_count += 1
      self._just_deposited = True
      self._advance_round_robin()
      self._starve_search_ticks = 0
      for elem in ELEMENTS:
        prev = self._prev_cargo_detail.get(elem, 0)
        cur = ss.cargo.get(elem, 0)
        dropped = prev - cur
        if dropped > 0:
          self._deposited[elem] = self._deposited.get(elem, 0) + dropped

    if self._prev_has_heart and ss.heart_count < self._prev_heart_count and ss.gear == "aligner":
      self._junctions_captured += 1
      self._deposit_count = 0
      self._junction_bounce_ticks = 0
      self._junction_bounce_target = None
      self._just_used_heart = True

    if self._prev_has_heart and ss.heart_count < self._prev_heart_count and ss.gear == "scrambler":
      self._junctions_scrambled += 1
      self._deposit_count = 0
      self._last_enemy_area = snapshot.position
      self._just_used_heart = True

    self._prev_cargo = ss.cargo_total
    self._prev_cargo_detail = dict(ss.cargo)
    self._prev_gear = ss.gear
    self._prev_has_heart = ss.has_heart
    self._prev_heart_count = ss.heart_count

  # --- Heart capacity ---

  def _heart_capacity(self, tick: int) -> int:
    """How many hearts this agent should carry, based on game tick.

    Scramblers wait until tick 100 before carrying hearts.
    """
    if self._role == "scrambler" and tick < 100:
      return 0
    cap = 1
    for threshold, hearts in self._heart_curve:
      if tick >= threshold:
        cap = hearts
      else:
        break
    return cap

  def _fair_heart_share(self, snapshot: WorldSnapshot) -> int:
    """Heart capacity capped to a fair share so one agent doesn't hog the supply.

    When capacity > 1, each heart-using agent (aligner/scrambler) takes at
    most half the curve capacity rounded up, ensuring at least 1 heart
    remains for a teammate returning to the hub.
    """
    cap = self._heart_capacity(snapshot.tick)
    if cap <= 1:
      return cap
    heart_users = sum(
      1 for aid, r in snapshot.teammates.items()
      if r in ("aligner", "scrambler") and aid != self._agent_id
    ) + 1  # +1 for self
    if heart_users <= 1:
      return cap
    share = max(1, -(-cap // heart_users))  # ceil division
    return share

  # --- Entity search ---

  def _is_in_enemy_territory(self, snapshot: WorldSnapshot) -> bool:
    """Check if agent is within enemy territory.

    Three signals, checked in order of reliability:
    (1) reconstructed territory value == 2 at current position,
    (2) proximity to a known enemy junction (range 10),
    (3) losing HP while outside friendly territory (HP drain from enemy
        territory even when the junction hasn't been discovered yet).
    """
    if snapshot.is_enemy_territory(snapshot.position):
      return True
    for j in snapshot.known_junctions:
      if j.owner in ("clips", "enemy") and j.distance <= JUNCTION_AOE_RANGE:
        return True
    ss = snapshot.self_state
    if ss.hp_delta < 0 and not snapshot.in_friendly_territory:
      return True
    return False


  def _find_nearest(self, snapshot: WorldSnapshot, tag_substr: str) -> Coord | None:
    for ent in snapshot.nearby_entities:
      if ent.position == snapshot.position:
        continue
      if any(tag_substr in t for t in ent.tags):
        return ent.position
    return None

  def _find_hub(self, snapshot: WorldSnapshot) -> Coord | None:
    """Find hub: own observation first, then teammate-shared position."""
    own = self._find_nearest(snapshot, "hub")
    if own:
      return own
    return snapshot.shared_hub

  def _find_shared_extractor(
    self, snapshot: WorldSnapshot, resource: str | None,
  ) -> Coord | None:
    """Find nearest extractor from teammate intel.

    Matches by element initial: c=carbon, o=oxygen, g=germanium, s=silicon.
    If resource is None, returns the closest extractor of any type.
    """
    if not snapshot.shared_extractors:
      return None

    pos = snapshot.position
    best: Coord | None = None
    best_dist = 9999
    initial = resource[0] if resource else None

    for ext_pos, code in snapshot.shared_extractors.items():
      if ext_pos in self._depleted_extractors:
        continue
      if initial and not code.startswith(initial):
        continue
      d = manhattan(pos, ext_pos)
      if d < best_dist:
        best_dist = d
        best = ext_pos

    return best

  def _choose_mining_target(self, ss, snapshot: WorldSnapshot | None = None) -> str:
    """Pick which resource element to mine next.

    Priority when cargo is empty:
    1. Hub resource counts (mine the element the hub has least of)
    2. Teammate-broadcast need
    3. Own deposit history starvation detection
    4. Round-robin fallback
    """
    if ss.cargo_total > 0:
      for elem in ELEMENTS:
        if ss.cargo.get(elem, 0) > 0:
          return elem
      return ELEMENTS[self._resource_idx]

    if snapshot and snapshot.hub_resources:
      resource_elements = [e for e in ELEMENTS if e in snapshot.hub_resources]
      if resource_elements:
        return min(resource_elements, key=lambda e: snapshot.hub_resources.get(e, 0))

    if snapshot and snapshot.resource_needs:
      return snapshot.resource_needs[0]

    starved = self._get_starved_resource()
    if starved:
      return starved

    return ELEMENTS[self._resource_idx]

  def _get_starved_resource(self) -> str | None:
    """Detect hub resource starvation from deposit history.

    Returns the most-needed element when the hub has a severe imbalance:
    some element deposited >= CARGO_DEPOSIT_THRESHOLD while another is
    below HEART_RECIPE_PER_ELEMENT. This means the hub is blocked from
    crafting hearts because it's missing a resource entirely.

    Only activates after enough total deposits that an imbalance is
    meaningful (at least 3 deposit cycles worth of resources).
    """
    dep = self._deposited
    amounts = [dep.get(e, 0) for e in ELEMENTS]
    total = sum(amounts)
    if total < CARGO_DEPOSIT_THRESHOLD * 3:
      return None
    if not any(a >= CARGO_DEPOSIT_THRESHOLD for a in amounts):
      return None
    if not any(a < HEART_RECIPE_PER_ELEMENT for a in amounts):
      return None

    return min(ELEMENTS, key=lambda e: dep.get(e, 0))

  def _advance_round_robin(self) -> None:
    """Move to the next element in the round-robin cycle."""
    self._resource_idx = (self._resource_idx + 1) % len(ELEMENTS)

  DEPLETED_FRUITLESS_THRESHOLD = 6

  def _track_mining_result(self, target: Coord, snapshot: WorldSnapshot) -> None:
    """Track whether a mining target has been fruitful.

    Called every tick from _decide_miner with the target the brain is
    about to issue. If the miner is at distance <= 1 (adjacent, where
    mining should occur) and cargo hasn't increased, bump the fruitless
    counter. Once the counter hits DEPLETED_FRUITLESS_THRESHOLD,
    blacklist the target. A cargo increase resets the counter.
    """
    ss = snapshot.self_state

    if ss.cargo_total > self._prev_cargo:
      self._extractor_fruitless.pop(target, None)
      self._last_mining_target = target
      return

    dist = manhattan(snapshot.position, target)
    if dist <= 1:
      count = self._extractor_fruitless.get(target, 0) + 1
      self._extractor_fruitless[target] = count
      if count >= self.DEPLETED_FRUITLESS_THRESHOLD:
        self._depleted_extractors.add(target)
        self._extractor_fruitless.pop(target, None)

    self._last_mining_target = target

  def _find_extractor_for_resource(
    self, snapshot: WorldSnapshot, resource: str,
  ) -> Coord | None:
    """Find nearest extractor for a specific resource in friendly territory."""
    target_tag = f"{resource}_extractor"
    for ent in snapshot.nearby_entities:
      if ent.position == snapshot.position:
        continue
      if ent.position in self._depleted_extractors:
        continue
      if not any(target_tag in t for t in ent.tags):
        continue
      if not snapshot.is_friendly_territory(ent.position):
        continue
      return ent.position
    return None

  def _find_nearest_extractor(self, snapshot: WorldSnapshot) -> Coord | None:
    """Find nearest extractor of any type in friendly territory (fallback)."""
    for ent in snapshot.nearby_entities:
      if ent.position == snapshot.position:
        continue
      if ent.position in self._depleted_extractors:
        continue
      if not any("extractor" in t for t in ent.tags):
        continue
      if not snapshot.is_friendly_territory(ent.position):
        continue
      return ent.position
    return None

  def debug_state(self) -> dict:
    """Snapshot of internal counters for observability dashboard."""
    return {
      "role": self._role,
      "deposit_count": self._deposit_count,
      "junctions_captured": self._junctions_captured,
      "junctions_scrambled": self._junctions_scrambled,
      "congestion_ticks": self._same_cmd_ticks,
      "last_cmd_reason": self._last_cmd_reason,
      "heart_cooldown": self._heart_cooldown,
      "heart_curve": self._heart_curve,
      "explore_reported": self._explore_reported,
      "resource_target": self._resource_target,
      "resource_idx": self._resource_idx,
      "deposited": dict(self._deposited),
      "depleted_extractors": [list(p) for p in self._depleted_extractors],
      "unalignable_junctions": [list(p) for p in self._unalignable_junctions],
      "extractor_fruitless": {str(k): v for k, v in self._extractor_fruitless.items()},
      "corner_probe_idx": self._corner_probe_idx,
      "corners_visited": list(self._corners_visited),
      "directive": self._directive.to_dict() if self._directive else None,
    }

  def reset(self) -> None:
    self._deposit_count = 0
    self._prev_cargo = 0
    self._prev_gear = None
    self._prev_has_heart = False
    self._prev_heart_count = 0
    self._junctions_captured = 0
    self._junctions_scrambled = 0
    self._last_enemy_area = None
    self._last_talk_tick = -TALK_REANNOUNCE_INTERVAL
    self._explore_reported = False
    self._last_cmd_reason = None
    self._same_cmd_ticks = 0
    self._heart_cooldown = 0
    self._hub_wait_ticks = 0
    self._resource_idx = self._agent_id % len(ELEMENTS)
    self._resource_target = None
    self._deposited = {e: 0 for e in ELEMENTS}
    self._prev_cargo_detail = {}
    self._starve_search_ticks = 0
    self._depleted_extractors = set()
    self._extractor_fruitless = {}
    self._last_mining_target = None
    self._just_deposited = False
    self._just_used_heart = False
    self._unalignable_junctions = set()
    self._junction_bounce_ticks = 0
    self._junction_bounce_target = None
    self._corner_probe_idx = self._agent_id % len(CORNER_PROBE_OFFSETS)
    self._corners_visited = set()
    self._last_probe_tick = 0
    self.pending_talk = None
