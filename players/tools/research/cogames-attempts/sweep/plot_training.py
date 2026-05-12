#!/usr/bin/env python3
"""Parse cogames training logs and generate multi-panel training graphs.

Usage:
    python3 plot_training.py results_v22/Q1_metta_optimal.log
    python3 plot_training.py results_v22/*.log          # batch mode
    python3 plot_training.py results_v22/Q1.log Q2.log  # overlay multiple runs
"""

import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def parse_log(path: str) -> dict:
    """Parse a cogames training log file into metric time series."""
    metrics = {
        "step": [],
        "junctions": [],
        "hearts": [],
        "aligner_gained": [],
        "entropy": [],
        "clipfrac": [],
        "explained_var": [],
        "pg_loss": [],
        "vf_loss": [],
        "total_loss": [],
        "reward": [],
        "sps": [],
    }

    # Patterns for metrics in cogames logs
    # Format varies but typically: key=value or key: value
    patterns = {
        "step": [
            re.compile(r"global_step[=:\s]+(\d+)"),
            re.compile(r"total_steps[=:\s]+(\d+)"),
        ],
        "junctions": [
            re.compile(r"aligned\.jun\w*[=:\s]+([0-9.]+)"),
            re.compile(r"junctions[=:\s]+([0-9.]+)"),
        ],
        "hearts": [
            re.compile(r"heart\.gained[=:\s]+([0-9.]+)"),
            re.compile(r"hearts[=:\s]+([0-9.]+)"),
        ],
        "aligner_gained": [
            re.compile(r"aligner\.gained[=:\s]+([0-9.]+)"),
            re.compile(r"aligner_gained[=:\s]+([0-9.]+)"),
        ],
        "entropy": [
            re.compile(r"entropy[=:\s]+([0-9.]+)"),
        ],
        "clipfrac": [
            re.compile(r"clipfrac[=:\s]+([0-9.]+)"),
        ],
        "explained_var": [
            re.compile(r"explained_var\w*[=:\s]+([0-9.-]+)"),
            re.compile(r"expl_var[=:\s]+([0-9.-]+)"),
        ],
        "pg_loss": [
            re.compile(r"pg_loss[=:\s]+([0-9.e+-]+)"),
            re.compile(r"policy_loss[=:\s]+([0-9.e+-]+)"),
        ],
        "vf_loss": [
            re.compile(r"vf_loss[=:\s]+([0-9.e+-]+)"),
            re.compile(r"value_loss[=:\s]+([0-9.e+-]+)"),
        ],
        "total_loss": [
            re.compile(r"(?:total_)?loss[=:\s]+([0-9.e+-]+)"),
        ],
        "reward": [
            re.compile(r"reward[=:\s]+([0-9.e+-]+)"),
        ],
        "sps": [
            re.compile(r"sps[=:\s]+([0-9.]+)"),
            re.compile(r"steps_per_sec[=:\s]+([0-9.]+)"),
        ],
    }

    with open(path) as f:
        # Track current step for associating metrics
        current_step = 0
        line_idx = 0

        for line in f:
            line_idx += 1
            found_in_line = {}

            for metric_name, pats in patterns.items():
                for pat in pats:
                    m = pat.search(line)
                    if m:
                        try:
                            found_in_line[metric_name] = float(m.group(1))
                        except ValueError:
                            pass
                        break

            if "step" in found_in_line:
                current_step = found_in_line["step"]

            # Only record if we found at least one training metric (not just step)
            training_metrics = {k for k in found_in_line if k != "step"}
            if training_metrics:
                for key in metrics:
                    if key == "step":
                        metrics["step"].append(current_step)
                    elif key in found_in_line:
                        metrics[key].append(found_in_line[key])
                    else:
                        metrics[key].append(np.nan)

    # Convert to numpy arrays
    return {k: np.array(v, dtype=float) for k, v in metrics.items()}


def plot_single(log_path: str, save_path: str = None):
    """Generate a multi-panel figure for a single training run."""
    data = parse_log(log_path)

    if len(data["step"]) == 0:
        print(f"WARNING: No data parsed from {log_path}")
        return

    steps = data["step"] / 1e6  # Convert to millions
    name = Path(log_path).stem

    fig, axes = plt.subplots(3, 2, figsize=(14, 12))
    fig.suptitle(f"Training: {name}", fontsize=14, fontweight="bold")

    # Panel 1: Junctions + Hearts
    ax = axes[0, 0]
    if not np.all(np.isnan(data["junctions"])):
        ax.plot(steps, data["junctions"], "b-", alpha=0.7, label="Junctions")
    if not np.all(np.isnan(data["hearts"])):
        ax2 = ax.twinx()
        ax2.plot(steps, data["hearts"], "r-", alpha=0.5, label="Hearts")
        ax2.set_ylabel("Hearts", color="r")
    ax.set_ylabel("Junctions", color="b")
    ax.set_title("Junctions & Hearts")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Panel 2: Aligner Gained (CRITICAL diagnostic)
    ax = axes[0, 1]
    if not np.all(np.isnan(data["aligner_gained"])):
        ax.plot(steps, data["aligner_gained"], "g-", alpha=0.7)
        ax.fill_between(steps, 0, data["aligner_gained"], alpha=0.2, color="g")
    ax.set_title("Aligner Gained (gear acquisition)")
    ax.set_ylabel("Aligner Gained")
    ax.axhline(y=0, color="r", linestyle="--", alpha=0.5, label="Zero line")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Panel 3: Entropy + Clipfrac
    ax = axes[1, 0]
    if not np.all(np.isnan(data["entropy"])):
        ax.plot(steps, data["entropy"], "m-", alpha=0.7, label="Entropy")
    ax.set_ylabel("Entropy", color="m")
    ax.axhline(y=1.0, color="m", linestyle=":", alpha=0.3)
    ax.axhline(y=1.6, color="m", linestyle=":", alpha=0.3)
    if not np.all(np.isnan(data["clipfrac"])):
        ax2 = ax.twinx()
        ax2.plot(steps, data["clipfrac"], "c-", alpha=0.5, label="Clipfrac")
        ax2.set_ylabel("Clipfrac", color="c")
        ax2.axhline(y=0.01, color="c", linestyle=":", alpha=0.3, label="Collapse threshold")
    ax.set_title("Entropy & Clipfrac")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Panel 4: Explained Variance
    ax = axes[1, 1]
    if not np.all(np.isnan(data["explained_var"])):
        ax.plot(steps, data["explained_var"], "k-", alpha=0.7)
        ax.fill_between(steps, 0, np.clip(data["explained_var"], 0, 1), alpha=0.15)
    ax.set_title("Explained Variance")
    ax.set_ylabel("Explained Var")
    ax.set_ylim(-0.5, 1.1)
    ax.axhline(y=0, color="r", linestyle="--", alpha=0.3)
    ax.axhline(y=1, color="g", linestyle="--", alpha=0.3)
    ax.grid(True, alpha=0.3)

    # Panel 5: Losses
    ax = axes[2, 0]
    if not np.all(np.isnan(data["pg_loss"])):
        ax.plot(steps, data["pg_loss"], "b-", alpha=0.6, label="PG Loss")
    if not np.all(np.isnan(data["vf_loss"])):
        ax.plot(steps, data["vf_loss"], "r-", alpha=0.6, label="VF Loss")
    ax.set_title("Loss Components")
    ax.set_ylabel("Loss")
    ax.set_xlabel("Steps (M)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Panel 6: Reward + SPS
    ax = axes[2, 1]
    if not np.all(np.isnan(data["reward"])):
        ax.plot(steps, data["reward"], "g-", alpha=0.7, label="Reward")
    ax.set_ylabel("Reward", color="g")
    if not np.all(np.isnan(data["sps"])):
        ax2 = ax.twinx()
        ax2.plot(steps, data["sps"], "orange", alpha=0.4, label="SPS")
        ax2.set_ylabel("SPS", color="orange")
    ax.set_title("Reward & Throughput")
    ax.set_xlabel("Steps (M)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path is None:
        save_path = str(Path(log_path).with_suffix(".png"))

    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {save_path}")

    # Print summary stats
    j = data["junctions"]
    valid_j = j[~np.isnan(j)]
    if len(valid_j) > 0:
        print(f"  Junctions: peak={valid_j.max():.2f}, mean={valid_j.mean():.2f}, "
              f"last={valid_j[-1]:.2f}")
    ent = data["entropy"]
    valid_ent = ent[~np.isnan(ent)]
    if len(valid_ent) > 0:
        print(f"  Entropy: last={valid_ent[-1]:.3f}")
    cf = data["clipfrac"]
    valid_cf = cf[~np.isnan(cf)]
    if len(valid_cf) > 0:
        print(f"  Clipfrac: last={valid_cf[-1]:.4f}")
    ag = data["aligner_gained"]
    valid_ag = ag[~np.isnan(ag)]
    if len(valid_ag) > 0:
        print(f"  Aligner gained: max={valid_ag.max():.3f}, "
              f"ever_nonzero={'YES' if valid_ag.max() > 0 else 'NO'}")


def plot_overlay(log_paths: list, save_path: str = None):
    """Overlay multiple training runs on the same figure."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"Training Comparison ({len(log_paths)} runs)", fontsize=14, fontweight="bold")

    colors = plt.cm.tab10(np.linspace(0, 1, len(log_paths)))

    for idx, log_path in enumerate(log_paths):
        data = parse_log(log_path)
        if len(data["step"]) == 0:
            continue
        steps = data["step"] / 1e6
        name = Path(log_path).stem
        c = colors[idx]

        # Junctions
        if not np.all(np.isnan(data["junctions"])):
            axes[0, 0].plot(steps, data["junctions"], color=c, alpha=0.7, label=name)

        # Entropy
        if not np.all(np.isnan(data["entropy"])):
            axes[0, 1].plot(steps, data["entropy"], color=c, alpha=0.7, label=name)

        # Clipfrac
        if not np.all(np.isnan(data["clipfrac"])):
            axes[1, 0].plot(steps, data["clipfrac"], color=c, alpha=0.7, label=name)

        # Reward
        if not np.all(np.isnan(data["reward"])):
            axes[1, 1].plot(steps, data["reward"], color=c, alpha=0.7, label=name)

    axes[0, 0].set_title("Junctions")
    axes[0, 0].set_ylabel("Junctions")
    axes[0, 0].legend(fontsize=8)
    axes[0, 0].grid(True, alpha=0.3)

    axes[0, 1].set_title("Entropy")
    axes[0, 1].set_ylabel("Entropy")
    axes[0, 1].axhline(y=1.0, color="gray", linestyle=":", alpha=0.3)
    axes[0, 1].axhline(y=1.6, color="gray", linestyle=":", alpha=0.3)
    axes[0, 1].grid(True, alpha=0.3)

    axes[1, 0].set_title("Clipfrac")
    axes[1, 0].set_ylabel("Clipfrac")
    axes[1, 0].set_xlabel("Steps (M)")
    axes[1, 0].axhline(y=0.01, color="red", linestyle=":", alpha=0.3, label="Collapse")
    axes[1, 0].grid(True, alpha=0.3)

    axes[1, 1].set_title("Reward")
    axes[1, 1].set_ylabel("Reward")
    axes[1, 1].set_xlabel("Steps (M)")
    axes[1, 1].grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path is None:
        save_path = "comparison.png"
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved comparison: {save_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 plot_training.py <log_file> [log_file2 ...]")
        sys.exit(1)

    log_files = sys.argv[1:]

    if len(log_files) == 1:
        plot_single(log_files[0])
    else:
        # Generate individual plots AND comparison overlay
        for f in log_files:
            plot_single(f)
        plot_overlay(log_files)
