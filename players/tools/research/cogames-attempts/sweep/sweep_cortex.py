#!/usr/bin/env python3
"""Hyperparameter sweep for Cortex architectures via cogames train.

Patches cogames' hardcoded PPO hyperparams by intercepting PuffeRL init.
This preserves the exact same env setup, vectorization, and training loop
as `cogames train` — only the target hyperparams change.

Usage:
    python3 sweep_cortex.py                    # run all configs
    python3 sweep_cortex.py --config 0         # run config 0 only
    python3 sweep_cortex.py --dry-run          # print configs without running
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Sweep configurations
# ---------------------------------------------------------------------------
# Each config overrides specific train_args keys passed to PuffeRL.
# Keys must match PufferLib's train_args dict exactly.
# See cogames/train.py for the full dict.

SWEEP_CONFIGS = [
    # Baseline: match cogames train defaults (control)
    {
        "name": "S17_baseline_lstm",
        "policy_class": "cortex_policy.CortexPolicy",
        "overrides": {},  # no overrides = pure cogames train defaults
        "note": "Control: native LSTM via cogames train defaults",
    },
    # H1: Higher entropy for Cortex Ag,A,S sequential
    {
        "name": "S18_agas_seq_ent08",
        "policy_class": "cortex_policy.CortexAgasSeqPolicy",
        "overrides": {"ent_coef": 0.08},
        "note": "Fix entropy collapse: ent_coef 0.05 -> 0.08",
    },
    # H2: Higher entropy + weight decay
    {
        "name": "S19_agas_seq_ent08_wd",
        "policy_class": "cortex_policy.CortexAgasSeqPolicy",
        "overrides": {"ent_coef": 0.08, "weight_decay": 1e-4},
        "note": "Entropy fix + L2 regularization (plasticity preservation)",
    },
    # H3: Much higher entropy (push through double descent)
    {
        "name": "S20_agas_seq_ent12",
        "policy_class": "cortex_policy.CortexAgasSeqPolicy",
        "overrides": {"ent_coef": 0.12},
        "note": "Aggressive entropy: prevent premature convergence entirely",
    },
    # H4: LSTM with higher entropy (does LSTM also benefit?)
    {
        "name": "S21_lstm_ent08",
        "policy_class": "cortex_policy.CortexPolicy",
        "overrides": {"ent_coef": 0.08},
        "note": "Does LSTM also benefit from higher entropy? Baseline comparison.",
    },
    # H5: Sequential Ag,A,S with update_epochs=3 (more gradient steps per batch)
    {
        "name": "S22_agas_seq_u3_ent08",
        "policy_class": "cortex_policy.CortexAgasSeqPolicy",
        "overrides": {"ent_coef": 0.08, "update_epochs": 3},
        "note": "More gradient steps per batch + entropy fix",
    },
]

# ---------------------------------------------------------------------------
# Monkey-patch mechanism
# ---------------------------------------------------------------------------

PATCH_SCRIPT_TEMPLATE = '''
import pufferlib.pufferl as pufferl
import json, os

_overrides = json.loads(os.environ.get("SWEEP_OVERRIDES", "{{}}"))

if _overrides:
    _orig_init = pufferl.PuffeRL.__init__

    def _patched_init(self, train_args, *args, **kwargs):
        for k, v in _overrides.items():
            old = train_args.get(k, "MISSING")
            train_args[k] = v
            print(f"[SWEEP] {{k}}: {{old}} -> {{v}}")
        _orig_init(self, train_args, *args, **kwargs)

    pufferl.PuffeRL.__init__ = _patched_init
    print(f"[SWEEP] Patched PuffeRL with overrides: {{_overrides}}")
'''


def write_patch_file(patch_path: Path):
    """Write the monkey-patch to a .pth file in site-packages."""
    patch_path.write_text(PATCH_SCRIPT_TEMPLATE.strip())


def get_sitecustomize_path() -> Path:
    """Get a path where we can drop a .pth file that auto-loads."""
    # Use PYTHONPATH + a conftest-style approach instead:
    # Write a small module that gets imported via sitecustomize
    return Path("/tmp/sweep_patch.py")


def run_experiment(config: dict, base_args: list[str], results_dir: Path):
    """Run a single sweep experiment."""
    name = config["name"]
    policy_class = config["policy_class"]
    overrides = config["overrides"]
    note = config.get("note", "")

    print(f"\n{'='*70}")
    print(f"EXPERIMENT: {name}")
    print(f"Policy: {policy_class}")
    print(f"Overrides: {json.dumps(overrides)}")
    print(f"Note: {note}")
    print(f"{'='*70}\n")

    # Write the patch module
    patch_path = get_sitecustomize_path()
    write_patch_file(patch_path)

    # Set env vars
    env = os.environ.copy()
    env["SWEEP_OVERRIDES"] = json.dumps(overrides)
    # Force import of our patch before cogames runs
    env["PYTHONSTARTUP"] = str(patch_path)

    # Build command — use -c to run Python that imports patch then cogames
    log_file = results_dir / f"{name}.log"
    cmd = [
        sys.executable, "-c",
        f"exec(open('{patch_path}').read()); "
        f"from cogames.main import app; app()"
    ] + base_args + [
        "-p", f"class={policy_class}",
        "--checkpoints", str(results_dir / name),
    ]

    print(f"Command: {' '.join(cmd)}")
    print(f"Log: {log_file}")

    start = time.time()
    with open(log_file, "w") as lf:
        proc = subprocess.run(
            cmd, env=env, stdout=lf, stderr=subprocess.STDOUT,
            cwd=str(results_dir.parent),
        )
    elapsed = time.time() - start

    # Extract results from log
    result = extract_results(log_file)
    result["name"] = name
    result["policy_class"] = policy_class
    result["overrides"] = overrides
    result["note"] = note
    result["elapsed_min"] = round(elapsed / 60, 1)
    result["exit_code"] = proc.returncode

    # Save result
    result_file = results_dir / f"{name}_result.json"
    with open(result_file, "w") as f:
        json.dump(result, f, indent=2)

    # Trim checkpoints (keep only final)
    trim_checkpoints(results_dir / name)

    return result


def extract_results(log_path: Path) -> dict:
    """Extract key metrics from training log."""
    try:
        text = log_path.read_text()
    except Exception:
        return {"peak_junctions": 0, "error": "log read failed"}

    # Extract junction values
    junctions = [float(m) for m in re.findall(
        r"game/cogs/aligned\.jun.*?\s+([\d.]+)", text
    )]
    peak_j = max(junctions) if junctions else 0.0

    # Extract final entropy, clipfrac
    entropies = re.findall(r"entropy\s+([\d.]+)", text)
    clipfracs = re.findall(r"clipfrac\s+([\d.]+)", text)

    # Extract params count
    params_m = re.search(r"Params\s+([\d.]+[KMB]?)", text)

    return {
        "peak_junctions": peak_j,
        "final_entropy": float(entropies[-1]) if entropies else 0,
        "final_clipfrac": float(clipfracs[-1]) if clipfracs else 0,
        "params": params_m.group(1) if params_m else "?",
        "num_junction_readings": len(junctions),
    }


def trim_checkpoints(checkpoint_dir: Path):
    """Keep only the final checkpoint to save disk space."""
    if not checkpoint_dir.exists():
        return
    # Find all subdirs (the run ID dir)
    for run_dir in checkpoint_dir.iterdir():
        if not run_dir.is_dir():
            continue
        models = sorted(run_dir.glob("model_*.pt"))
        if len(models) > 1:
            for m in models[:-1]:  # keep only last
                m.unlink()
                print(f"  Trimmed: {m.name}")
        # Remove trainer_state to save space
        ts = run_dir / "trainer_state.pt"
        if ts.exists():
            ts.unlink()
            print(f"  Trimmed: trainer_state.pt")


def print_summary(results: list[dict]):
    """Print summary table of all results."""
    print(f"\n{'='*80}")
    print("SWEEP SUMMARY")
    print(f"{'='*80}")
    print(f"{'Name':30s} {'Peak J':>8} {'Entropy':>8} {'Clip':>8} "
          f"{'Time':>8} {'Overrides'}")
    print("-" * 80)
    for r in results:
        overrides_str = json.dumps(r.get("overrides", {}))
        if len(overrides_str) > 30:
            overrides_str = overrides_str[:27] + "..."
        print(f"{r['name']:30s} {r.get('peak_junctions', 0):>8.3f} "
              f"{r.get('final_entropy', 0):>8.3f} "
              f"{r.get('final_clipfrac', 0):>8.3f} "
              f"{r.get('elapsed_min', 0):>6.1f}m "
              f"{overrides_str}")

    # Best result
    best = max(results, key=lambda r: r.get("peak_junctions", 0))
    print(f"\nBest: {best['name']} with {best.get('peak_junctions', 0):.3f} junctions")


def main():
    parser = argparse.ArgumentParser(description="Cortex hyperparameter sweep")
    parser.add_argument("--config", type=int, help="Run only this config index")
    parser.add_argument("--dry-run", action="store_true", help="Print configs only")
    parser.add_argument("--steps", type=int, default=50_000_000, help="Training steps")
    parser.add_argument("--mission", default="cogsguard_arena.basic")
    parser.add_argument("--cogs", type=int, default=8)
    parser.add_argument("--results-dir", default="./sweep_results")
    args = parser.parse_args()

    configs = SWEEP_CONFIGS
    if args.config is not None:
        configs = [SWEEP_CONFIGS[args.config]]

    if args.dry_run:
        for i, c in enumerate(SWEEP_CONFIGS):
            print(f"[{i}] {c['name']}: {json.dumps(c['overrides'])} — {c['note']}")
        return

    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    base_args = [
        "train",
        "-m", args.mission,
        "--cogs", str(args.cogs),
        "--steps", str(args.steps),
        "--device", "auto",
    ]

    results = []
    for i, config in enumerate(configs):
        print(f"\n[{i+1}/{len(configs)}] Starting {config['name']}...")
        result = run_experiment(config, base_args, results_dir)
        results.append(result)
        print(f"  -> Peak junctions: {result.get('peak_junctions', 0):.3f}")

    print_summary(results)

    # Save all results
    summary_file = results_dir / "sweep_summary.json"
    with open(summary_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {summary_file}")


if __name__ == "__main__":
    main()
