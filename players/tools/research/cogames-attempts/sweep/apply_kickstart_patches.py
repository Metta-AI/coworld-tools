#!/usr/bin/env python3
"""Source-patch pufferl.py with kickstart CE loss injection.

Run once on AWS before kickstart training:
    python3 scripts/sweep/apply_kickstart_patches.py

Patches:
    1. Kickstart CE loss: if self._ks_teacher_actions exists, add
       cross_entropy(logits, teacher_actions) to the PPO loss BEFORE backward().
       Coefficient is self._ks_effective_coef (set by patch_and_train.py evaluate wrapper).

All patches are backward-compatible (no-op when _ks_teacher_actions is absent).
Idempotent: safe to run multiple times.
Requires: apply_tier1_patches.py to have been run first (for PFO loss line).
"""

import os
import shutil

PUFFERL_PATH = os.path.expanduser(
    "~/projects/cogames-env/lib64/python3.12/site-packages/pufferlib/pufferl.py"
)

with open(PUFFERL_PATH) as f:
    source = f.read()

# Backup (use .orig2 to avoid overwriting tier1 backup)
backup_path = PUFFERL_PATH + ".pre_ks"
if not os.path.exists(backup_path):
    shutil.copy2(PUFFERL_PATH, backup_path)
    print(f"[KS_PATCH] Backed up to {backup_path}")
else:
    print(f"[KS_PATCH] Backup already exists at {backup_path}")

modified = False

# --- 1. Kickstart CE loss in train() ---
# Inject AFTER the loss computation line, BEFORE self.amp_context.__enter__()
# The loss line may have PFO addition from tier1 patches.
# We anchor on the amp_context line that follows it.

ANCHOR = '            self.amp_context.__enter__()  # TODO: Debug'

KS_INJECTION = '''            # Kickstart: CE loss against pre-computed teacher actions
            _ks_ta = getattr(self, '_ks_teacher_actions', None)
            _ks_c = getattr(self, '_ks_effective_coef', 0.0)
            if _ks_ta is not None and _ks_c > 0:
                _ks_logits = logits.reshape(-1, logits.shape[-1]) if logits.dim() > 2 else logits
                _ks_targets = _ks_ta[idx].reshape(-1).long().to(_ks_logits.device)
                _ks_n = min(_ks_logits.shape[0], _ks_targets.shape[0])
                _ks_ce = torch.nn.functional.cross_entropy(_ks_logits[:_ks_n], _ks_targets[:_ks_n])
                loss = loss + _ks_c * _ks_ce
                losses["ks_loss"] = losses.get("ks_loss", 0) + _ks_ce.item() / self.total_minibatches
'''

if '_ks_teacher_actions' in source:
    print("[KS_PATCH] Skip: kickstart CE loss already applied")
else:
    if ANCHOR in source:
        source = source.replace(ANCHOR, KS_INJECTION + ANCHOR, 1)
        print("[KS_PATCH] Applied: kickstart CE loss injection in train()")
        modified = True
    else:
        print("[KS_PATCH] WARNING: Could not find anchor line for kickstart injection")
        print("[KS_PATCH]   Expected: self.amp_context.__enter__()  # TODO: Debug")

# --- 2. Teacher-led action replacement in evaluate() ---
# Inject AFTER action sampling, BEFORE reward clamping.
# Anchor: the action sampling line + reward clamp line.

EVAL_ANCHOR = '                action, logprob, _ = pufferlib.pytorch.sample_logits(logits)\n                r = torch.clamp(r, -1, 1)'

TEACHER_LED_INJECTION = '''                action, logprob, _ = pufferlib.pytorch.sample_logits(logits)
                # Teacher-led: replace fraction of actions with teacher actions
                _tl_fn = getattr(self, '_ks_teacher_fn', None)
                _tl_frac = getattr(self, '_ks_teacher_led_frac', 0.0)
                if _tl_fn is not None and _tl_frac > 0:
                    import numpy as _tl_np
                    _tl_mask = torch.rand(action.shape[0], device=action.device) < _tl_frac
                    if _tl_mask.any():
                        _tl_obs = o.numpy() if isinstance(o, torch.Tensor) else o
                        for _tl_i in range(_tl_mask.shape[0]):
                            if _tl_mask[_tl_i]:
                                _tl_flat = _tl_obs[_tl_i].flatten()
                                _tl_ntok = len(_tl_flat) // 3
                                if _tl_ntok > 0:
                                    _tl_tok = _tl_flat[:_tl_ntok * 3].reshape(-1, 3).astype(_tl_np.int32)
                                    action[_tl_i] = _tl_fn(_tl_tok, _tl_i % 8, self.global_step)
                        # Recompute logprobs for ALL actions (replaced and not)
                        _tl_dist = torch.distributions.Categorical(logits=logits)
                        logprob = _tl_dist.log_prob(action)
                r = torch.clamp(r, -1, 1)'''

if '_ks_teacher_fn' in source:
    print("[KS_PATCH] Skip: teacher-led already applied")
else:
    if EVAL_ANCHOR in source:
        source = source.replace(EVAL_ANCHOR, TEACHER_LED_INJECTION, 1)
        print("[KS_PATCH] Applied: teacher-led action replacement in evaluate()")
        modified = True
    else:
        print("[KS_PATCH] WARNING: Could not find eval anchor for teacher-led injection")
        print("[KS_PATCH]   Expected: action sampling + reward clamp on consecutive lines")

# --- Write patched file ---
if modified:
    with open(PUFFERL_PATH, "w") as f:
        f.write(source)
    print(f"[KS_PATCH] Wrote patched pufferl.py ({len(source)} bytes)")
else:
    print("[KS_PATCH] No modifications needed")
