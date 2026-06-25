# Coworld Tools

This repository collects shared Coworld game and supporting-role implementations in one public place.

The old standalone role repos (`players`, `commissioners`, `reporters`, `graders`, and `diagnosers`) are archived
pointers to this repo. New shared role work belongs here. Game-specific pieces belong beside their game in the relevant
`Metta-AI/coworld-<slug>` repo.

When rebuilding a Coworld, choose exactly one source owner for each runnable:

- use a `coworld-tools/...` path for a shared implementation; or
- use a `coworld-<slug>/...` path for a game-local implementation.

Do not patch archived role repos, and do not keep one runnable split between `coworld-tools` and the game repo. The
Coworld manifest's `source_url` should point to the chosen owner and be pinned to a commit SHA before certification.

## Layout

- `games/` - imported from `Metta-AI/games`
- `players/` - imported from `Metta-AI/players`
- `commissioners/` - imported from `Metta-AI/commissioners`
- `reporters/` - imported from `Metta-AI/reporters`
- `graders/` - imported from `Metta-AI/graders`
- `diagnosers/` - imported from `Metta-AI/diagnosers`

Each source repository's `main` branch history was rewritten under its folder and merged into this repository.

See `IMPORTED_REPOS.md` for source commit provenance.
