# Player SDK docs

Documentation for `players.player_sdk` (the Coworld Player SDK / Cyborg
framework).

## Framework reference

- [`metta_cogames_framework/README.md`](metta_cogames_framework/README.md) —
  the Cyborg two-loop architecture: layers, contracts, and design rationale.
- [`metta_cogames_framework/PYTHON_FRAMEWORK.md`](metta_cogames_framework/PYTHON_FRAMEWORK.md) —
  quickstart for building a new agent on the SDK.
- [`metta_cogames_framework/SOURCE_REPOS.md`](metta_cogames_framework/SOURCE_REPOS.md) —
  historical source pointers that informed the first version.

## Designs

Living design documents for SDK evolution.

- [`designs/generalizing-the-sdk-for-turn-based-games.md`](designs/generalizing-the-sdk-for-turn-based-games.md) —
  how to make the SDK useful for turn-based / message-driven games (e.g. Cue n
  Woo) without removing the gridworld machinery: an explicit telemetry/grid
  boundary, a generic message bridge, a shared LLM-client helper, an opaque
  trace step coordinate, and a reusable `TraceConfig` base. Prioritized plan.
