# eyes_v1 Deprecation Note

## Decision

`eyes_v1` is deprecated as a primary Cogbase pipeline stage. Keep the code for
reference and targeted visual-artifact experiments, but do not use it as the
canonical way to understand a new game.

`guide_v1` is the canonical front door for game understanding. It owns the
source-grounded guide bundle, including the agent interface contract,
observation decoding, state/view model, and the classification of a game's
observation surface as symbolic, visual, or mixed.

## Rationale

The useful documentation work that `eyes_v1` attempted to do overlaps heavily
with `guide_v1`:

- UI and view inventory belong in `STATE_AND_VIEW_MODEL.md` and
  `OBSERVATION_DECODING.md`.
- Protocol and observation details belong in `INTERFACE_CONTRACT.md`.
- Action and navigation requirements belong in `ACTION_SEMANTICS_AND_CONTROL.md`
  and `MINIMUM_VIABLE_AGENT.md`.
- Training fixtures and visual parsing risks belong in
  `TRAINING_AND_EVALUATION.md`, `ERROR_RECOVERY_AND_ROBUSTNESS.md`, and
  generated downstream artifact plans.

The remaining `eyes_v1` value is automated frame capture and visual fixture
generation. That is useful, but it is not a safe first-stage abstraction. In
visual-only domains, automatic capture can become circular: an explorer must
already parse enough of the frames to navigate to the views it is supposed to
collect for perception development.

## Replacement Model

Use `guide_v1` first:

1. Generate or update the guide bundle for the target game.
2. Confirm the player observation surface from source.
3. Classify it as symbolic, visual, or mixed.
4. If visual evidence is needed, generate targeted downstream artifacts:
   capture plans, frame fixtures, replay/global-view captures, parser tests, or
   instrumented harnesses.

The `maker_v1` stage owns the next step: turning guide bundles into baseline
agent artifacts. It now produces plan artifacts, starter symbolic agents for
symbolic-primary games, capture-only visual shells for visual or
mixed/alternate games, and an offline visual bootstrap loop over captured image
frames using mock labels or AWS Bedrock Claude labels. `eyes_v1` code may be
reused for targeted visual artifacts, but outputs from that reuse belong under
an `output/<game>/`
artifact directory and should not be treated as toolkit code or authoritative
documentation. See `maker_v1_design.md` for the VLM-assisted visual bootstrap
model.

## Status

- `testbed/guide_v1/` remains active prototype toolkit code.
- `testbed/eyes_v1/` remains in place as deprecated prototype code.
- Existing `eyes_v1` generated artifacts are historical outputs.
- New games should not start with `eyes_v1`; start with `guide_v1`.
