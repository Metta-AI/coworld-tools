# Commissioner Design

> **Status:** implementation-repo placeholder. The canonical commissioner protocol already lives in metta at `packages/coworld/src/coworld/commissioner/protocol.py`.

## Purpose

Commissioners orchestrate tournament rounds. They receive league/division/membership context and recent results, then return episode schedules or round-complete decisions.

This repo should hold commissioner implementations and scaffolding. It should not fork or redefine the protocol.

## Current facts from metta

- `CoworldManifest.commissioner` is a list of `CoworldDeclaredRoleSpec`.
- The allowed role type enum includes `"commissioner"`.
- Certification checks declared commissioner images for reachability.
- `packages/coworld/src/coworld/commissioner/protocol.py` defines the protocol messages.
- Commissioner state continuity is owned by the platform, which threads opaque state between rounds.

## Implementation expectations

1. Implement against the metta commissioner protocol.
2. Keep state payloads explicit and documented in the leaf commissioner's README.
3. Keep scheduling decisions reproducible where possible.
4. Keep league/game-specific logic under `commissioners/<game>/<name>/`.
5. Update this document only with repo-local conventions. Protocol changes belong in metta first.

## Scaffold rules

- Keep each implementation in one leaf directory under `commissioners/<game>/<name>/`.
- Use `commissioners/templates/commissioner_template/` as the starting point for new placeholders.
- Each leaf README should document scheduling policy, expected state shape, and local test commands.
