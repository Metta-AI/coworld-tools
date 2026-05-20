# Finding: cogsguard baseline-family policies crash on recipe discovery

**Status:** Open, pre-existing — independent of any docker / packaging work.
**Discovered:** 2026-05 during the image-contract test build-out.
**Affected versions:** Reproduced against `mettagrid 0.26.20`, `cogames 0.27.2`,
`cogsguard 0.0.0.post1.dev10` (the versions currently pinned in this repo).

## Symptom

When a freshly-constructed `BaselinePolicy` is driven against the standard
cogsguard missions (`make_machina1_mission`, `make_tutorial_mission`), the very
first call to `step_with_state` reaches `_calculate_deficits` and raises:

```
RuntimeError: Heart recipe not discovered! Agent must observe hub with correct
vibe to learn recipe. Ensure protocol_details_obs=True in game config.
```

This reproduces in two independent code paths:

1. The engine's own `mettagrid.runner.rollout.run_episode_local` driving the
   policy in-process.
2. The Docker image-contract test that puts the policy behind the
   `coworld_json_bridge` and feeds it real `AgentObservation` triplets over a
   websocket.

Both paths fail at the same site, so this is not a test-harness artifact.

## Mechanism

`BaselinePolicy._calculate_deficits` requires `state.heart_recipe` to be
populated before the first gather action. The recipe is learned from
observation tokens with feature ids in the `protocol_input:*` /
`protocol_output:*` range (36..59 in this build). These tokens are emitted by
the C++ observation encoder **only when the observed hub or extractor has a
non-empty `current_protocol`**.

Inspecting the live grid in both `machina_1` and `tutorial`:

- Every hub and every extractor exposes `current_protocol_inputs = None` and
  `current_protocol_outputs = None` at step 0.
- Walking the agent adjacent, issuing `change_vibe_heart`, or stepping through
  60 noops never causes those properties to become non-None, and no token in
  the protocol-feature range ever appears in the agent's observation.

No engine knob found so far primes `current_protocol` at episode start, and
no action sequence we've tried causes it to be assigned. The conditional
emission in the encoder is therefore correct — there is genuinely no active
protocol to encode — but the policy has no way to discover the recipe and
crashes deterministically.

## What is not affected

- `test_cogsguard_guardrails.py` exercises the `role` policy with `gear=1`
  (miner role) against `Planky*` diagnostic missions that pre-seed inventory.
  That policy does not need recipe discovery, so it does not hit this crash.
  This is why the guardrail suite currently passes despite the baseline
  policy being broken.
- The image-lifecycle contract test (`test_image_lifecycle.py`) deliberately
  does **not** drive the obs→action loop, so it remains a valid check of
  Dockerfile, env wiring, `COGAMES_POLICY_DISCOVERY_PACKAGES`, entrypoint,
  bridge `configure()`, and clean shutdown — for every cogsguard leaf.

## Affected images

The baseline-family policies share `_calculate_deficits`, so the issue is
expected to reproduce for:

- `players-cogsguard-baseline:dev` (URI `metta://policy/baseline`)
- `players-cogsguard-tiny-baseline:dev` (URI `metta://policy/tiny_baseline`)
- `players-cogsguard-buggy:dev` (URI `metta://policy/buggy`)
- `players-cogsguard-cranky:dev` (URI `metta://policy/cranky`)

`players-cogsguard-role:dev` (URI `metta://policy/role`) and
`players-cogsguard-nim:dev` (URI `metta://policy/thinky`) take a different
path and are not known to hit this crash.

## Possible follow-ups

1. Audit the `machina_1` / `tutorial` mission configs and the `protocols`
   variant chain to find out whether `current_protocol` is meant to be
   assigned by a variant that's currently missing from the recipe.
2. Check the upstream mettagrid / cogsguard repo for changes since the
   pinned versions — recipe discovery may have been refactored to use a
   different signaling channel.
3. If discovery is supposed to come from `change_vibe_<recipe>` + adjacent
   hub interaction, trace why that interaction is not surfacing tokens in
   this build.
4. Either way, the baseline policy needs a safe fallback (skip
   `_calculate_deficits`, idle, or no-op gather) when `heart_recipe` is
   still unknown after N steps, rather than crashing the episode.
