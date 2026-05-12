#!/usr/bin/env python3
"""Patch pufferl.py to:
1. Zero LSTM state on episode boundaries (critical for Cortex)
2. Add kickstarting cross-entropy loss support (from v1 patch)

PufferLib 3.0.17 never resets LSTM state when episodes end within an
evaluate() call. Standard LSTM tolerates this (forget gate), but Cortex's
AGaLiTe tick counter and sLSTM commitment state become severely corrupted.
"""

import sys

PUFFERL_PATH = "/home/ec2-user/projects/cogames-env/lib64/python3.12/site-packages/pufferlib/pufferl.py"

with open(PUFFERL_PATH, "r") as f:
    content = f.read()

# ──────────────────────────────────────────────────────────────
# Patch 1: Zero LSTM state on episode done (CRITICAL)
# After state is stored back, check if episode ended and zero.
# ──────────────────────────────────────────────────────────────

old_state_store = """\
                if config["use_rnn"]:
                    self.lstm_h[env_id.start] = state["lstm_h"]
                    self.lstm_c[env_id.start] = state["lstm_c"]"""

new_state_store = """\
                if config["use_rnn"]:
                    self.lstm_h[env_id.start] = state["lstm_h"]
                    self.lstm_c[env_id.start] = state["lstm_c"]

                    # PATCH: zero LSTM state for agents whose episodes ended
                    _d_bool = d.bool() if d.dim() > 0 else d.unsqueeze(0).bool()
                    if _d_bool.any():
                        self.lstm_h[env_id.start][_d_bool] = 0
                        self.lstm_c[env_id.start][_d_bool] = 0"""

if "# PATCH: zero LSTM state" in content:
    print("Patch 1 (episode reset) already applied, skipping")
else:
    assert old_state_store in content, "Could not find LSTM state store pattern"
    content = content.replace(old_state_store, new_state_store, 1)
    print("Patch 1 applied: zero LSTM state on episode done")

# ──────────────────────────────────────────────────────────────
# Patch 2: teacher_actions attribute in __init__
# ──────────────────────────────────────────────────────────────

old_init = "        self.free_idx = total_agents\n"
new_init = "        self.free_idx = total_agents\n        self.teacher_actions = None  # Filled externally for kickstarting\n"

if "self.teacher_actions" in content:
    print("Patch 2 (teacher_actions) already applied, skipping")
else:
    assert old_init in content, "Could not find init insertion point"
    content = content.replace(old_init, new_init, 1)
    print("Patch 2 applied: teacher_actions = None in __init__")

# ──────────────────────────────────────────────────────────────
# Patch 3: CE kickstarting loss in train()
# ──────────────────────────────────────────────────────────────

old_loss = '            loss = pg_loss + config["vf_coef"] * v_loss - config["ent_coef"] * entropy_loss\n            self.amp_context.__enter__()  # TODO: Debug'

new_loss = '''            loss = pg_loss + config["vf_coef"] * v_loss - config["ent_coef"] * entropy_loss

            # Kickstarting cross-entropy loss
            if self.teacher_actions is not None:
                _ks_coef = config.get("ks_coef", 0.0)
                if _ks_coef > 0:
                    _progress = self.global_step / config["total_timesteps"]
                    _anneal_frac = config.get("ks_anneal_frac", 0.5)
                    _effective_ks = _ks_coef * max(0, 1.0 - _progress / _anneal_frac)
                    if _effective_ks > 0:
                        _mb_teacher = self.teacher_actions[idx].reshape(-1).long()
                        _ks_loss = torch.nn.functional.cross_entropy(
                            logits.reshape(-1, logits.shape[-1]), _mb_teacher
                        )
                        loss = loss + _effective_ks * _ks_loss
                        losses["ks_loss"] += _ks_loss.item() / self.total_minibatches

            self.amp_context.__enter__()  # TODO: Debug'''

if "Kickstarting cross-entropy" in content:
    print("Patch 3 (kickstarting loss) already applied, skipping")
else:
    assert old_loss in content, "Could not find loss insertion point"
    content = content.replace(old_loss, new_loss, 1)
    print("Patch 3 applied: CE kickstarting loss in train()")

# ──────────────────────────────────────────────────────────────
# Write patched file
# ──────────────────────────────────────────────────────────────

with open(PUFFERL_PATH, "w") as f:
    f.write(content)

print(f"\nDone! Patched {PUFFERL_PATH}")

# Verify
with open(PUFFERL_PATH, "r") as f:
    lines = f.readlines()

print("\nVerification:")
for i, line in enumerate(lines, 1):
    if "PATCH: zero LSTM" in line or "teacher_actions" in line or "ks_loss" in line:
        print(f"  Line {i}: {line.rstrip()}")
