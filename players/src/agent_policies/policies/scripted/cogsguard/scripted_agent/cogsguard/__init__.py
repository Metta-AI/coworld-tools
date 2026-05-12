"""CoGsGuard scripted agent with role-based behavior."""

from agent_policies.policies.scripted.cogsguard.evolution.cogsguard.evolution import (
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
from agent_policies.policies.scripted.cogsguard.evolution.cogsguard.evolutionary_coordinator import (
    EvolutionaryRoleCoordinator,
)
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.behavior_hooks import build_cogsguard_behavior_hooks
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.control_agent import CogsguardControlAgent
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.policy import CogsguardPolicy, CogsguardWomboPolicy
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.targeted_agent import CogsguardTargetedAgent
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.teacher import CogsguardTeacherPolicy
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.v2_agent import CogsguardV2Agent

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
