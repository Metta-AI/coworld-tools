# Docs Index

## Audit & Game State
- **[`audit_episode_results.md`](audit_episode_results.md)**: Latest episode audit results — which mechanics fire, what's broken, root causes, and recommendations. **Start here for current game state.**
- **[`audit_tools.md`](audit_tools.md)**: Reference for all instrumentation tools — compile-time flags, scripts, per-agent stats, replay system, and known gaps.

## Getting Started
- `quickstart.md`: prerequisites, building, running, testing, and environment variables.
- `metta_integration.md`: how Tribal Cog fits `Metta-AI/games`, Metta recipes, CoGames optional loading, and future Coworld packaging.
- `cli_and_debugging.md`: CLI usage, debugging flags, common failure modes.
- `cogame_template.md`: template upstream and merge guidance.

## Architecture & Configuration
- `architecture.md`: high-level codebase architecture and module layout.
- `configuration.md`: tunable constants and configuration reference.
- `action_space.md`: action encoding, verbs, and argument layout.
- `observation_space.md`: observation tensor layout and tint codes.
- `python_api.md`: Python wrapper, PufferLib integration, examples.

## Gameplay Systems
- `game_logic.md`: step loop, actions, entities, victory conditions, production queues, tech trees, unit commands.
- `combat.md`: combat rules, counters, siege, trebuchets, attack-move, patrol, unit stances, cliff fall damage.
- `economy_respawn.md`: inventory, stockpiles, markets, AoE2 trade, Trade Cogs, biome bonuses, hearts, respawns.
- `victory_conditions.md`: victory condition mechanics and configuration.
- `population_and_housing.md`: pop-cap and housing details.
- `clippy_tint_freeze.md`: territory tinting, tumors, and frozen tiles.
- `wildlife_predators.md`: wildlife spawn and behavior rules.
- `temple_hybridization.md`: temple-based hybrid spawn notes.

## AI
- `ai_system.md`: AI roles, inter-role coordination, shared threat maps, adaptive difficulty, economy management, scout exploration, OptionDef behavior model, evolution toggle.

## World Generation
- `world_generation.md`: trading hub, rivers, goblin hives, tuning notes.
- `spawn_pipeline.md`: spawn order, placement helpers, and connectivity pass.
- `terrain_biomes.md`: biome masks, elevation, cliffs, ramps, mud, water depth, movement speed modifiers, biome resource bonuses, connectivity.

## Visuals & Assets
- `asset_pipeline.md`: asset generation and wiring guidance.
- `combat_visuals.md`: combat tint/visual feedback specifics.
- `recently-merged-features.md`: recently merged feature documentation.

## Testing
- `testing.md`: test organization, `behavior_*` vs `domain_*` conventions, naming guidelines.
- `test-audit-report.md`: test suite audit findings and recommendations.

## Training
- `training_and_replays.md`: training entrypoints and replay writer setup.

## Performance
- `performance_optimization_roadmap.md`: consolidated performance audits, completed optimizations, and open optimization roadmap.
- `data_structure_audit.md`: data structure performance audit.
- `audit_spatial_systems.md`: spatial systems performance audit.

## Analysis (`analysis/`)
- `analysis/ai_behavior_analysis.md`: AI role overview and invalid action root causes.
- `analysis/codebase_audit.md`: full codebase audit.
- `analysis/docs_accuracy_audit.md`: documentation accuracy audit.
- `analysis/entity_interaction_analysis.md`: entity interaction analysis.
- `analysis/game_mechanics_analysis.md`: game mechanics action failure analysis.
- `analysis/role_audit_report.md`: AI role audit report.
- `analysis/spatial_stats_audit.md`: spatial statistics audit.
- `analysis/temple_hybridization_audit.md`: temple hybridization audit.
- `analysis/terrain_biomes_audit.md`: terrain and biomes audit.
- `ai-control-gap-analysis.md`: AI control gap analysis.
- `audit-world-sim-core.md`: world simulation core audit.

## Archive
Archive directory removed — all historical plans and completed audits have been deleted.
Active performance analysis lives in `performance_optimization_roadmap.md`.
