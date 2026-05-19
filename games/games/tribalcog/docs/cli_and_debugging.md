# CLI Playbook and Debugging

Date: 2026-02-06
Owner: Docs / Systems
Status: Active

## Purpose
This document consolidates the CLI and runtime issues seen in recent sessions.
It gives a single source of truth for how to run the game, what the CLI actually does, and
how to debug common failures.

## Canonical Run Commands
Preferred (CLI):
- `tribalcog play`
- `tribalcog` (defaults to `play` when no subcommand is provided)

Text-only smoke test (no GUI):
- `tribalcog play --render ansi --steps 128`

Direct Nim run (bypasses Python CLI):
- `nim r -d:release --path:src tribal_village.nim`

### Makefile Targets

| Target | Description |
|--------|-------------|
| `make check` | CI gate: syncs deps + runs `nim check` |
| `make build` / `make lib` | Build shared library via `nimble buildLib` |
| `make test` | Run all tests (Nim + Python) |
| `make test-nim` | Nim unit and integration tests only |
| `make test-python` | Python integration tests (builds lib first) |
| `make test-integration` | Full integration suite (Nim + Python end-to-end) |
| `make test-settlement` | Settlement behavior tests |
| `make audit-settlement` | Audit settlement expansion metrics |
| `make benchmark` | Steps/second benchmark with perf regression instrumentation |
| `make clean` | Remove build artifacts |

Key files:
- `tribal_village_env/cli.py` (CLI entry point)
- `tribal_village_env/build.py` (Nim toolchain + lib build)
- `tribal_village.nim` (Nim GUI main, at repo root)
- `Makefile` (build/test/benchmark targets)

## What the CLI Actually Does
- Ensures the Nim library is built and up-to-date via `ensure_nim_library_current()`.
- Bootstraps `nimby` if needed and installs Nim into `~/.nimby/nim/bin`.
- Launches `nim r -d:release --path:src tribal_village.nim` for GUI mode.

## Debug Flags and Timers
Use these to confirm the sim is stepping or to identify stalls:
- `--profile` and `--profile-steps` (headless profile run)
- `--step-timing` with `--step-timing-target` and `--step-timing-window`
- `--render-timing` with `--render-timing-target` and `--render-timing-window`

When running Nim directly, the CLI sets these environment variables for you:
- `TV_PROFILE_STEPS`
- `TV_STEP_TIMING`, `TV_STEP_TIMING_WINDOW`
- `TV_RENDER_TIMING`, `TV_RENDER_TIMING_WINDOW`, `TV_RENDER_TIMING_EVERY`, `TV_RENDER_TIMING_EXIT`

## Common Failure Modes and Fixes

### "Got unexpected extra argument (play)"
Seen when using older or mismatched CLI builds (for example, an older metta package).
Fix:
- Run `tribalcog` without the `play` subcommand, or
- Reinstall from this repo so `tribalcog play` is registered.

### "FileNotFoundError: nimble" or "nim" not found
Indicates the Nim toolchain is missing from PATH.
Fix:
- Install Nim with `nimby` (see README Quick Start).
- Ensure `~/.nimby/nim/bin` is on PATH.

### "key not found: resources/wood" or other missing sprite errors
Indicates missing assets or a stale asset map.
Fix:
- Verify required files exist under `data/` and `data/oriented/`.
- Regenerate assets via `scripts/generate_assets.py` if needed.

### GUI seems to hang after "[Exec]"
Often the sim is running but the GUI window is blocked or rendering is stalled.
Fix:
- Run ANSI mode to confirm stepping: `tribalcog play --render ansi`.
- Enable `--step-timing` or `--render-timing` to see progress.
- Verify OpenGL availability on the local machine.

## Fast Triage Checklist
1. `make check` (confirm code compiles)
2. `tribalcog --help` (confirm you are using the correct CLI)
3. `tribalcog play --render ansi --steps 32` (confirm stepping)
4. `nim r -d:release --path:src tribal_village.nim` (confirm Nim GUI path)
5. Check assets exist under `data/` and `data/oriented/`
