# Coworld Tools

This repository collects Coworld game and supporting-role implementations in one public place.

## Intended Coworld Workflow

This repository is the shared source for Coworld examples and reusable pieces, not the final home for a specific
Coworld's production code.

When creating or updating a Coworld, start from:

- the templates in `packages/coworld` in the `metta` repo;
- the PaintArena example in `packages/coworld`, when it is the closest shape for the piece you are building;
- an existing game, player, commissioner, reporter, grader, or diagnoser implementation in this `coworld-tools` repo.

Copy the relevant piece into the specific Coworld repository and keep it there under the matching role folder. For
example, a new `coworld-muster` repo should own its commissioner code under a path like `commissioner/`, copied from the
closest template or existing implementation. That Coworld repo is then the canonical place to evolve the bespoke code
for that Coworld.

## Layout

- `games/` - imported from `Metta-AI/games`
- `players/` - imported from `Metta-AI/players`
- `commissioners/` - imported from `Metta-AI/commissioners`
- `reporters/` - imported from `Metta-AI/reporters`
- `graders/` - imported from `Metta-AI/graders`
- `diagnosers/` - imported from `Metta-AI/diagnosers`

Each source repository's `main` branch history was rewritten under its folder and merged into this repository.

See `IMPORTED_REPOS.md` for source commit provenance.
