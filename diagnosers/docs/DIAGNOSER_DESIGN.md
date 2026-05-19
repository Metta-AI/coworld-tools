# Diagnoser Design

> **Status:** placeholder. The coworld `diagnoser` role exists in the manifest schema, but there is no finalized runtime contract yet.

## Purpose

Diagnosers are intended to inspect coworld failures, policy behavior, logs, replay artifacts, or unusual tournament outcomes and produce diagnostic artifacts for developers and operators.

The exact trigger, inputs, output envelope, certification behavior, and Observatory/API surface are still undecided.

## Current facts from metta

- `CoworldManifest.diagnoser` is a list of `CoworldDeclaredRoleSpec`.
- The allowed role type enum includes `"diagnoser"`.
- Certification checks declared diagnoser images for reachability.
- The episode runner does not currently launch diagnosers.
- There are no in-tree diagnoser examples or diagnoser tests yet.

## Open questions

1. Does a diagnoser run on failed episodes only, successful episodes too, per round, or on demand?
2. What artifacts does it read: logs, results, replay, manifest, commissioner state, policy metadata, or runner diagnostics?
3. Does it produce structured diagnoses, Markdown reports, traces, replay annotations, or remediation suggestions?
4. Is failure fatal to certification, recorded as separate status, or ignored when diagnosis is best-effort?
5. Should diagnoser outputs be private/operator-only or visible in Observatory?
6. How should diagnoser outputs be fetched from the coworld CLI?

## Scaffold rules

- Keep each implementation in one leaf directory under `diagnosers/<game>/<name>/`.
- Use `diagnosers/templates/diagnoser_template/` as the starting point for new placeholders.
- Do not add runtime assumptions to implementation code before the contract is documented in metta.
- When the contract is defined, mirror the final runtime obligations into this file and into the metta coworld docs.
