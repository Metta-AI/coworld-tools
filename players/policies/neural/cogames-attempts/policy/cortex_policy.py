"""Cortex policy for CogsGuard — drop-in replacement for LSTMPolicyNet.

Matches the native LSTMPolicyNet architecture exactly (Linear encoder,
same hidden_size, same obs preprocessing) but swaps nn.LSTM for a Cortex
stack. This isolates the Cortex recurrent core from encoder differences.

PufferLib zeros ALL recurrent state at the start of every evaluate() call,
so state never persists beyond bptt_horizon steps. State packing only needs
to survive within a single evaluate() window.

Usage:
    # Match native LSTM exactly (1 Cortex-LSTM layer, d=128)
    net = CortexPolicyNet(policy_env_info)

    # Swap in Axon cells
    net = CortexPolicyNet(policy_env_info, preset="axon")

    # Full Ag,A,S stack
    net = CortexPolicyNet(policy_env_info, preset="agas")
"""

from __future__ import annotations

import os
from typing import Optional, Sequence

import numpy as np
import pufferlib.pytorch
import torch
import torch.nn as nn
from einops import rearrange

from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy, StatefulAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface

from cortex.stacks import build_cortex_auto_stack

# Pattern-based presets: (pattern_string_or_list, num_layers)
# Pattern tokens: L=LSTM, A=Axon, Ag=AGaLiTe, S=sLSTM, M=mLSTM, X=XL, C=CausalConv1d
# Axonified variants: S^=sLSTM+RTRL, M^=mLSTM+RTRL
PATTERN_PRESETS = {
    # --- Single cells ---
    "lstm": ("L", 1),
    "lstm2": ("L", 2),            # 2 LSTM layers
    "axon": ("A", 1),             # Axon (RTRL)
    "slstm": ("S", 1),           # sLSTM (stabilized gating)
    "mlstm": ("M", 1),           # mLSTM (multiplicative LSTM)
    "agalite": ("Ag", 1),        # AGaLiTe (attention-based)
    "xl": ("X", 1),              # XL (extended recurrent)
    "conv1d": ("C", 1),          # CausalConv1d (no true recurrence)
    # --- Axonified variants (cell + RTRL gradient flow) ---
    "slstm_axon": ("S^", 1),    # sLSTM axonified
    "mlstm_axon": ("M^", 1),    # mLSTM axonified
    # --- Multi-cell combinations (routed Column) ---
    "agas": ("Ag,A,S", 1),       # 1 Column layer with 3 experts
    "agas2": ("Ag,A,S", 2),      # 2 Column layers with 3 experts each
    "ls": ("L,S", 1),            # LSTM + sLSTM routed
    "lm": ("L,M", 1),            # LSTM + mLSTM routed
    "la": ("L,A", 1),            # LSTM + Axon routed
    # --- Sequential combinations (separate layers) ---
    "agas_seq": (["Ag", "A", "S"], 3),  # 3 sequential layers, 1 cell each
    "ls_seq": (["L", "S"], 2),   # LSTM → sLSTM sequential
    "lm_seq": (["L", "M"], 2),   # LSTM → mLSTM sequential
    "la_seq": (["L", "A"], 2),   # LSTM → Axon sequential
}


class SeparateACPolicyNet(nn.Module):
    """Separate actor/critic LSTM policy — no shared features.

    Two independent LSTM backbones: one for policy (actor) and one for value
    (critic). Prevents critic convergence from degrading actor representations.

    State packing: actor_h and critic_h are concatenated along the hidden dim
    into a single lstm_h buffer. Same for lstm_c. PufferLib sees hidden_size
    = 2 * d_hidden, but internally we split at the midpoint.
    """

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        d_hidden: int = 128,
    ):
        super().__init__()

        self.d_hidden = d_hidden
        obs_size = int(np.prod(policy_env_info.observation_space.shape))
        num_primary = len(policy_env_info.action_names)
        num_vibe = len(policy_env_info.vibe_action_names)
        if os.environ.get("VIBE_ACTIONS", "") == "1" and num_vibe > 0:
            num_actions = num_primary + num_primary * num_vibe
        else:
            num_actions = num_primary

        # Actor network (encoder + LSTM + action head)
        self._actor_net = nn.Sequential(
            pufferlib.pytorch.layer_init(nn.Linear(obs_size, d_hidden)),
            nn.LeakyReLU(0.01),
            pufferlib.pytorch.layer_init(nn.Linear(d_hidden, d_hidden)),
        )
        self._actor_rnn = nn.LSTM(d_hidden, d_hidden, num_layers=1, batch_first=True)
        self._action_head = nn.Linear(d_hidden, num_actions)

        # Critic network (encoder + LSTM + value head) — completely separate
        self._critic_net = nn.Sequential(
            pufferlib.pytorch.layer_init(nn.Linear(obs_size, d_hidden)),
            nn.LeakyReLU(0.01),
            pufferlib.pytorch.layer_init(nn.Linear(d_hidden, d_hidden)),
        )
        self._critic_rnn = nn.LSTM(d_hidden, d_hidden, num_layers=1, batch_first=True)
        self._value_head = nn.Linear(d_hidden, 1)

        # PufferLib compatibility: hidden_size = 2 * d_hidden (packed)
        self.hidden_size = d_hidden * 2

        # Also expose _net for PFO hook compatibility (points to actor encoder)
        self._net = self._actor_net

    def forward(self, observations, state=None):
        orig_shape = observations.shape
        obs_size = self._actor_net[0].in_features
        total_elements = observations.numel()
        batch_size = orig_shape[0]

        if total_elements // batch_size != obs_size:
            bptt_horizon = total_elements // (batch_size * obs_size)
            segments = batch_size
            observations = observations.reshape(
                segments * bptt_horizon, obs_size,
            ).float()
        else:
            segments = batch_size
            bptt_horizon = 1
            observations = observations.reshape(segments, obs_size).float()

        if observations.max() > 1.0:
            observations = observations / 255.0

        # Unpack state: split along hidden dim
        actor_h, actor_c, critic_h, critic_c = None, None, None, None
        if state is not None:
            h = state.get("lstm_h")
            c = state.get("lstm_c")
            if h is not None and c is not None:
                d = self.d_hidden
                # h/c shape: (batch, hidden_size) where hidden_size = 2*d_hidden
                actor_h = h[:, :d].unsqueeze(0).contiguous()   # (1, B, d)
                critic_h = h[:, d:].unsqueeze(0).contiguous()
                actor_c = c[:, :d].unsqueeze(0).contiguous()
                critic_c = c[:, d:].unsqueeze(0).contiguous()

        # Actor forward
        actor_features = self._actor_net(observations)
        actor_features = actor_features.reshape(segments, bptt_horizon, self.d_hidden)
        if actor_h is not None:
            actor_out, (new_actor_h, new_actor_c) = self._actor_rnn(
                actor_features, (actor_h, actor_c)
            )
        else:
            actor_out, (new_actor_h, new_actor_c) = self._actor_rnn(actor_features)

        # Critic forward
        critic_features = self._critic_net(observations)
        critic_features = critic_features.reshape(segments, bptt_horizon, self.d_hidden)
        if critic_h is not None:
            critic_out, (new_critic_h, new_critic_c) = self._critic_rnn(
                critic_features, (critic_h, critic_c)
            )
        else:
            critic_out, (new_critic_h, new_critic_c) = self._critic_rnn(critic_features)

        # Pack state back: concatenate along hidden dim
        if state is not None:
            state["lstm_h"] = torch.cat(
                [new_actor_h.squeeze(0), new_critic_h.squeeze(0)], dim=-1
            )
            state["lstm_c"] = torch.cat(
                [new_actor_c.squeeze(0), new_critic_c.squeeze(0)], dim=-1
            )

        # Heads
        actor_flat = actor_out.reshape(segments * bptt_horizon, self.d_hidden)
        critic_flat = critic_out.reshape(segments * bptt_horizon, self.d_hidden)

        return self._action_head(actor_flat), self._value_head(critic_flat)

    def forward_eval(self, observations, state=None):
        return self.forward(observations, state)


class CortexPolicyNet(nn.Module):
    """Linear encoder + Cortex recurrent core + actor-critic heads.

    Architecture matches LSTMPolicyNet exactly:
      - Linear(obs_flat → d_hidden) → ReLU → Linear(d_hidden → d_hidden)
      - Cortex stack (configurable cells)
      - Linear heads for actions and value
    """

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        d_hidden: int = 128,
        num_layers: int = 1,
        preset: str = "lstm",
    ):
        super().__init__()

        self.d_hidden = d_hidden
        obs_size = int(np.prod(policy_env_info.observation_space.shape))

        # Encoder — identical to LSTMPolicyNet (LeakyReLU prevents dying neurons)
        self._net = nn.Sequential(
            pufferlib.pytorch.layer_init(nn.Linear(obs_size, d_hidden)),
            nn.LeakyReLU(0.01),
            pufferlib.pytorch.layer_init(nn.Linear(d_hidden, d_hidden)),
        )

        # Cortex core -- pattern-based API
        pattern, default_num_layers = PATTERN_PRESETS.get(preset, PATTERN_PRESETS["lstm"])

        self._cortex = build_cortex_auto_stack(
            d_hidden=d_hidden,
            num_layers=default_num_layers,
            pattern=pattern,
            post_norm=False,
        )

        # Compute state size for PufferLib compatibility.
        # Axonified cells (S^, M^) add RTRL auxiliary state during forward
        # that isn't present in init_state. Run a dummy forward to measure.
        _init_template = self._cortex.init_state(batch=1, dtype=torch.float32)
        with torch.no_grad():
            _dummy_in = torch.zeros(1, 1, d_hidden)
            _, _template = self._cortex(_dummy_in, _init_template)
        self._state_leaf_shapes: list[tuple[str, torch.Size, int]] = []
        self._init_state_values: dict[int, float] = {}
        total_numel = 0
        for key in sorted(_template.keys(include_nested=True, leaves_only=True)):
            shape = _template[key].shape[1:]  # drop batch dim
            numel = max(shape.numel(), 1)
            # Use init values where available, else zeros
            init_v = _init_template.get(key, None)
            if init_v is not None and not (init_v == 0).all().item():
                self._init_state_values[total_numel] = init_v.flatten()[0].item()
            self._state_leaf_shapes.append((key, shape, numel))
            total_numel += numel

        self._half_state_size = (total_numel + 1) // 2
        self.hidden_size = self._half_state_size
        self._total_state_size = total_numel

        # Actor-critic heads — identical to LSTMPolicyNet
        # When VIBE_ACTIONS=1 (Phase 2 R24), use transport action space:
        #   Discrete(N_primary + N_primary * N_vibe)
        # For machina_1/arena: 5 + 5*7 = 40
        num_primary = len(policy_env_info.action_names)
        num_vibe = len(policy_env_info.vibe_action_names)
        if os.environ.get("VIBE_ACTIONS", "") == "1" and num_vibe > 0:
            num_actions = num_primary + num_primary * num_vibe  # transport space
            print(f"[CORTEX] Transport action head: {num_actions} "
                  f"({num_primary} primary x {num_vibe} vibes + {num_primary} no-vibe)")
        else:
            num_actions = num_primary
        self._num_actions = num_actions
        self._action_head = nn.Linear(d_hidden, num_actions)
        self._value_head = nn.Linear(d_hidden, 1)

    # ------------------------------------------------------------------
    # State packing: Cortex TensorDict <-> PufferLib flat buffers
    # ------------------------------------------------------------------

    def _pack_state(self, cortex_state, state):
        """Pack Cortex TensorDict into PufferLib state dict (in-place)."""
        if state is None:
            return
        flat = self._tensordict_to_flat(cortex_state)
        padded = torch.zeros(
            flat.shape[0], self._half_state_size * 2,
            device=flat.device, dtype=flat.dtype,
        )
        padded[:, :flat.shape[1]] = flat
        state["lstm_h"] = padded[:, :self._half_state_size]
        state["lstm_c"] = padded[:, self._half_state_size:]

    def _unpack_state(self, state, batch_size):
        """Unpack PufferLib state dict into Cortex TensorDict + reset mask."""
        if state is None:
            return None, None
        h = state.get("lstm_h")
        c = state.get("lstm_c")
        if h is None or c is None:
            return None, None

        flat = torch.cat(
            [h.reshape(batch_size, -1), c.reshape(batch_size, -1)], dim=-1,
        )
        flat = flat[:, :self._total_state_size]

        # Detect reset rows and restore non-zero init values
        resets = None
        zero_rows = (flat == 0).all(dim=-1)
        if zero_rows.any():
            resets = zero_rows
            if self._init_state_values:
                for offset, init_val in self._init_state_values.items():
                    flat[zero_rows, offset] = init_val

        return self._flat_to_tensordict(flat, batch_size), resets

    def _tensordict_to_flat(self, td):
        leaves = []
        for key in sorted(td.keys(include_nested=True, leaves_only=True)):
            v = td[key]
            if v.dim() == 1:
                leaves.append(v.unsqueeze(-1))
            else:
                leaves.append(v.reshape(v.shape[0], -1))
        return torch.cat(leaves, dim=-1)

    def _flat_to_tensordict(self, flat, batch_size):
        td = self._cortex.init_state(
            batch=batch_size, device=flat.device, dtype=flat.dtype,
        )
        offset = 0
        for key, shape, numel in self._state_leaf_shapes:
            chunk = flat[:, offset:offset + numel]
            if shape.numel() == 0:
                td[key] = chunk.squeeze(-1)
            else:
                td[key] = chunk.reshape(batch_size, *shape)
            offset += numel
        return td

    # ------------------------------------------------------------------
    # Forward — matches LSTMPolicyNet flow exactly
    # ------------------------------------------------------------------

    def forward(self, observations, state=None):
        orig_shape = observations.shape

        # Detect BPTT dimension
        obs_size = self._net[0].in_features
        total_elements = observations.numel()
        batch_size = orig_shape[0]

        if total_elements // batch_size != obs_size:
            bptt_horizon = total_elements // (batch_size * obs_size)
            segments = batch_size
            observations = observations.reshape(
                segments * bptt_horizon, obs_size,
            ).float()
        else:
            segments = batch_size
            bptt_horizon = 1
            observations = observations.reshape(segments, obs_size).float()

        # Normalize (matching LSTMPolicyNet)
        if observations.max() > 1.0:
            observations = observations / 255.0

        # Encoder (identical to LSTMPolicyNet)
        hidden = self._net(observations)
        hidden = rearrange(hidden, "(b t) h -> b t h", t=bptt_horizon, b=segments)

        # Cortex forward (replaces nn.LSTM)
        cortex_state, resets = self._unpack_state(state, segments)
        # Resets should only apply at t=0 (start of BPTT window), NOT all
        # timesteps. Broadcasting [B] -> [B,T] with expand() would reset at
        # every timestep, killing temporal propagation entirely.
        if resets is not None:
            resets_2d = torch.zeros(
                segments, bptt_horizon, dtype=torch.bool,
                device=hidden.device,
            )
            resets_2d[:, 0] = resets  # Only reset first timestep
            resets = resets_2d
        hidden, new_cortex_state = self._cortex(
            hidden, cortex_state, resets=resets,
        )

        # Pack state back
        self._pack_state(new_cortex_state, state)

        # Heads (identical to LSTMPolicyNet)
        hidden = rearrange(hidden, "b t h -> (b t) h")
        return self._action_head(hidden), self._value_head(hidden)

    def forward_eval(self, observations, state=None):
        return self.forward(observations, state)

    def gradient_norms(self):
        """Per-component gradient L2 norms for monitoring."""
        norms = {}
        groups = {
            "encoder": [self._net],
            "cortex": [self._cortex],
            "action_head": [self._action_head],
            "value_head": [self._value_head],
        }
        for name, modules in groups.items():
            total_sq = 0.0
            count = 0
            for mod in modules:
                for p in mod.parameters():
                    if p.grad is not None:
                        total_sq += p.grad.data.norm(2).item() ** 2
                        count += 1
            norms[name] = total_sq ** 0.5 if count > 0 else 0.0

        for i, scaffold in enumerate(self._cortex.scaffolds):
            sq = 0.0
            count = 0
            for p in scaffold.parameters():
                if p.grad is not None:
                    sq += p.grad.data.norm(2).item() ** 2
                    count += 1
            norms[f"cortex_layer{i}"] = sq ** 0.5 if count > 0 else 0.0
        return norms


class CortexPolicy(MultiAgentPolicy):
    """Cortex policy — drop-in replacement for LSTMPolicy."""

    short_names = ["cortex"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        d_hidden: int = 128,
        num_layers: int = 1,
        preset: str = "lstm",
        **kwargs,
    ):
        super().__init__(policy_env_info, device=device, **kwargs)
        self._device = torch.device(device)
        self._policy_env_info = policy_env_info
        self._net = CortexPolicyNet(
            policy_env_info,
            d_hidden=d_hidden,
            num_layers=num_layers,
            preset=preset,
        ).to(self._device)

    def network(self):
        return self._net

    def agent_policy(self, agent_id):
        raise NotImplementedError(
            "Single-agent inference not yet implemented for CortexPolicy."
        )

    def is_recurrent(self):
        return True

    def load_policy_data(self, path):
        self._net.load_state_dict(
            torch.load(path, map_location=self._device, weights_only=True)
        )


class CortexAxonPolicy(CortexPolicy):
    """Cortex with Axon (RTRL) cell."""

    short_names = ["cortex_axon"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="axon", **kwargs)


class CortexSLSTMPolicy(CortexPolicy):
    """Cortex with sLSTM (stabilized gating) cell."""

    short_names = ["cortex_slstm"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="slstm", **kwargs)


class CortexMLSTMPolicy(CortexPolicy):
    """Cortex with mLSTM (multiplicative) cell."""

    short_names = ["cortex_mlstm"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="mlstm", **kwargs)


class CortexAGaLiTePolicy(CortexPolicy):
    """Cortex with AGaLiTe (attention-based) cell."""

    short_names = ["cortex_agalite"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="agalite", **kwargs)


class CortexXLPolicy(CortexPolicy):
    """Cortex with XL (extended recurrent) cell."""

    short_names = ["cortex_xl"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="xl", **kwargs)


class CortexConv1dPolicy(CortexPolicy):
    """Cortex with CausalConv1d (no recurrence baseline)."""

    short_names = ["cortex_conv1d"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="conv1d", **kwargs)


class CortexSLSTMAxonPolicy(CortexPolicy):
    """Cortex with sLSTM axonified (sLSTM + RTRL)."""

    short_names = ["cortex_slstm_axon"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="slstm_axon", **kwargs)


class CortexMLSTMAxonPolicy(CortexPolicy):
    """Cortex with mLSTM axonified (mLSTM + RTRL)."""

    short_names = ["cortex_mlstm_axon"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="mlstm_axon", **kwargs)


class CortexLSTM2Policy(CortexPolicy):
    """Cortex with 2 LSTM layers."""

    short_names = ["cortex_lstm2"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="lstm2", **kwargs)


class CortexLSPolicy(CortexPolicy):
    """Cortex with LSTM + sLSTM routed Column."""

    short_names = ["cortex_ls"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="ls", **kwargs)


class CortexLSSeqPolicy(CortexPolicy):
    """Cortex with LSTM → sLSTM sequential."""

    short_names = ["cortex_ls_seq"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="ls_seq", **kwargs)


class CortexAgasPolicy(CortexPolicy):
    """Cortex with AGaLiTe + Axon + sLSTM (Ag,A,S) stack."""

    short_names = ["cortex_agas"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="agas", **kwargs)

    def save_policy_data(self, path):
        torch.save(self._net.state_dict(), path)


class CortexAgasSeqPolicy(CortexPolicy):
    """Cortex with AGaLiTe → Axon → sLSTM as 3 sequential layers (no router)."""

    short_names = ["cortex_agas_seq"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="agas_seq", **kwargs)


class CortexAgasSeq64Policy(CortexPolicy):
    """Ag,A,S sequential with d_hidden=64 (~300K params, matching LSTM scale)."""

    short_names = ["cortex_agas_seq_64"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="agas_seq", d_hidden=64, **kwargs)


class CortexAxon64Policy(CortexPolicy):
    """Axon-only with d_hidden=64 — tests RTRL in isolation at LSTM param scale."""

    short_names = ["cortex_axon_64"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="axon", d_hidden=64, **kwargs)


class Cortex64Policy(CortexPolicy):
    """LSTM via Cortex with d_hidden=64 — reduced param count control."""

    short_names = ["cortex_64"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, preset="lstm", d_hidden=64, **kwargs)


class SeparateACLSTMPolicy(MultiAgentPolicy):
    """Separate actor/critic LSTM policy — no shared features (Subhojeet suggestion).

    Two independent LSTM backbones prevent critic from degrading actor representations.
    Doubles parameter count (~450K vs ~226K) and recurrent state (512 vs 256 per agent).
    """

    short_names = ["separate_ac"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device, **kwargs)
        self._device = torch.device(device)
        self._policy_env_info = policy_env_info
        self._net = SeparateACPolicyNet(policy_env_info).to(self._device)

    def network(self):
        return self._net

    def agent_policy(self, agent_id):
        raise NotImplementedError(
            "Single-agent inference not yet implemented for SeparateACLSTMPolicy."
        )

    def is_recurrent(self):
        return True

    def load_policy_data(self, path):
        self._net.load_state_dict(
            torch.load(path, map_location=self._device, weights_only=True)
        )
