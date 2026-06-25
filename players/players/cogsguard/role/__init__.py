"""CoGsGuard scripted agent with role-based behavior."""

from players.cogsguard.role.evolution.evolution import (
    BehaviorDef,
    BehaviorSource,
    EvolutionConfig,
    RoleCatalog,
    RoleDef,
    RoleTier,
    TierSelection,
    materialize_role_behaviors,
    mutate_role,
    pick_role_id_weighted,
    recombine_roles,
    record_behavior_score,
    record_role_score,
    sample_role,
)
from players.cogsguard.role.evolution.evolutionary_coordinator import (
    EvolutionaryRoleCoordinator,
)
from players.cogsguard.role.behavior_hooks import build_cogsguard_behavior_hooks
from players.cogsguard.role.control_agent import CogsguardControlAgent
from players.cogsguard.role.policy import CogsguardPolicy, CogsguardWomboPolicy
from players.cogsguard.role.targeted_agent import CogsguardTargetedAgent
from players.cogsguard.role.teacher import CogsguardTeacherPolicy
from players.cogsguard.role.v2_agent import CogsguardV2Agent

__all__ = [
    "CogsguardControlAgent",
    "CogsguardPolicy",
    "CogsguardWomboPolicy",
    "CogsguardTargetedAgent",
    "CogsguardTeacherPolicy",
    "CogsguardV2Agent",
    # Evolution types
    "BehaviorDef",
    "BehaviorSource",
    "EvolutionConfig",
    "RoleCatalog",
    "RoleDef",
    "RoleTier",
    "TierSelection",
    # Evolution functions
    "materialize_role_behaviors",
    "mutate_role",
    "pick_role_id_weighted",
    "recombine_roles",
    "record_behavior_score",
    "record_role_score",
    "sample_role",
    # Coordinator + hooks
    "EvolutionaryRoleCoordinator",
    "build_cogsguard_behavior_hooks",
]
