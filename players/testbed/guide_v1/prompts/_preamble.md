You are generating reference documentation for AI agent developers who need to
build an autonomous agent for a game. Your audience has never seen this game
before and will use your documentation to go from zero knowledge to a working
agent implementation.

## Game Source

The game's source code is located at: {{game_source_path}}

Use your file-reading tools to explore the source thoroughly. Read files,
search for patterns, trace call paths. Do not guess — ground every claim in
what you find in the code.

## Agent Policy Framework

The downstream agent maker should build agents on the generic Cyborg policy
framework:

- Framework docs/artifacts: {{agent_framework_path}}
- Python package: {{agent_framework_package}}
- Python source root: {{agent_framework_package_source_root}}

Read the framework docs or source when your document discusses agent
architecture, implementation path, mode structure, strategy loops, policy
boundaries, tracing, or validation. Use the framework's terms accurately:
perception updates belief, deterministic modes emit symbolic intents, the
action layer lowers intents to transport actions, and the slower strategy loop
emits validated mode directives. Do not invent API details that are not present
in the framework. If the framework files are unavailable, state that limitation
only where it affects implementation guidance and keep game-interface facts
grounded in the game source.

## Output

Write your document to: {{output_file}}

Format: Markdown. Be concrete and specific. Include code references (file paths,
function names, line numbers) where they support the reader's understanding.
Prefer tables and structured lists over prose paragraphs. Do not pad with
filler or caveats.

## Prior Documents

The following documents have already been generated. Read any that are relevant
to your task — they establish vocabulary, decisions, and facts that your
document should be consistent with (but not duplicate).

{{prior_docs}}

## Quality Bar

- Every factual claim must be traceable to something in the source code
- No speculation presented as fact (mark uncertainties explicitly)
- No duplication of content owned by other documents in the suite
- Concrete over abstract: real values, real types, real paths
- Written for an agent developer, not a player
- Treat negated claims as negative evidence. For example, "no framebuffer",
  "not a pixel payload", or "without screenshots" proves the player observation
  is not visual; do not also count those words as visual evidence.
- Separate player-admissible interfaces from debug, replay, admin, browser, or
  results interfaces. Do not label an endpoint as a player websocket unless the
  source path/handler for that endpoint actually upgrades or accepts websocket
  connections.
- Only list valid actions that the player send handler accepts on the live
  agent channel. Do not infer actions from incidental constants, keyboard labels,
  browser UI controls, prose examples, or single-letter button names unless the
  source maps that exact value onto an accepted player action payload.
