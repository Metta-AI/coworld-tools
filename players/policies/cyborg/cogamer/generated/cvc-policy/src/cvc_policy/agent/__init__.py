"""CvC agent — heuristic engine, mixins, and utility functions."""

from cvc_policy.agent.decisions import (
    DECISION_PIPELINE,
    run_pipeline,
)
from cvc_policy.agent.geometry import (
    direction_from_step,
    explore_offsets,
    format_position,
    greedy_step,
    manhattan,
    unstick_directions,
)
from cvc_policy.agent.resources import (
    absolute_position,
    attr_int,
    attr_str,
    gear_signature,
    has_role_gear,
    heart_batch_target,
    heart_cap_for_role,
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
from cvc_policy.agent.scoring import (
    aligner_target_score,
    is_usable_extractor,
    scramble_target_score,
    spawn_relative_station_target,
    teammate_closer_to_target,
    within_alignment_network,
)
from cvc_policy.agent.tick_context import (
    TickContext,
    build_tick_context,
    teammate_aligner_positions,
)
from cvc_policy.agent.types import (
    ELEMENTS,
    GEAR_COSTS,
    HP_THRESHOLDS,
    HUB_ALIGN_DISTANCE,
    JUNCTION_ALIGN_DISTANCE,
    JUNCTION_AOE_RANGE,
    KnownEntity,
    _ALIGNER_EXPLORE_OFFSETS,
    _EMERGENCY_RESOURCE_LOW,
    _HEART_BATCH_TARGETS,
    _MINER_EXPLORE_OFFSETS,
    _MOVE_DELTAS,
    _SCRAMBLER_EXPLORE_OFFSETS,
    _STATION_TARGETS_BY_AGENT,
)
