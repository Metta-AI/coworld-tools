# Quickstart Guide

Date: 2026-02-06
Owner: Docs / Onboarding
Status: Active

This guide helps new developers get up and running with Tribal Village quickly.

## Prerequisites

### Nim

- **Version**: 2.2.4 or later (2.2.6 recommended)
- **Installation**: Use [nimby](https://github.com/treeform/nimby) for version management

```bash
# Download nimby (adjust URL for your platform)
curl -L https://github.com/treeform/nimby/releases/download/0.1.11/nimby-linux-x86_64 -o ./nimby
# macOS ARM: nimby-macOS-ARM64
# macOS x64: nimby-macOS-x86_64
chmod +x ./nimby

# Install Nim and sync dependencies
./nimby use 2.2.6
./nimby sync -g nimby.lock
```

After installation, ensure `~/.nimby/nim/bin` is on your PATH.

### Python (for training bindings)

- **Version**: 3.12.x
- **Packages**: gymnasium, numpy, pufferlib

```bash
pip install -e .
python -c "import tribal_village_env; print('import ok')"
```

For training support with CoGames/PufferLib:

```bash
pip install -e .[cogames]
```

### System Dependencies

- **OpenGL**: Required for graphical rendering
- **Linux**: OpenGL libraries (libGL, etc.)
- **macOS**: Metal/OpenGL (included with system)

## Building the Project

### Using the Makefile (Recommended)

The Makefile provides convenient targets for common operations:

```bash
make check          # CI gate: syncs deps + runs nim check
make build          # Build shared library (alias: make lib)
make test           # Run all tests (Nim + Python)
make test-nim       # Run Nim unit and integration tests only
make test-python    # Run Python integration tests (builds lib first)
make test-integration  # Full integration suite
make test-settlement   # Run settlement behavior tests
make audit-settlement  # Audit settlement expansion metrics
make benchmark      # Measure steps/second with perf regression instrumentation
make clean          # Remove build artifacts
```

### Basic Compilation

Compile and run with release optimizations:

```bash
nim r -d:release --path:src tribal_village.nim
```

Or compile only:

```bash
nim c -d:release --path:src tribal_village.nim
```

### With Evolution Enabled

The AI evolution layer is disabled by default. To enable:

```bash
nim r -d:release -d:enableEvolution --path:src tribal_village.nim
```

### With Step Timing

For per-step timing breakdown (useful for debugging performance):

```bash
nim r -d:stepTiming -d:release --path:src tribal_village.nim
```

Set environment variables to control timing output:

```bash
TV_STEP_TIMING=100 TV_STEP_TIMING_WINDOW=50 \
  nim r -d:stepTiming -d:release --path:src tribal_village.nim
```

## Running Headless (No Graphics)

### Headless via CLI

Using the Python CLI with ANSI rendering:

```bash
tribalcog play --render ansi --steps 128
```

## Running with Graphics

### Main Entry Point

The graphical viewer runs via:

```bash
nim r -d:release --path:src tribal_village.nim
```

Or through the Python CLI:

```bash
tribalcog play
# This internally runs: nim r -d:release tribal_village.nim
```

### Keyboard Controls

#### Simulation

| Key | Action |
|-----|--------|
| **Space** | Play/pause; step once when paused |
| **-** or **[** | Decrease simulation speed (0.5x) |
| **=** or **]** | Increase simulation speed (2x) |
| **N** / **M** | Cycle observation overlays |
| **Tab** | Cycle through teams (observer / team 0-7) |
| **F1-F8** | Quick switch to teams 0-7 |
| **F9** | Cycle weather effects (Rain / Wind / None) |

#### Mouse Controls

| Action | Effect |
|--------|--------|
| **Left-click** | Select unit/building (shift-click toggles) |
| **Left-drag** | Pan map (or drag-box multi-select on units) |
| **Right-click** | AoE2-style contextual command (move/attack/gather) |
| **Shift+Right-click** | Queue patrol waypoint |
| **Scroll wheel** | Zoom in/out |
| **Minimap click** | Pan camera to that location |

#### Unit Selection and Control

| Key | Action |
|-----|--------|
| **Ctrl+0-9** | Assign selection to control group |
| **0-9** | Recall control group (double-tap to center camera) |
| **S** | Stop |
| **H** | Hold position (fighters only) |
| **L / O / T** | Set formation (Line / Box / Staggered) |
| **W/S/A/D** | Move selected agent (cardinal) or pan camera |
| **Q/E/Z/C** | Move selected agent (diagonal) |
| **U** | Use/craft action in facing direction |

#### Building Placement (when villager selected)

| Key | Action |
|-----|--------|
| **B** | Open build menu |
| **Q/W/E/R/A/S/D/F/Z/X** | Build specific buildings (when menu open) |
| **Esc** | Cancel building placement |
| **Shift+Click** | Place multiple buildings |

### Render Timing

For frame-by-frame render timing:

```bash
nim r -d:renderTiming -d:release --path:src tribal_village.nim
```

With environment variable control:

```bash
TV_RENDER_TIMING=0 TV_RENDER_TIMING_WINDOW=100 TV_RENDER_TIMING_EVERY=10 \
  nim r -d:renderTiming -d:release --path:src tribal_village.nim
```

## Running Tests

### Using Makefile (Recommended)

```bash
make check          # Quick compilation check (syncs deps first)
make test           # Run all tests (Nim + Python)
make test-nim       # Nim unit/integration tests only
make test-python    # Python integration tests (builds lib first)
make test-settlement  # Settlement behavior tests
```

### Individual Test Files

```bash
nim r --path:src tests/test_balance_scorecard.nim
nim r --path:src tests/test_map_determinism.nim
nim r --path:src tests/test_score_tracking.nim
nim r --path:src tests/integration_behaviors.nim
```

### Validation Sequence

1. Compile check:
   ```bash
   make check
   ```

2. Smoke test (15s timeout):
   ```bash
   timeout 15s nim r -d:release --path:src tribal_village.nim
   ```

3. Test suite:
   ```bash
   make test-nim
   ```

## Environment Variables Reference

### Profiling

| Variable | Description | Default |
|----------|-------------|---------|
| `TV_PROFILE_STEPS` | Number of steps to run in headless profile mode | 3000 |
| `TV_PROFILE_REPORT_EVERY` | Log progress every N steps (0 disables) | 0 |
| `TV_PROFILE_SEED` | Random seed for profiling runs | 42 |

### Performance Regression Detection (requires `-d:perfRegression`)

| Variable | Description | Default |
|----------|-------------|---------|
| `TV_PERF_BASELINE` | Path to baseline JSON file to compare against | (none) |
| `TV_PERF_SAVE_BASELINE` | Path to save captured baseline (capture mode) | (none) |
| `TV_PERF_THRESHOLD` | Regression threshold percentage | 10 |
| `TV_PERF_WINDOW` | Sliding window size in steps | 100 |
| `TV_PERF_INTERVAL` | Report/check interval in steps | 100 |
| `TV_PERF_FAIL_ON_REGRESSION` | If "1", exit non-zero on regression (CI mode) | "0" |

### Step Timing (requires `-d:stepTiming`)

| Variable | Description | Default |
|----------|-------------|---------|
| `TV_STEP_TIMING` | Target step to start timing | -1 (disabled) |
| `TV_STEP_TIMING_WINDOW` | Number of steps to time | 0 |

### Render Timing (requires `-d:renderTiming`)

| Variable | Description | Default |
|----------|-------------|---------|
| `TV_RENDER_TIMING` | Target frame to start timing | -1 (disabled) |
| `TV_RENDER_TIMING_WINDOW` | Number of frames to time | 0 |
| `TV_RENDER_TIMING_EVERY` | Log every N frames | 1 |
| `TV_RENDER_TIMING_EXIT` | Exit after this frame | -1 (disabled) |

### Replay Recording

| Variable | Description | Default |
|----------|-------------|---------|
| `TV_REPLAY_DIR` | Directory for replay files | (none) |
| `TV_REPLAY_PATH` | Explicit replay file path (overrides dir) | (none) |
| `TV_REPLAY_NAME` | Base name for replay files | `tribal_village` |
| `TV_REPLAY_LABEL` | Label metadata in replay | `Tribal Village Replay` |

### Controller Mode

| Variable | Description |
|----------|-------------|
| `TRIBAL_PYTHON_CONTROL` | Use external neural network controller |
| `TRIBAL_EXTERNAL_CONTROL` | Use external neural network controller |

### Build Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TRIBAL_VILLAGE_NIM_VERSION` | Nim version for Python build | 2.2.6 |
| `TRIBAL_VILLAGE_NIMBY_VERSION` | Nimby version for Python build | 0.1.11 |
| `TRIBAL_VECTOR_BACKEND` | Vector backend for training (serial/ray) | serial |

## Quick Reference

### Common Commands

```bash
# Play with graphics
tribalcog play
nim r -d:release --path:src tribal_village.nim

# Headless smoke test
tribalcog play --render ansi --steps 128

# Compile check (CI gate)
make check

# Run all tests
make test

# Benchmark with perf regression detection
make benchmark

# Build shared library for Python
make build

# Train with CoGames
tribalcog train --steps 1000000 --parallel-envs 8 --num-workers 4 --log-outputs
```

### Compile-Time Flags

| Flag | Purpose |
|------|---------|
| `-d:release` | Enable optimizations |
| `-d:danger` | Maximum speed (no bounds checks) |
| `-d:stepTiming` | Enable step timing instrumentation |
| `-d:renderTiming` | Enable render timing instrumentation |
| `-d:perfRegression` | Enable performance regression detection |
| `-d:enableEvolution` | Enable AI evolution layer |
| `-d:audio` | Enable audio system |
| `-d:aiAudit` | Enable AI decision audit logging |
| `-d:actionAudit` | Enable action distribution logging |
| `-d:actionFreqCounter` | Enable action frequency by unit type |

See `docs/configuration.md` for detailed documentation of audit flags including
environment variables and performance implications.

## Troubleshooting

### "nim" or "nimble" not found

Ensure `~/.nimby/nim/bin` is on your PATH:

```bash
export PATH="$HOME/.nimby/nim/bin:$PATH"
```

### Missing sprite errors

Verify assets exist under `data/` and regenerate if needed:

```bash
python scripts/generate_assets.py
```

### GUI hangs after "[Exec]"

1. Try ANSI mode to confirm stepping works:
   ```bash
   tribalcog play --render ansi --steps 32
   ```

2. Enable step timing to see progress:
   ```bash
   TV_STEP_TIMING=0 TV_STEP_TIMING_WINDOW=100 \
     nim r -d:stepTiming -d:release --path:src tribal_village.nim
   ```

3. Verify OpenGL is available on your system.

## Next Steps

- See `docs/README.md` for the full documentation index
- See `docs/cli_and_debugging.md` for detailed CLI usage
- See `docs/performance_optimization_roadmap.md` for performance analysis
- See `docs/training_and_replays.md` for ML training setup
