# Grader Design

> **Status:** placeholder. The coworld `grader` role exists in the manifest schema, but there is no finalized runtime contract yet.

## Purpose

Graders are intended to evaluate coworld outputs, player behavior, submissions, or episode artifacts and produce grading results for tournament or Observatory workflows.

The exact trigger, inputs, output envelope, certification behavior, and Observatory/API surface are still undecided.

## Current facts from metta

- `CoworldManifest.grader` is a list of `CoworldDeclaredRoleSpec`.
- The allowed role type enum includes `"grader"`.
- Certification checks declared grader images for reachability.
- The episode runner does not currently launch graders.
- There are no in-tree grader examples or grader tests yet.

## Open questions

1. Does a grader run per episode, per round, per submission, or on demand?
2. What artifacts does it read: results, replay, logs, manifest, policy metadata, or commissioner state?
3. Does it produce authoritative scores, advisory diagnostics, validation errors, or all of the above?
4. Is failure fatal to the episode, fatal to certification only, or recorded as a separate grader status?
5. Should grader outputs have a platform-enforced schema?
6. How should grader outputs surface in Observatory and the coworld CLI?

## Scaffold rules

- Keep each implementation in one leaf directory under `graders/<game>/<name>/`.
- Use `graders/templates/grader_template/` as the starting point for new placeholders.
- Do not add runtime assumptions to implementation code before the contract is documented in metta.
- When the contract is defined, mirror the final runtime obligations into this file and into the metta coworld docs.
