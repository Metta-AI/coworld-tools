#!/usr/bin/env python3
"""Monkey-patch cogames train hyperparams and training loop, then run cogames CLI.

Intercepts PuffeRL.__init__ to override train_args before training starts.
Optionally patches the training loop with plasticity/optimization fixes.

Usage:
    # Override entropy coefficient
    SWEEP_OVERRIDES='{"ent_coef": 0.08}' python3 patch_and_train.py train -m mission -p policy ...

    # Use metta-tuned hyperparameter preset
    SWEEP_PRESET=metta_optimal python3 patch_and_train.py train ...

    # Preset + additional overrides (overrides win)
    SWEEP_PRESET=metta_optimal SWEEP_OVERRIDES='{"ent_coef": 0.05}' python3 patch_and_train.py ...

    # Enable fixes (comma-separated)
    SWEEP_FIXES='pfo,sep_lr,redo,asym_clip' python3 patch_and_train.py train ...

    # Kickstarting from scripted teacher
    KICKSTART_MODE=kl KS_COEF=0.6 python3 patch_and_train.py train ...

Available override keys (from PufferLib train_args):
    ent_coef, learning_rate, gamma, gae_lambda, update_epochs,
    clip_coef, vf_coef, vf_clip_coef, max_grad_norm, weight_decay,
    anneal_lr, bptt_horizon, adam_beta1, adam_beta2, min_lr_ratio

Available presets (SWEEP_PRESET):
    metta_optimal   - Metta's sweep-tuned values from recipes/experiment/cogsguard.py
                      lr=0.00738, gamma=0.9986, gae=0.9354, clip=0.367, ent=0.0257,
                      vf=1.465, weight_decay=0.3, bptt=256, update_epochs=1

Available fixes:
    pfo             - Pre-activation Feature Optimization (Moalla et al., NeurIPS 2024)
                      Requires: run apply_tier1_patches.py first to patch pufferl.py
                      Env: PFO_COEF (default: 1.0)
    sep_lr          - Separate actor/critic learning rates (critic 5x lower)
    asym_clip       - Asymmetric clipping, clip_high = 1.5x clip_coef (DAPO, ByteDance 2025)
                      Requires: run apply_tier1_patches.py first to patch pufferl.py
    redo            - ReDo dormant neuron recycling (Sokar et al., ICML 2023)
                      Env: REDO_INTERVAL (default: 100), REDO_TAU (default: 0.1)
    adam_rel        - Reset Adam optimizer timestep each epoch (Ellis et al., NeurIPS 2024)
    shrink_perturb  - Soft Shrink+Perturb: regularize weights toward init (Lyle et al., NeurIPS 2024)
    no_vf_clip      - Remove value function clipping
                      Requires: run apply_tier1_patches.py first to patch pufferl.py
    target_net      - Target network for value stabilization (Subhojeet suggestion)
                      Polyak-averaged critic copy used for GAE value targets.
                      Env: TARGET_NET_TAU (default: 0.005)
    adamw_sf        - Replace Adam with AdamW ScheduleFree (metta's optimizer)
                      Env: ADAMW_MOMENTUM (default: 0.98)

Kickstarting (KICKSTART_MODE):
    none            - No kickstarting (default)
    kl              - KL divergence loss: L_ks = coef * CE(student_logits/T, teacher_action)
    eer             - EER: KL loss + reward shaping r' = r + lambda * log(pi(a_teacher|s))
    Env vars:
        KS_COEF             - Kickstart loss coefficient (default: 0.6)
        KS_TEMPERATURE      - Softmax temperature for KL loss (default: 2.0)
        KS_ANNEAL_START     - Fraction of training to start annealing (default: 0.5)
        KS_ANNEAL_END       - Fraction of training to finish annealing (default: 1.0)
        EER_LAMBDA          - Reward shaping scale for EER mode (default: 0.01)
        KS_TEACHER_LED      - Fraction of rollouts using teacher actions (default: 0.0)

Research approach hooks (Rounds 11+):
    REWARD_MODE     - chain_rewards | curiosity | none (default: none)
                      chain_rewards: Dense intermediate rewards for economy chain steps
                      curiosity: Count-based intrinsic motivation for novel (pos, inventory) states
    REWARD_SCALE    - Magnitude for reward shaping (default: 0.5)
    ADVANTAGE_MODE  - standard | dual_gamma | prd (default: standard)
                      dual_gamma: Blend fast (0.99) and slow (0.999) gamma advantages
                      prd: Subtract team-mean advantage for individual credit assignment
    DUAL_GAMMA_ALPHA - Blend factor for dual-gamma (0=all slow, 1=all fast, default: 0.5)
    PRD_ALPHA       - Team-mean subtraction factor for PRD (default: 0.5)
    ENTROPY_MODE    - fixed | adaptive | cosine (default: fixed)
                      adaptive: Floor/ceiling controller — doubles ent_coef when below floor
                      cosine: Cosine schedule from ENT_COEF_MAX to ENT_COEF_MIN
    ENTROPY_TARGET  - Target entropy ratio for adaptive mode (default: 0.5)
    ENT_COEF_MAX    - Max/start ent_coef for cosine/adaptive (default: auto)
    ENT_COEF_MIN    - Min/end ent_coef for cosine/adaptive (default: auto)
    ENTROPY_FLOOR   - Below this entropy, aggressively boost (default: 0.3*max_entropy)
    ENTROPY_CEIL    - Above this entropy, gently decay (default: 0.7*max_entropy)
"""

import copy
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import torch
import torch.nn as nn

# 0a. Fixed-vibe injection (Phase 1 — R24)
#
# Root cause of 0 junctions in R1-R23: policy outputs Discrete(5) = movement only.
# Without supervisor, vibe_actions.fill(0) → default vibe → agents can't mine/craft/align.
#
# This monkey-patch transforms Discrete(5) policy actions into transport-encoded
# Discrete(40) actions with fixed vibe assignments per agent.
#
# Transport encoding (machina_1/arena/tutorial/four_score):
#   N_primary=5, N_vibe=7 (default, heart, gear, scrambler, aligner, miner, scout)
#   action < 5       → primary only, no vibe change
#   action >= 5      → offset = action - 5; primary = offset // 7; vibe = offset % 7
#   So: transport = 5 + primary * 7 + vibe_idx
#
# Usage:
#   VIBE_ROLES="miner,miner,miner,miner,aligner,aligner,aligner,aligner" python3 patch_and_train.py train ...
#   VIBE_ROLES="heart,heart,miner,miner,miner,miner,aligner,aligner" python3 patch_and_train.py train ...
_vibe_roles_str = os.environ.get("VIBE_ROLES", "")
if _vibe_roles_str:
    from mettagrid.envs.mettagrid_puffer_env import MettaGridPufferEnv

    _VIBE_NAME_TO_IDX = {
        "default": 0, "heart": 1, "gear": 2, "scrambler": 3,
        "aligner": 4, "miner": 5, "scout": 6,
    }
    _VIBE_ASSIGNMENT = [_VIBE_NAME_TO_IDX[r.strip()] for r in _vibe_roles_str.split(",")]
    _N_PRIMARY = 5
    _N_VIBE = 7

    _orig_mgpe_step = MettaGridPufferEnv.step

    def _vibe_step(self, actions):
        actions = np.asarray(actions, dtype=np.int32).copy()
        n = len(actions)
        for i in range(n):
            primary = int(actions[i]) % _N_PRIMARY
            vibe_idx = _VIBE_ASSIGNMENT[i % len(_VIBE_ASSIGNMENT)]
            actions[i] = _N_PRIMARY + primary * _N_VIBE + vibe_idx
        return _orig_mgpe_step(self, actions)

    MettaGridPufferEnv.step = _vibe_step
    print(f"[VIBE] Fixed vibe injection enabled")
    print(f"[VIBE] Roles: {_vibe_roles_str}")
    print(f"[VIBE] Assignment indices: {_VIBE_ASSIGNMENT}")
    print(f"[VIBE] Encoding: transport = {_N_PRIMARY} + primary * {_N_VIBE} + vibe_idx")

# 0b. Learnable vibe actions (Phase 2 — R24)
#
# When VIBE_ACTIONS=1, override PufferLib's action space to Discrete(40) so the
# policy learns WHEN to switch vibes. Removes the Phase 1 fixed-vibe monkey-patch
# (the env natively decodes transport actions).
_vibe_actions_learnable = os.environ.get("VIBE_ACTIONS", "") == "1"
if _vibe_actions_learnable:
    if _vibe_roles_str:
        print("[VIBE] WARNING: VIBE_ROLES ignored when VIBE_ACTIONS=1 (learnable vibes)")
        # Undo Phase 1 monkey-patch
        from mettagrid.envs.mettagrid_puffer_env import MettaGridPufferEnv
        MettaGridPufferEnv.step = _orig_mgpe_step
    print("[VIBE] Learnable vibe actions enabled — policy outputs Discrete(40)")
    print("[VIBE] PufferLib already reads single_transport_action_space = Discrete(40)")

# 0c. Monkey-patch to enable reward variants (credit, milestones, role_conditional, etc.)
#
# Problem: cogames 0.22 has reward_variants.apply_reward_variants() but it's NOT wired
# into the CLI or training pipeline. The CLI's parse_variants() only knows mission
# variants and rejects reward variant names.
#
# Solution: Two patches:
# (a) patch parse_variants to silently skip reward variant names
# (b) patch train() to call apply_reward_variants on env_cfg before training
_reward_variants_to_apply = []
try:
    from cogames.games.cogs_vs_clips.train.reward_variants import (
        AVAILABLE_REWARD_VARIANTS,
        apply_reward_variants as _apply_reward_variants,
    )
    import cogames.cli.utils as _cli_utils
    _orig_parse_variants = _cli_utils.parse_variants

    def _patched_parse_variants(registry, variants_arg):
        if not variants_arg:
            return _orig_parse_variants(registry, variants_arg)
        # Separate reward variants from mission variants
        global _reward_variants_to_apply
        mission_only = []
        for v in variants_arg:
            if v in AVAILABLE_REWARD_VARIANTS:
                if v not in _reward_variants_to_apply:
                    _reward_variants_to_apply.append(v)
            else:
                mission_only.append(v)
        if _reward_variants_to_apply:
            print(f"[SWEEP] Reward variants queued: {_reward_variants_to_apply}")
        return _orig_parse_variants(registry, mission_only if mission_only else None)

    _cli_utils.parse_variants = _patched_parse_variants

    # Patch train() to apply reward variants to env_cfg
    import cogames.train as _train_module
    _orig_train_fn = _train_module.train

    def _patched_train_fn(env_cfg=None, **kwargs):
        if env_cfg is not None and _reward_variants_to_apply:
            print(f"[SWEEP] Applying reward variants to env_cfg: {_reward_variants_to_apply}")
            _apply_reward_variants(env_cfg, variants=_reward_variants_to_apply)
        return _orig_train_fn(env_cfg=env_cfg, **kwargs)

    _train_module.train = _patched_train_fn
    print(f"[SWEEP] Patched CLI + train() for reward variants: {sorted(AVAILABLE_REWARD_VARIANTS)}")
except ImportError:
    print("[SWEEP] WARNING: Could not patch reward variants (cogames not found)")

# 1. Monkey-patch PuffeRL to intercept train_args
#    Also handles VIBE_ACTIONS=1 action space override for Phase 2.
import pufferlib.pufferl as pufferl

# --- Hyperparameter presets ---
PRESETS = {
    "metta_optimal": {
        "learning_rate": 0.00738,
        "gamma": 0.9986,
        "gae_lambda": 0.9354,
        "clip_coef": 0.367,
        "ent_coef": 0.0257,
        "vf_coef": 1.465,
        "vf_clip_coef": 0.1,
        "weight_decay": 0.3,
        "bptt_horizon": 256,
        "update_epochs": 1,
        "max_grad_norm": 1.5,
        "adam_eps": 6.7e-6,
    },
}

_preset_name = os.environ.get("SWEEP_PRESET", "")
_preset = PRESETS.get(_preset_name, {})
_overrides_raw = json.loads(os.environ.get("SWEEP_OVERRIDES", "{}"))
# Preset values are the base; explicit overrides win
_overrides = {**_preset, **_overrides_raw}
_fixes = set(os.environ.get("SWEEP_FIXES", "").split(",")) - {""}

# Kickstarting config
_kickstart_mode = os.environ.get("KICKSTART_MODE", "none")
_ks_coef = float(os.environ.get("KS_COEF", "0.6"))
_ks_temperature = float(os.environ.get("KS_TEMPERATURE", "2.0"))
_ks_anneal_start = float(os.environ.get("KS_ANNEAL_START", "0.5"))
_ks_anneal_end = float(os.environ.get("KS_ANNEAL_END", "1.0"))
_eer_lambda = float(os.environ.get("EER_LAMBDA", "0.01"))
_ks_teacher_led = float(os.environ.get("KS_TEACHER_LED", "0.0"))

# Research approach hooks (Rounds 11+)
_reward_mode = os.environ.get("REWARD_MODE", "none")
_reward_scale = float(os.environ.get("REWARD_SCALE", "0.5"))
_advantage_mode = os.environ.get("ADVANTAGE_MODE", "standard")
_dual_gamma_alpha = float(os.environ.get("DUAL_GAMMA_ALPHA", "0.5"))
_prd_alpha = float(os.environ.get("PRD_ALPHA", "0.5"))
_entropy_mode = os.environ.get("ENTROPY_MODE", "fixed")
_entropy_target = float(os.environ.get("ENTROPY_TARGET", "0.5"))
# Enhanced entropy collapse prevention (R21+)
_ent_coef_max = float(os.environ.get("ENT_COEF_MAX", "0.0"))  # 0 = use ent_coef from overrides
_ent_coef_min = float(os.environ.get("ENT_COEF_MIN", "0.0"))
_entropy_floor = float(os.environ.get("ENTROPY_FLOOR", "0.0"))  # min acceptable entropy
_entropy_ceil = float(os.environ.get("ENTROPY_CEIL", "0.0"))   # above this, reduce ent_coef

# Curiosity state: visit counts per (x, y, inv_state) tuple
_curiosity_counts = defaultdict(int)

if _preset_name:
    print(f"[SWEEP] Preset: {_preset_name} ({len(_preset)} params)")
if _overrides_raw:
    print(f"[SWEEP] Explicit overrides: {_overrides_raw}")
if _overrides:
    print(f"[SWEEP] Final overrides: {_overrides}")
if _fixes:
    print(f"[SWEEP] Enabling fixes: {_fixes}")
if _kickstart_mode != "none":
    print(f"[SWEEP] Kickstarting: mode={_kickstart_mode}, coef={_ks_coef}, "
          f"temp={_ks_temperature}, anneal=[{_ks_anneal_start},{_ks_anneal_end}]")
    if _kickstart_mode == "eer":
        print(f"[SWEEP]   EER lambda={_eer_lambda}")
    if _ks_teacher_led > 0:
        print(f"[SWEEP]   Teacher-led proportion={_ks_teacher_led}")
if _reward_mode != "none":
    print(f"[SWEEP] Reward mode: {_reward_mode} (scale={_reward_scale})")
if _advantage_mode != "standard":
    print(f"[SWEEP] Advantage mode: {_advantage_mode}")
if _entropy_mode != "fixed":
    if _entropy_mode == "cosine":
        print(f"[SWEEP] Entropy mode: cosine (max={_ent_coef_max}, min={_ent_coef_min})")
    elif _entropy_mode == "adaptive":
        print(f"[SWEEP] Entropy mode: adaptive (floor={_entropy_floor}, ceil={_entropy_ceil}, "
              f"coef_range=[{_ent_coef_min}, {_ent_coef_max}])")
    else:
        print(f"[SWEEP] Entropy mode: {_entropy_mode} (target={_entropy_target})")

# --- Hyperparam overrides + init-time patches ---
_orig_init = pufferl.PuffeRL.__init__


def _patched_init(self, train_args, *args, **kwargs):
    for k, v in _overrides.items():
        old_val = train_args.get(k, "MISSING")
        train_args[k] = v
        print(f"[SWEEP] {k}: {old_val} -> {v}")

    # Asymmetric clipping: set clip_high in config
    if "asym_clip" in _fixes:
        clip_coef = train_args.get("clip_coef", 0.2)
        clip_high = clip_coef * 1.5  # upper bound 50% wider
        train_args["clip_high"] = clip_high
        print(f"[SWEEP] Asymmetric clipping: low={clip_coef}, high={clip_high}")

    # PFO: set coefficient in config
    if "pfo" in _fixes:
        pfo_coef = float(os.environ.get("PFO_COEF", "1.0"))
        train_args["pfo_coef"] = pfo_coef
        print(f"[SWEEP] PFO coefficient: {pfo_coef}")

    # No value clipping
    if "no_vf_clip" in _fixes:
        train_args["no_vf_clip"] = True
        print("[SWEEP] Value function clipping disabled")

    # Call original init
    _orig_init(self, train_args, *args, **kwargs)

    # --- Post-init patches ---

    # AdamW ScheduleFree: replace optimizer (metta's choice)
    if "adamw_sf" in _fixes:
        try:
            from schedulefree import AdamWScheduleFree
            lr = train_args.get("learning_rate", 0.00738)
            wd = train_args.get("weight_decay", 0.3)
            momentum = float(os.environ.get("ADAMW_MOMENTUM", "0.98"))
            eps = train_args.get("adam_eps", 6.7e-6)
            self.optimizer = AdamWScheduleFree(
                self.policy.parameters(),
                lr=lr,
                weight_decay=wd,
                betas=(momentum, 0.999),
                eps=eps,
            )
            self.optimizer.train()
            print(f"[SWEEP] AdamW ScheduleFree: lr={lr}, wd={wd}, momentum={momentum}, eps={eps}")
        except ImportError:
            print("[SWEEP] WARNING: schedulefree not installed, falling back to AdamW")
            lr = train_args.get("learning_rate", 0.00738)
            wd = train_args.get("weight_decay", 0.3)
            eps = train_args.get("adam_eps", 6.7e-6)
            self.optimizer = torch.optim.AdamW(
                self.policy.parameters(),
                lr=lr,
                weight_decay=wd,
                betas=(train_args.get("adam_beta1", 0.95),
                       train_args.get("adam_beta2", 0.999)),
                eps=eps,
            )
            print(f"[SWEEP] AdamW fallback: lr={lr}, wd={wd}, eps={eps}")

    # PFO: Register forward hook on encoder's last Linear layer
    if "pfo" in _fixes:
        target_layer = None
        if hasattr(self.policy, '_net'):
            # LSTMPolicyNet / CortexPolicyNet: _net is Sequential(Linear, ReLU, Linear)
            for module in self.policy._net:
                if isinstance(module, nn.Linear):
                    target_layer = module  # last Linear in encoder

        if target_layer is not None:
            def _pfo_hook(module, input, output):
                self._pfo_pre_act = output
            target_layer.register_forward_hook(_pfo_hook)
            self._pfo_pre_act = None
            print(f"[SWEEP] PFO hook registered on {target_layer}")
        else:
            print("[SWEEP] WARNING: Could not find encoder Linear for PFO hook")

    # Separate LR: Recreate optimizer with actor/critic param groups
    if "sep_lr" in _fixes and "adamw_sf" not in _fixes:
        lr = train_args.get("learning_rate", 0.00092)
        critic_lr_ratio = float(os.environ.get("CRITIC_LR_RATIO", "0.2"))
        critic_lr = lr * critic_lr_ratio

        # Find value head parameters
        value_params = []
        if hasattr(self.policy, '_value_head'):
            value_params = list(self.policy._value_head.parameters())
        elif hasattr(self.policy, 'value_head'):
            value_params = list(self.policy.value_head.parameters())

        if value_params:
            value_ids = {id(p) for p in value_params}
            actor_params = [p for p in self.policy.parameters() if id(p) not in value_ids]

            self.optimizer = torch.optim.Adam([
                {"params": actor_params, "lr": lr},
                {"params": value_params, "lr": critic_lr},
            ], betas=(train_args.get("adam_beta1", 0.95),
                      train_args.get("adam_beta2", 0.999)),
               eps=train_args.get("adam_eps", 1e-8))
            print(f"[SWEEP] Separate LR: actor={lr}, critic={critic_lr} (ratio={critic_lr_ratio})")
        else:
            print("[SWEEP] WARNING: Could not find value head for separate LR")

    # Store initial parameters for Shrink+Perturb
    if "shrink_perturb" in _fixes:
        self._init_params = {
            name: param.data.clone()
            for name, param in self.policy.named_parameters()
        }
        print(f"[SWEEP] Stored {len(self._init_params)} initial parameter tensors")

    # ReDo: Store encoder layer references
    if "redo" in _fixes:
        self._redo_step = 0
        self._redo_interval = int(os.environ.get("REDO_INTERVAL", "100"))
        self._redo_tau = float(os.environ.get("REDO_TAU", "0.1"))
        print(f"[SWEEP] ReDo: interval={self._redo_interval}, tau={self._redo_tau}")

    # Target network: polyak-averaged VALUE HEAD only (not full policy)
    # We hook _value_head to swap in target predictions during evaluate()
    if "target_net" in _fixes:
        self._target_net_tau = float(os.environ.get("TARGET_NET_TAU", "0.005"))
        self._use_target_values = False  # flag: True during evaluate, False during train

        # Find value head on the policy (CortexPolicyNet or LSTMPolicyNet)
        value_head = getattr(self.policy, '_value_head', None)
        if value_head is None and hasattr(self.policy, '_net'):
            value_head = getattr(self.policy._net, '_value_head', None)

        if value_head is not None:
            # Deep copy just the value head (tiny: 1 Linear layer)
            self._target_value_head = copy.deepcopy(value_head)
            self._target_value_head.requires_grad_(False)
            self._target_value_head.eval()
            self._online_value_head = value_head

            # Register hook: during evaluate, replace value head output with target
            def _target_value_hook(module, input, output):
                if self._use_target_values:
                    with torch.no_grad():
                        return self._target_value_head(input[0])
                return output

            value_head.register_forward_hook(_target_value_hook)
            print(f"[SWEEP] Target value head: tau={self._target_net_tau}, hooked on {value_head}")
        else:
            print("[SWEEP] WARNING: Could not find _value_head for target net")

    # Kickstarting: initialize teacher and step counter
    if _kickstart_mode != "none":
        self._ks_global_step = 0
        self._ks_total_steps = train_args.get("total_timesteps", 50_000_000)
        print(f"[SWEEP] Kickstart initialized: total_steps={self._ks_total_steps}")


pufferl.PuffeRL.__init__ = _patched_init

# --- Training loop patches ---
_orig_train = pufferl.PuffeRL.train


def _patched_train(self):
    # Adam-Rel: reset optimizer timestep BEFORE training epoch
    if "adam_rel" in _fixes:
        for group in self.optimizer.param_groups:
            for p in group["params"]:
                if p in self.optimizer.state:
                    state = self.optimizer.state[p]
                    if "step" in state:
                        state["step"].zero_()

    # Adaptive/cosine entropy: adjust ent_coef to prevent collapse
    if _entropy_mode in ("adaptive", "cosine"):
        try:
            _apply_adaptive_entropy(self)
        except Exception as e:
            if not hasattr(self, '_adaptive_ent_warned'):
                print(f"[SWEEP] Adaptive entropy warning (once): {e}")
                self._adaptive_ent_warned = True

    # Run original training (which now includes PFO loss + asymmetric clipping
    # if pufferl.py was patched by apply_tier1_patches.py)
    # NOTE: Dual-gamma and PRD are now applied via compute_puff_advantage patch
    result = _orig_train(self)

    # Soft Shrink+Perturb: after each training epoch, nudge weights toward init
    if "shrink_perturb" in _fixes and hasattr(self, "_init_params"):
        beta = 1e-4  # stronger than before (was 1e-6)
        with torch.no_grad():
            for name, param in self.policy.named_parameters():
                if name in self._init_params:
                    param.data.mul_(1 - beta).add_(
                        beta * self._init_params[name].to(param.device)
                    )

    # ReDo: Dormant neuron recycling
    if "redo" in _fixes:
        self._redo_step += 1
        if self._redo_step % self._redo_interval == 0:
            _redo_recycle(self)

    # Target network: polyak update the target value head after each training epoch
    if "target_net" in _fixes and hasattr(self, '_target_value_head'):
        tau = self._target_net_tau
        with torch.no_grad():
            for p_target, p_online in zip(
                self._target_value_head.parameters(),
                self._online_value_head.parameters(),
            ):
                p_target.data.mul_(1 - tau).add_(tau * p_online.data)

    # Encoder health monitoring: detect dead neurons via bias drift
    if hasattr(self, 'global_step') and self.global_step % 100 == 0:
        try:
            net = getattr(self.policy, '_net', None)
            if net is not None:
                for module in net:
                    if isinstance(module, nn.Linear) and module.bias is not None:
                        bias_max = module.bias.data.max().item()
                        bias_min = module.bias.data.min().item()
                        if bias_max < -0.5:
                            print(f"[ENCODER] WARNING: Dead encoder detected! "
                                  f"bias_max={bias_max:.4f}, bias_min={bias_min:.4f}, "
                                  f"step={self.global_step}")
                        elif self.global_step % 500_000 < getattr(
                            self, 'train_args', {}
                        ).get("batch_size", 65536):
                            print(f"[ENCODER] bias_max={bias_max:.4f}, "
                                  f"bias_min={bias_min:.4f}, step={self.global_step}")
                        break  # Only check first Linear layer
        except Exception:
            pass

    return result


def _apply_adaptive_entropy(trainer):
    """Entropy collapse prevention with configurable modes.

    Modes (ENTROPY_MODE):
      - "adaptive": Floor/ceiling controller — aggressively boost when below floor,
                     gently decay when above ceiling. Much stronger than the old 5% ramp.
      - "cosine": Cosine schedule from ENT_COEF_MAX to ENT_COEF_MIN over training.
                  Does NOT respond to current entropy — purely schedule-based.

    Env vars:
      ENTROPY_FLOOR  - Below this entropy, multiply ent_coef by 2.0 each epoch (aggressive)
      ENTROPY_CEIL   - Above this entropy, multiply ent_coef by 0.99 (gentle decay)
      ENT_COEF_MAX   - Max ent_coef (for cosine: start value; for adaptive: clamp)
      ENT_COEF_MIN   - Min ent_coef (for cosine: end value; for adaptive: clamp)
    """
    n_actions = 40 if _vibe_actions_learnable else 5
    max_entropy = math.log(n_actions)

    if _entropy_mode == "cosine":
        # Pure cosine schedule: ENT_COEF_MAX → ENT_COEF_MIN over training
        total = getattr(trainer, '_ks_total_steps', None)
        if total is None:
            total = getattr(trainer, 'train_args', {}).get("total_timesteps", 1_000_000_000)
        progress = trainer.global_step / max(total, 1)
        progress = min(progress, 1.0)
        coef = _ent_coef_min + 0.5 * (_ent_coef_max - _ent_coef_min) * (1 + math.cos(math.pi * progress))
        if hasattr(trainer, 'train_args') and 'ent_coef' in trainer.train_args:
            old = trainer.train_args['ent_coef']
            trainer.train_args['ent_coef'] = coef
            if trainer.global_step % 5_000_000 < getattr(trainer, 'train_args', {}).get("batch_size", 65536):
                print(f"[ENTROPY] cosine: progress={progress:.3f}, ent_coef={old:.4f} -> {coef:.4f}")
        return

    # "adaptive" mode: respond to current entropy
    current_entropy = None
    # PufferLib 3.0 stores entropy in self.losses dict (updated each train() call)
    if hasattr(trainer, 'losses') and isinstance(trainer.losses, dict):
        current_entropy = trainer.losses.get('entropy', None)
    # Fallback: check stats or last_log
    if current_entropy is None and hasattr(trainer, 'stats') and isinstance(trainer.stats, dict):
        current_entropy = trainer.stats.get('entropy', None)
    if current_entropy is None:
        return
    if isinstance(current_entropy, torch.Tensor):
        current_entropy = current_entropy.item()

    floor = _entropy_floor if _entropy_floor > 0 else 0.3 * max_entropy
    ceil = _entropy_ceil if _entropy_ceil > 0 else 0.7 * max_entropy
    lo = _ent_coef_min if _ent_coef_min > 0 else 0.01
    hi = _ent_coef_max if _ent_coef_max > 0 else 0.30

    if hasattr(trainer, 'train_args') and 'ent_coef' in trainer.train_args:
        ent = trainer.train_args['ent_coef']
        old_ent = ent
        if current_entropy < floor:
            # AGGRESSIVE boost — double ent_coef each epoch
            ent = min(ent * 2.0, hi)
        elif current_entropy > ceil:
            # Gentle decay
            ent *= 0.99
        # Clamp
        ent = max(lo, min(hi, ent))
        trainer.train_args['ent_coef'] = ent
        if trainer.global_step % 5_000_000 < getattr(trainer, 'train_args', {}).get("batch_size", 65536):
            print(f"[ENTROPY] adaptive: H={current_entropy:.3f} (floor={floor:.3f}, ceil={ceil:.3f}), "
                  f"ent_coef={old_ent:.4f} -> {ent:.4f}")


def _redo_recycle(trainer):
    """ReDo: Recycle dormant neurons in encoder layers (Sokar et al., ICML 2023).

    A neuron is dormant if its outgoing weight norm < tau * mean norm.
    Dormant neurons get reinitialized with fresh random weights;
    their outgoing connections in the next layer are zeroed to preserve function.
    """
    tau = trainer._redo_tau
    total_recycled = 0

    if not hasattr(trainer.policy, '_net'):
        return

    # Get encoder layers: _net is Sequential(Linear, ReLU, Linear)
    layers = [m for m in trainer.policy._net if isinstance(m, nn.Linear)]

    with torch.no_grad():
        for i, layer in enumerate(layers):
            weight_norms = layer.weight.norm(dim=1)  # norm per output neuron
            mean_norm = weight_norms.mean()

            if mean_norm < 1e-8:
                continue

            dormant = weight_norms < tau * mean_norm
            n_dormant = dormant.sum().item()

            if n_dormant == 0:
                continue

            # Reinitialize incoming weights (orthogonal, like layer_init)
            fan_in = layer.weight.shape[1]
            std = (2.0 / fan_in) ** 0.5
            layer.weight.data[dormant] = torch.randn_like(
                layer.weight.data[dormant]
            ) * std
            if layer.bias is not None:
                layer.bias.data[dormant] = 0.0

            # Zero outgoing connections in the NEXT layer to preserve function
            if i + 1 < len(layers):
                next_layer = layers[i + 1]
                next_layer.weight.data[:, dormant] = 0.0
            else:
                # Last encoder layer feeds into LSTM/Cortex
                # Try to zero corresponding input weights in the recurrent core
                if hasattr(trainer.policy, '_rnn'):
                    rnn = trainer.policy._rnn
                    if hasattr(rnn, 'weight_ih_l0'):
                        rnn.weight_ih_l0.data[:, dormant] = 0.0
                elif hasattr(trainer.policy, '_cortex'):
                    # Cortex handles this internally; skip
                    pass

            total_recycled += n_dormant

    if total_recycled > 0:
        print(f"[REDO] Step {trainer._redo_step}: recycled {total_recycled} dormant neurons")


if _fixes or _advantage_mode != "standard" or _entropy_mode != "fixed":
    pufferl.PuffeRL.train = _patched_train

# --- Advantage manipulation: monkey-patch compute_puff_advantage ---
# PufferLib 3.0 computes advantages as a local variable inside train().
# We wrap compute_puff_advantage to post-process the result.
if _advantage_mode != "standard":
    _orig_compute_advantage = pufferl.compute_puff_advantage

    def _patched_compute_advantage(
        values, rewards, terminals, ratio, advantages, gamma, gae_lambda,
        vtrace_rho_clip, vtrace_c_clip,
    ):
        # Compute normal (fast-gamma) advantages
        result = _orig_compute_advantage(
            values, rewards, terminals, ratio, advantages, gamma, gae_lambda,
            vtrace_rho_clip, vtrace_c_clip,
        )

        if _advantage_mode == "dual_gamma":
            try:
                _apply_dual_gamma_post(result, values, rewards, terminals, gamma, gae_lambda)
            except Exception as e:
                if not hasattr(_patched_compute_advantage, '_warned'):
                    print(f"[SWEEP] Dual-gamma warning (once): {e}")
                    _patched_compute_advantage._warned = True

        elif _advantage_mode == "prd":
            try:
                _apply_prd_post(result)
            except Exception as e:
                if not hasattr(_patched_compute_advantage, '_prd_warned'):
                    print(f"[SWEEP] PRD warning (once): {e}")
                    _patched_compute_advantage._prd_warned = True

        return result

    pufferl.compute_puff_advantage = _patched_compute_advantage


def _apply_dual_gamma_post(advantages, values, rewards, terminals, fast_gamma, gae_lambda):
    """Dual-gamma: compute slow-gamma advantages and blend with fast.

    advantages is modified in-place (it's the tensor passed to compute_puff_advantage).
    """
    alpha = _dual_gamma_alpha
    slow_gamma = 0.999

    # Save fast advantages
    fast_adv = advantages.clone()

    # Compute slow-gamma GAE manually (advantages tensor shape: [segments, bptt_horizon])
    segs, T = advantages.shape
    lastgaelam = torch.zeros(segs, device=advantages.device)

    for t in reversed(range(T)):
        if t == T - 1:
            next_val = values[:, t]  # bootstrap from last value
            next_nonterminal = 1.0
        else:
            next_val = values[:, t + 1]
            next_nonterminal = 1.0 - terminals[:, t + 1]

        delta = rewards[:, t] + slow_gamma * next_val * next_nonterminal - values[:, t]
        lastgaelam = delta + slow_gamma * gae_lambda * next_nonterminal * lastgaelam
        advantages[:, t] = lastgaelam

    slow_adv = advantages.clone()

    # Blend: alpha * fast + (1-alpha) * slow
    blended = alpha * fast_adv + (1 - alpha) * slow_adv

    # Normalize per-segment
    adv_mean = blended.mean()
    adv_std = blended.std() + 1e-8
    advantages.copy_((blended - adv_mean) / adv_std)


def _apply_prd_post(advantages):
    """PRD: subtract team-mean advantage for individual credit assignment.

    advantages shape: [segments, bptt_horizon]. Segments contain interleaved agent data.
    """
    alpha = _prd_alpha
    num_agents = 8  # cogames default

    segs = advantages.shape[0]
    if segs % num_agents != 0:
        return

    # Reshape to (n_groups, num_agents, bptt_horizon)
    n_groups = segs // num_agents
    reshaped = advantages.reshape(n_groups, num_agents, -1)
    team_mean = reshaped.mean(dim=1, keepdim=True)
    reshaped -= alpha * team_mean
    advantages.copy_(reshaped.reshape_as(advantages))


# --- Target network: enable target value head during evaluate ---
# The forward hook on _value_head swaps to target predictions when _use_target_values=True.
# We set the flag around evaluate() so GAE uses stable target values.
if "target_net" in _fixes:
    _orig_evaluate_tnet = pufferl.PuffeRL.evaluate

    def _patched_evaluate_tnet(self):
        if hasattr(self, '_use_target_values'):
            self._use_target_values = True
        result = _orig_evaluate_tnet(self)
        if hasattr(self, '_use_target_values'):
            self._use_target_values = False
        return result

    pufferl.PuffeRL.evaluate = _patched_evaluate_tnet

# --- Evaluate hook for reward shaping ---
if _reward_mode != "none":
    _orig_evaluate = pufferl.PuffeRL.evaluate

    def _patched_evaluate(self):
        result = _orig_evaluate(self)

        if _reward_mode == "chain_rewards":
            _apply_chain_rewards(self)
        elif _reward_mode == "curiosity":
            _apply_curiosity_rewards(self)

        return result

    pufferl.PuffeRL.evaluate = _patched_evaluate


def _apply_chain_rewards(trainer):
    """Dense chain rewards: reward intermediate economy chain steps.

    Monitors observation deltas to detect:
    - Heart gained (mining chain complete): +0.5 * scale
    - Gear crafted: +1.0 * scale
    - Near junction with gear: +0.3 * scale

    Uses the observation buffer in trainer.obs to detect changes.
    Observation format: mettagrid token grid, specific feature indices TBD.
    Falls back to reward_buffer if obs features are not accessible.
    """
    try:
        rewards = trainer.rewards
        if rewards is None:
            return
        # Access current observations (PufferLib 3.0: self.observations)
        obs = trainer.observations if hasattr(trainer, 'observations') else None
        if obs is None or not hasattr(trainer, '_prev_obs_chain'):
            # First call: store observations for next delta
            if obs is not None:
                trainer._prev_obs_chain = obs.clone()
            return

        prev_obs = trainer._prev_obs_chain

        # Detect observation deltas across all agents
        # obs shape: (num_envs * num_agents, obs_dim) or (num_envs * num_agents, H, W, C)
        if obs.dim() >= 2:
            # Flatten to 2D if needed
            flat_obs = obs.reshape(obs.shape[0], -1).float()
            flat_prev = prev_obs.reshape(prev_obs.shape[0], -1).float()
            delta = flat_obs - flat_prev

            # Heuristic: large positive deltas in inventory features indicate gains
            # Sum absolute changes as a proxy for "something happened"
            change_magnitude = delta.abs().sum(dim=1)

            # Reward agents that had significant observation changes
            # This is a coarse approximation -- refine with actual feature indices
            significant = change_magnitude > 5.0  # threshold for "something happened"
            bonus = significant.float() * _reward_scale * 0.1

            rewards[:bonus.shape[0]] += bonus.to(rewards.device)

        trainer._prev_obs_chain = obs.clone()

    except Exception as e:
        # Silently skip if reward shaping fails -- don't crash training
        if not hasattr(trainer, '_chain_reward_warned'):
            print(f"[SWEEP] Chain reward warning (once): {e}")
            trainer._chain_reward_warned = True


def _apply_curiosity_rewards(trainer):
    """Count-based curiosity: reward novel (position, inventory) observations.

    intrinsic_reward = beta / sqrt(visit_count[key])
    """
    global _curiosity_counts
    try:
        rewards = trainer.rewards
        if rewards is None:
            return
        obs = trainer.observations if hasattr(trainer, 'observations') else None
        if obs is None:
            return

        flat_obs = obs.reshape(obs.shape[0], -1)
        n_agents = flat_obs.shape[0]

        for i in range(n_agents):
            # Use first 8 features as hash key (coarse state identifier)
            key = tuple(flat_obs[i, :8].cpu().numpy().astype(int).tolist())
            _curiosity_counts[key] += 1
            count = _curiosity_counts[key]
            intrinsic = _reward_scale / math.sqrt(count)
            rewards[i] += intrinsic

    except Exception as e:
        if not hasattr(trainer, '_curiosity_reward_warned'):
            print(f"[SWEEP] Curiosity reward warning (once): {e}")
            trainer._curiosity_reward_warned = True


# --- Kickstarting: pre-compute teacher actions + EER reward shaping ---
# The actual KL/CE loss injection is done by apply_kickstart_patches.py which
# source-patches pufferl.py train() to check self._ks_teacher_actions.
# Here we: (1) wrap evaluate() to pre-compute teacher actions for the full buffer,
# (2) compute annealing coefficient, (3) add EER reward bonus.
if _kickstart_mode != "none":
    # Import teacher — add scripts/policy to path
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _policy_dir = os.path.join(os.path.dirname(_script_dir), "policy")
    if _policy_dir not in sys.path:
        sys.path.insert(0, _policy_dir)
    from scripted_teacher import teacher_action

    def _compute_teacher_actions_buffer(trainer):
        """Pre-compute teacher actions for the FULL rollout buffer.

        observations shape: [segments, horizon, *obs_shape]
        Returns: teacher_actions tensor [segments, horizon] (long, on device)
        """
        obs = trainer.observations  # [segments, horizon, N, 3] or [segments, horizon, obs_dim]
        segments, horizon = obs.shape[0], obs.shape[1]
        device = trainer.actions.device

        teacher_acts = torch.zeros(segments, horizon, dtype=torch.long, device=device)

        # Move obs to CPU for numpy conversion (may already be CPU if cpu_offload)
        obs_cpu = obs.cpu().numpy() if obs.is_cuda else obs.numpy()

        for s in range(segments):
            agent_idx = s % 8  # cogames: 8 agents per env
            for h in range(horizon):
                flat = obs_cpu[s, h].flatten()
                n_tok = len(flat) // 3
                if n_tok > 0:
                    tokens = flat[:n_tok * 3].reshape(-1, 3).astype(np.int32)
                    teacher_acts[s, h] = teacher_action(tokens, agent_idx, trainer.global_step + h)

        return teacher_acts

    def _compute_ks_annealing(trainer):
        """Compute effective kickstart coefficient with linear annealing."""
        total = trainer.config.get("total_timesteps", 50_000_000)
        progress = trainer.global_step / max(total, 1)

        if progress < _ks_anneal_start:
            alpha = 1.0
        elif progress < _ks_anneal_end:
            frac = (progress - _ks_anneal_start) / max(_ks_anneal_end - _ks_anneal_start, 1e-8)
            alpha = 1.0 - frac
        else:
            alpha = 0.0

        return _ks_coef * alpha

    def _apply_eer_reward_shaping(trainer):
        """EER: add lambda * log(pi_student(a_teacher|s)) to rewards buffer.

        Operates on the FULL rollout buffer (not per-step).
        rewards shape: [segments, horizon]
        """
        obs = trainer.observations  # [segments, horizon, *obs_shape]
        rewards = trainer.rewards  # [segments, horizon]
        segments, horizon = obs.shape[0], obs.shape[1]

        # Forward pass on flat observations to get student log-probs
        # Reshape: [segments * horizon, *obs_shape]
        flat_obs = obs.reshape(-1, *obs.shape[2:])
        if flat_obs.device != trainer.config["device"]:
            flat_obs = flat_obs.to(trainer.config["device"])

        # Process in chunks to avoid OOM on large buffers
        chunk_size = 4096
        n_total = flat_obs.shape[0]
        all_log_probs = []

        with torch.no_grad():
            for start in range(0, n_total, chunk_size):
                end = min(start + chunk_size, n_total)
                chunk_obs = flat_obs[start:end]
                # Use forward_eval if available (no LSTM state needed for log_probs)
                state = dict(action=None, lstm_h=None, lstm_c=None)
                logits, _ = trainer.policy(chunk_obs, state)
                lp = torch.nn.functional.log_softmax(logits, dim=-1)
                all_log_probs.append(lp)

        all_log_probs = torch.cat(all_log_probs, dim=0)  # [segments*horizon, n_actions]

        # Get teacher actions (already computed)
        teacher_acts = trainer._ks_teacher_actions  # [segments, horizon]
        flat_teacher = teacher_acts.reshape(-1).long()  # [segments*horizon]

        # Gather log_prob of teacher action: log_probs[i, teacher_act[i]]
        teacher_log_probs = all_log_probs.gather(
            1, flat_teacher.unsqueeze(1).to(all_log_probs.device)
        ).squeeze(1)  # [segments*horizon]

        # Add bonus to rewards
        bonus = _eer_lambda * teacher_log_probs.reshape(segments, horizon)
        rewards += bonus.to(rewards.device)

    # Wrap evaluate() to set up teacher actions and EER BETWEEN evaluate and train
    _orig_evaluate_ks = pufferl.PuffeRL.evaluate

    def _patched_evaluate_ks(self):
        result = _orig_evaluate_ks(self)

        # Compute annealing coefficient
        self._ks_effective_coef = _compute_ks_annealing(self)

        if self._ks_effective_coef < 1e-6:
            self._ks_teacher_actions = None
            return result

        try:
            # Pre-compute teacher actions for the full rollout buffer
            self._ks_teacher_actions = _compute_teacher_actions_buffer(self)

            # EER: add reward shaping bonus
            if _kickstart_mode == "eer":
                _apply_eer_reward_shaping(self)

            # Log occasionally — include teacher action distribution
            if self.global_step % 500_000 < self.config.get("batch_size", 65536):
                total = self.config.get("total_timesteps", 50_000_000)
                progress = self.global_step / max(total, 1)
                # Teacher action distribution diagnostic
                ta = self._ks_teacher_actions
                n_total = ta.numel()
                if _vibe_actions_learnable:
                    # Transport-encoded: show primary + vibe breakdown
                    act_names = ["noop", "north", "south", "west", "east"]
                    vibe_names = ["default", "heart", "gear", "scrambler", "aligner", "miner", "scout"]
                    # Primary distribution (decode from transport)
                    primaries = torch.where(ta < 5, ta, (ta - 5) // 7)
                    dist_parts = []
                    for a_idx in range(5):
                        frac = (primaries == a_idx).sum().item() / max(n_total, 1)
                        dist_parts.append(f"{act_names[a_idx]}={frac:.1%}")
                    # Vibe distribution
                    has_vibe = ta >= 5
                    vibes = (ta[has_vibe] - 5) % 7 if has_vibe.any() else torch.tensor([])
                    vibe_parts = []
                    for v_idx in range(7):
                        frac = (vibes == v_idx).sum().item() / max(n_total, 1)
                        if frac > 0.01:
                            vibe_parts.append(f"{vibe_names[v_idx]}={frac:.1%}")
                    dist_str = ", ".join(dist_parts) + " | vibes: " + ", ".join(vibe_parts)
                else:
                    act_names = ["noop", "north", "south", "west", "east"]
                    dist_parts = []
                    for a_idx in range(5):
                        frac = (ta == a_idx).sum().item() / max(n_total, 1)
                        dist_parts.append(f"{act_names[a_idx]}={frac:.1%}")
                    dist_str = ", ".join(dist_parts)
                noop_frac = (ta == 0).sum().item() / max(n_total, 1)
                warn = " ** ALL NOOP — TEACHER BROKEN **" if noop_frac > 0.95 else ""
                print(f"[KICKSTART] step={self.global_step}, "
                      f"progress={progress:.3f}, "
                      f"effective_coef={self._ks_effective_coef:.4f}, "
                      f"teacher_dist=[{dist_str}]{warn}")

        except Exception as e:
            if not hasattr(self, '_ks_warned'):
                print(f"[KICKSTART] Warning (once): {e}")
                import traceback
                traceback.print_exc()
                self._ks_warned = True
            self._ks_teacher_actions = None

        return result

    pufferl.PuffeRL.evaluate = _patched_evaluate_ks

    # Store teacher function on PuffeRL instances for teacher-led
    # (used by the source-patched evaluate() in pufferl.py)
    if _ks_teacher_led > 0:
        _orig_init_ks = pufferl.PuffeRL.__init__
        # Check if __init__ is already patched (it is — _patched_init)
        # We need to add to the CURRENT __init__, not the original
        _current_init = pufferl.PuffeRL.__init__

        def _patched_init_ks(self, *args, **kwargs):
            _current_init(self, *args, **kwargs)
            self._ks_teacher_fn = teacher_action
            self._ks_teacher_led_frac = _ks_teacher_led
            print(f"[KICKSTART] Teacher-led: fraction={_ks_teacher_led}")

        pufferl.PuffeRL.__init__ = _patched_init_ks


# 2. Forward to cogames CLI
sys.argv[0] = "cogames"
from cogames.main import app
app()
