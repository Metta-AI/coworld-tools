"""CvC agent — heuristic engine, mixins, and utility functions."""

from cogamer.cvc.agent.decisions import (
    DECISION_PIPELINE,
    run_pipeline,
)
from cogamer.cvc.agent.geometry import (
    direction_from_step,
    explore_offsets,
    format_position,
    greedy_step,
    manhattan,
    unstick_directions,
)
from cogamer.cvc.agent.resources import (
    absolute_position,
    attr_int,
    attr_str,
    deposit_threshold,
    has_role_gear,
    heart_batch_target,
    heart_supply_capacity,
    inventory_signature,
    needs_emergency_mining,
    phase_name,
    resource_priority,
    resource_total,
    retreat_threshold,
    role_vibe,
    should_batch_hearts,
    team_can_afford_gear,
    team_can_refill_hearts,
    team_id,
    team_min_resource,
)
from cogamer.cvc.agent.scoring import (
    aligner_target_score,
    is_claimed_by_other,
    is_usable_recent_extractor,
    scramble_target_score,
    spawn_relative_station_target,
    teammate_closer_to_target,
    within_alignment_network,
)
from cogamer.cvc.agent.tick_context import (
    TickContext,
    build_tick_context,
    teammate_aligner_positions,
)
from cogamer.cvc.agent.types import (
    _ALIGNER_EXPLORE_OFFSETS,
    _CLAIMED_TARGET_PENALTY,
    _ELEMENTS,
    _EMERGENCY_RESOURCE_LOW,
    _EXTRACTOR_MEMORY_STEPS,
    _GEAR_COSTS,
    _HEART_BATCH_TARGETS,
    _HP_THRESHOLDS,
    _HUB_ALIGN_DISTANCE,
    _JUNCTION_ALIGN_DISTANCE,
    _JUNCTION_AOE_RANGE,
    _MINER_EXPLORE_OFFSETS,
    _MOVE_DELTAS,
    _SCRAMBLER_EXPLORE_OFFSETS,
    _STATION_TARGETS_BY_AGENT,
    _TARGET_CLAIM_STEPS,
    KnownEntity,
)
