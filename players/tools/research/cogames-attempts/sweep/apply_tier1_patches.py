#!/usr/bin/env python3
"""Source-patch pufferl.py with Tier 1 PPO fixes.

Run once on AWS before training:
    python3 scripts/sweep/apply_tier1_patches.py

Patches:
    1. Asymmetric clipping: config["clip_high"] for upper bound (default: same as clip_coef)
    2. PFO loss: Pre-activation L2 regularization via config["pfo_coef"] (default: 0.0)
    3. Optional value clip removal via config["no_vf_clip"]

All patches are backward-compatible (no-op when extra config keys are absent).
Idempotent: safe to run multiple times.
"""

import os
import shutil

PUFFERL_PATH = os.path.expanduser(
    "~/projects/cogames-env/lib64/python3.12/site-packages/pufferlib/pufferl.py"
)

with open(PUFFERL_PATH) as f:
    source = f.read()

# Backup original (only if no backup exists yet)
backup_path = PUFFERL_PATH + ".orig"
if not os.path.exists(backup_path):
    shutil.copy2(PUFFERL_PATH, backup_path)
    print(f"[TIER1] Backed up original to {backup_path}")
else:
    print(f"[TIER1] Backup already exists at {backup_path}")

modified = False

# --- 1. Asymmetric clipping ---
OLD_CLIP = "pg_loss2 = -adv * torch.clamp(ratio, 1 - clip_coef, 1 + clip_coef)"
NEW_CLIP = "pg_loss2 = -adv * torch.clamp(ratio, 1 - clip_coef, 1 + config.get('clip_high', clip_coef))"

if OLD_CLIP in source:
    source = source.replace(OLD_CLIP, NEW_CLIP)
    print("[TIER1] Applied: asymmetric clipping (config['clip_high'])")
    modified = True
elif "clip_high" in source:
    print("[TIER1] Skip: asymmetric clipping already applied")
else:
    print("[TIER1] WARNING: Could not find clipping line")

# --- 2. PFO pre-activation L2 regularization ---
OLD_LOSS = 'loss = pg_loss + config["vf_coef"] * v_loss - config["ent_coef"] * entropy_loss'
NEW_LOSS = (
    '# PFO: pre-activation L2 reg (Moalla et al. NeurIPS 2024)\n'
    '            _pfo_c = config.get("pfo_coef", 0.0)\n'
    '            _pfo_l = _pfo_c * (self._pfo_pre_act ** 2).mean() if _pfo_c > 0 and getattr(self, "_pfo_pre_act", None) is not None else 0.0\n'
    '            loss = pg_loss + config["vf_coef"] * v_loss - config["ent_coef"] * entropy_loss + _pfo_l'
)

if OLD_LOSS in source and "_pfo_c" not in source:
    source = source.replace(OLD_LOSS, NEW_LOSS)
    print("[TIER1] Applied: PFO loss (config['pfo_coef'])")
    modified = True
elif "_pfo_c" in source:
    print("[TIER1] Skip: PFO loss already applied")
else:
    print("[TIER1] WARNING: Could not find loss line")

# --- 3. Optional value clipping removal ---
OLD_VF_CLIP = "v_loss_clipped = (v_clipped - mb_returns) ** 2"
NEW_VF_CLIP = (
    "v_loss_clipped = (v_clipped - mb_returns) ** 2\n"
    "            if config.get('no_vf_clip', False):\n"
    "                v_loss_clipped = v_loss_unclipped  # bypass value clipping"
)

if OLD_VF_CLIP in source and "no_vf_clip" not in source:
    source = source.replace(OLD_VF_CLIP, NEW_VF_CLIP)
    print("[TIER1] Applied: optional value clip removal (config['no_vf_clip'])")
    modified = True
elif "no_vf_clip" in source:
    print("[TIER1] Skip: value clip removal already applied")

if modified:
    with open(PUFFERL_PATH, "w") as f:
        f.write(source)
    print(f"[TIER1] Wrote patched pufferl.py ({len(source)} bytes)")
else:
    print("[TIER1] No changes needed")

# Verify
with open(PUFFERL_PATH) as f:
    verify = f.read()
    checks = [
        ("clip_high", "asymmetric clipping"),
        ("_pfo_c", "PFO loss"),
        ("no_vf_clip", "value clip removal"),
    ]
    for marker, name in checks:
        status = "OK" if marker in verify else "MISSING"
        print(f"  [{status}] {name}")
