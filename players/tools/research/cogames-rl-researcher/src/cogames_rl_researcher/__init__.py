"""Claude-first RL researcher workflows for CoGames."""

from cogames_rl_researcher.actor_critic import (
    ActorCriticReport,
    FixPackProposal,
    LogMiningContext,
    analyze_actor_critic,
)
from cogames_rl_researcher.coverage import (
    CoveragePackSummary,
    CoverageVariant,
    run_submit_coverage_pack,
)
from cogames_rl_researcher.coverage_tuning import (
    CoverageTuningPlan,
    CoverageTuningProposal,
    build_coverage_tuning_plan,
)
from cogames_rl_researcher.defects import (
    CrashDefect,
    DefectBacklog,
    DefectFixAttempt,
    DefectFixPlan,
    build_defect_backlog,
    build_defect_fix_plan,
    set_defect_status,
    submit_crash_defect,
    validate_defect_fix,
)
from cogames_rl_researcher.log_mining import (
    LogMiningConfig,
    LogMiningReport,
    mine_cogames_failures,
    run_log_mining_service,
)
from cogames_rl_researcher.pickup import PickupConfig, PickupResult, run_pickup
from cogames_rl_researcher.research_command import (
    ResearchCommandConfig,
    ResearchCommandSummary,
    run_research_command,
)
from cogames_rl_researcher.resume import ResumeConfig, run_resume
from cogames_rl_researcher.startup import StartupConfig, run_startup
from cogames_rl_researcher.swarm import SwarmConfig, SwarmPlan, build_swarm_plan

__all__ = [
    "StartupConfig",
    "run_startup",
    "ResumeConfig",
    "run_resume",
    "CoverageVariant",
    "CoveragePackSummary",
    "run_submit_coverage_pack",
    "CoverageTuningPlan",
    "CoverageTuningProposal",
    "build_coverage_tuning_plan",
    "LogMiningConfig",
    "LogMiningReport",
    "mine_cogames_failures",
    "run_log_mining_service",
    "CrashDefect",
    "DefectBacklog",
    "DefectFixPlan",
    "DefectFixAttempt",
    "submit_crash_defect",
    "set_defect_status",
    "build_defect_backlog",
    "build_defect_fix_plan",
    "validate_defect_fix",
    "ResearchCommandConfig",
    "ResearchCommandSummary",
    "run_research_command",
    "PickupConfig",
    "PickupResult",
    "run_pickup",
    "ActorCriticReport",
    "FixPackProposal",
    "LogMiningContext",
    "analyze_actor_critic",
    "SwarmConfig",
    "SwarmPlan",
    "build_swarm_plan",
]
