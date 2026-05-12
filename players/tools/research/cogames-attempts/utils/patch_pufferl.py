#!/usr/bin/env python3
"""Patch pufferl.py to add kickstarting cross-entropy loss support."""

import sys

PUFFERL_PATH = "/home/ec2-user/projects/cogames-env/lib64/python3.12/site-packages/pufferlib/pufferl.py"

with open(PUFFERL_PATH, "r") as f:
    content = f.read()

# Patch 1: Add teacher_actions = None in __init__ after free_idx
old_init = "        self.free_idx = total_agents\n"
new_init = "        self.free_idx = total_agents\n        self.teacher_actions = None  # Filled externally for kickstarting\n"

if "self.teacher_actions" in content:
    print("Patch 1 already applied, skipping")
else:
    assert old_init in content, f"Could not find init insertion point"
    content = content.replace(old_init, new_init, 1)
    print("Patch 1 applied: teacher_actions = None in __init__")

# Patch 2: Add CE loss after loss = pg_loss + ... line
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
    print("Patch 2 already applied, skipping")
else:
    assert old_loss in content, f"Could not find loss insertion point"
    content = content.replace(old_loss, new_loss, 1)
    print("Patch 2 applied: CE loss in train()")

with open(PUFFERL_PATH, "w") as f:
    f.write(content)

print("Done! Verifying...")

# Verify
with open(PUFFERL_PATH, "r") as f:
    lines = f.readlines()

for i, line in enumerate(lines, 1):
    if "teacher_actions" in line:
        print(f"  Line {i}: {line.rstrip()}")
    if "ks_loss" in line:
        print(f"  Line {i}: {line.rstrip()}")
