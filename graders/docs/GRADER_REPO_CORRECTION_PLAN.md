# Grader Repo Correction Plan

## Source Of Truth

Authoritative Coworld docs and schemas live in `~/coding/metta/packages/coworld/`.
For this update, treat these files as the contract:

- `packages/coworld/src/coworld/docs/roles/grader.md`
- `packages/coworld/src/coworld/docs/roles/OVERVIEW.md`
- `packages/coworld/src/coworld/EPISODE_BUNDLE_README.md`
- `packages/coworld/src/coworld/MANIFEST_README.md`
- `packages/coworld/src/coworld/coworld_manifest_schema.json`
- `docs/specs/0045-coworld-role-repos.md`

Important current facts:

- The grader role is still `reserved`, and the runtime contract is explicitly tentative.
- The tentative grader contract is defined: read `COGAME_EPISODE_BUNDLE_URI`, inspect the bundle zip, and write JSON to `COGAME_GRADE_URI`.
- Grader output must include `score`; `grader_id` is recommended.
- Supporting runnables are on-demand; the episode runner does not automatically launch graders.
- Role repos must provide a root `CATALOG.yaml`; source present without a catalog entry is incomplete.

## Problems To Fix

1. `graders/among_them/among_them_grader/among_them_grader.py` implements an older per-artifact env-var contract:
   `COGAME_RESULTS_URI` -> `COGAME_GRADE_OUTPUT_URI`.
2. `graders/among_them/among_them_grader/README.md` documents the same stale contract.
3. `README.md`, `docs/COWORLD_REFERENCE.md`, and `docs/GRADER_DESIGN.md` describe the grader role as undefined or optional,
   while the current Coworld docs define a tentative on-demand bundle contract.
4. `README.md` links to stale source-of-truth paths, including a missing `docs/specs/0043-user-container-management.md`.
5. This repo has no root `CATALOG.yaml`.
6. Empty scaffold directories exist for template, PaintArena, and Cogs vs Clips; they should remain clearly non-implementations
   unless source and catalog entries are added.

## Implementation Plan

1. Update the Among Them grader implementation.
   - Read `COGAME_EPISODE_BUNDLE_URI`.
   - Open the zip bundle and read `manifest.json`.
   - Locate `results.json` through `manifest.files.results`, falling back to `results.json` only if the manifest is incomplete.
   - Write JSON to `COGAME_GRADE_URI`.
   - Include both `score` and `grader_id`.
   - Support local paths, `file://`, HTTP(S), and `s3://` URI handling via lazy `boto3` import so hosted-mode
     compatibility does not affect local tests.

2. Add focused tests.
   - Test `interestingness()` with a representative results object.
   - Test the full entrypoint using a temporary episode bundle and local output path.
   - Test `file://` output path handling.
   - Avoid Docker or network dependency in tests.

3. Add root `CATALOG.yaml`.
   - Include only the real Among Them implementation.
   - Do not catalog empty scaffolds.
   - Use a local image name that matches the current build script unless/until a Softmax-published image is assigned.

4. Refresh documentation.
   - Update root `README.md` to point to the current authoritative files and clarify the role is reserved but has a tentative contract.
   - Update `docs/COWORLD_REFERENCE.md` to be an index into current Coworld docs rather than a stale mini-spec.
   - Update `docs/GRADER_DESIGN.md` to preserve the still-open decisions without claiming the contract is absent.
   - Update the Among Them grader README to document bundle input, grade output, `grader_id`, and score scale.
   - Leave empty scaffold READMEs untouched unless they need explicit "empty placeholder" text after the main docs are corrected.

5. Validate.
   - Run the new focused tests with the project Python (`python3` in this checkout).
   - Run `python3 -m compileall` over the implementation tree if pytest is unavailable.
   - Run `git diff --check`.
   - Search for stale env vars and stale source references:
     `COGAME_RESULTS_URI`, `COGAME_GRADE_OUTPUT_URI`, `0043-user-container-management`, `undefined stubs`, and
     `no documented runtime contract`.

## Sanity Check Notes

Attempted external sanity check:

```bash
auggie --print "Sanity check this correction plan for the Metta-AI/graders repo. Treat ~/coding/metta/packages/coworld as authoritative. Focus on whether the implementation steps are technically correct, too broad, or missing important constraints. Plan file: docs/GRADER_REPO_CORRECTION_PLAN.md"
```

The sandboxed run could not reach Augment, and the escalated rerun was rejected by policy because it would send private
workspace context to an external service. The local replacement sanity check changed the plan to account for the
authoritative `COGAME_GRADE_URI` `s3://` hosted-output case.

## Non-Goals

- Do not change authoritative Coworld docs in `~/coding/metta`.
- Do not add hosted runtime or `coworld run-grader` support.
- Do not publish images, push branches, or open a PR.
- Do not turn empty scaffold directories into real implementations.

## Expected End State

- This repo states that it follows the current tentative Coworld grader contract.
- The only real grader implementation can run from an episode bundle and write the documented grade output.
- The repo has a catalog entry for its real implementation.
- Remaining open questions are accurately framed as Coworld contract questions, not repo-local inventions.
