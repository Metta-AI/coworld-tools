"""Pure helper functions for cyborg policy logic.

Organized by concern:
- types: Constants and data types (KnownEntity, game thresholds)
- geometry: Distance, direction, pathfinding, exploration offsets
- resources: Inventory, team state, phase determination
- targeting: Scoring, claiming, alignment network queries
- cost_tracking: LLM API token usage aggregation
- benchmarking: Run comparison and statistical analysis
"""

from cvc.cogent.player_cog.policy.helpers.geometry import (
    direction_from_step,
    explore_offsets,
    format_position,
    greedy_step,
    manhattan,
    unstick_directions,
)
from cvc.cogent.player_cog.policy.helpers.resources import (
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
from cvc.cogent.player_cog.policy.helpers.targeting import (
    aligner_target_score,
    is_claimed_by_other,
    is_usable_recent_extractor,
    scramble_target_score,
    spawn_relative_station_target,
    v65_aligner_target_score,
    within_alignment_network,
)
from cvc.cogent.player_cog.policy.helpers.types import (
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

__all__ = [
    # geometry
    "direction_from_step",
    "explore_offsets",
    "format_position",
    "greedy_step",
    "manhattan",
    "unstick_directions",
    # resources
    "absolute_position",
    "attr_int",
    "attr_str",
    "deposit_threshold",
    "has_role_gear",
    "heart_batch_target",
    "heart_supply_capacity",
    "inventory_signature",
    "needs_emergency_mining",
    "phase_name",
    "resource_priority",
    "resource_total",
    "retreat_threshold",
    "role_vibe",
    "should_batch_hearts",
    "team_can_afford_gear",
    "team_can_refill_hearts",
    "team_id",
    "team_min_resource",
    # targeting
    "aligner_target_score",
    "is_claimed_by_other",
    "is_usable_recent_extractor",
    "scramble_target_score",
    "spawn_relative_station_target",
    "within_alignment_network",
    # types + constants
    "KnownEntity",
    "_ALIGNER_EXPLORE_OFFSETS",
    "_CLAIMED_TARGET_PENALTY",
    "_ELEMENTS",
    "_EMERGENCY_RESOURCE_LOW",
    "_EXTRACTOR_MEMORY_STEPS",
    "_GEAR_COSTS",
    "_HEART_BATCH_TARGETS",
    "_HP_THRESHOLDS",
    "_HUB_ALIGN_DISTANCE",
    "_JUNCTION_ALIGN_DISTANCE",
    "_JUNCTION_AOE_RANGE",
    "_MINER_EXPLORE_OFFSETS",
    "_MOVE_DELTAS",
    "_SCRAMBLER_EXPLORE_OFFSETS",
    "_STATION_TARGETS_BY_AGENT",
    "_TARGET_CLAIM_STEPS",
]
