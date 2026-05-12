"""Game configuration template.

Copy this file to your game directory and customize.

Editable files: list every file the evolution agent is allowed to modify.
Evolution prompt: tells the evolution agent about your game's architecture.
Analysis prompt: tells the analysis LLM how to evaluate a game.

The framework wiki (policies/framework/wiki/) provides universal skills and
strategy docs. Your game's wiki/ adds game-specific knowledge. Both are
loaded into the LLM system prompt automatically.
"""

from __future__ import annotations

from framework.base_evolution import GameEvolutionConfig

EDITABLE_FILES = [
  # Decision logic — the main evolution target
  "policies/games/new_game/brain.py",
  # Game-specific wiki — evolves alongside the brain
  "policies/games/new_game/wiki/strategy/opening.md",
  "policies/games/new_game/wiki/strategy/common-mistakes.md",
  # Add more editable files as your game grows:
  # "policies/games/new_game/triggers.py",
  # "policies/games/new_game/wiki/skills/your_skill.md",
]

EVOLUTION_SYSTEM_PROMPT = """\
You are a game AI policy engineer. You just finished analyzing a completed
game. Your job is to make 1-3 targeted code changes to improve the agent's
policy based on what went wrong.

## Rules

1. Your ONLY available tool is str_replace. Make MINIMAL, SURGICAL changes.
2. Only edit files in the editable files list:
{editable_files}
3. After making changes, write a ONE PARAGRAPH summary.
4. Refer to framework/wiki/ for universal patterns (memory, triggers, etc.)
   but do NOT edit framework files — only game-specific files.

## Game Context

Game: {game_name}
Game ID: {game_id}

## Architecture

The agent uses the framework's BaseBrain/BasePolicy architecture:
- brain.py: per-tick decision logic (decide method returns a Command)
- triggers.py: event detection (fires LLM consultations)
- harness.py: LLM context building and directive parsing
- policy.py: perceive/execute bridge to the game engine
- wiki/: game-specific strategy knowledge loaded into LLM prompts

## TODO: Add game-specific details
- What are the available actions?
- What does the observation look like?
- What roles/strategies exist?
"""

ANALYSIS_SYSTEM_PROMPT = """\
You are analyzing a completed game to extract reusable strategic insights.

Review the memory dump (events, strategic facts, performance metrics) and
identify what worked, what failed, and what concrete rules should guide
future games.

## TODO: Add game-specific analysis instructions
- What constitutes a good score?
- What are the key strategic dimensions?
- What common failure modes should you look for?

Respond with JSON (no markdown fences):
{{
  "score": 7,
  "what_worked": ["insight 1"],
  "what_failed": ["failure 1"],
  "actionable_rules": ["IF x THEN y"],
  "biggest_mistake": "the single most impactful error",
  "recommended_next_game_strategy": "what to do differently"
}}
"""

GAME_EVOLUTION_CONFIG = GameEvolutionConfig(
  game_name="new_game",
  editable_files=EDITABLE_FILES,
  system_prompt_template=EVOLUTION_SYSTEM_PROMPT,
  policy_dir_glob="policies/games/new_game/",
)
