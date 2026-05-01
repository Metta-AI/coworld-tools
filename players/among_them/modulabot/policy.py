"""Cogames ``MultiAgentPolicy`` wrapper for modulabot.

This is the class the cogames BitWorld tournament loader instantiates.
It owns one :class:`~modulabot.bot.BotCore` per controlled agent and
forwards :meth:`step_batch` calls through them.

Ship command::

    cogames ship \\
      -p class=modulabot.policy.AmongThemPolicy \\
      -f among_them/modulabot \\
      -n "$USER-modulabot-py" \\
      --season among-them
"""

from __future__ import annotations

import numpy as np

try:
    from mettagrid.bitworld import BITWORLD_ACTION_NAMES, bitworld_action_name
    from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
    from mettagrid.policy.policy_env_interface import PolicyEnvInterface
    from mettagrid.simulator import Action, AgentObservation

    _MODULES_AVAILABLE = True
except ImportError:  # pragma: no cover — hit only in stripped envs
    _MODULES_AVAILABLE = False

    # Stub types so imports succeed during unit testing without mettagrid.
    BITWORLD_ACTION_NAMES = tuple(str(i) for i in range(27))

    def bitworld_action_name(i):
        return BITWORLD_ACTION_NAMES[i]

    class AgentPolicy:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...

    class MultiAgentPolicy:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...

    class PolicyEnvInterface: ...  # type: ignore[no-redef]

    class Action:  # type: ignore[no-redef]
        def __init__(self, name="", talk=None):
            self.name = name
            self.talk = talk

    class AgentObservation: ...  # type: ignore[no-redef]

from .bot import BotCore
from .data import ReferenceData, load_reference_data
from .localize import Localizer
from .trace import TraceLevel, TraceWriter, from_env as trace_from_env

# Touch the Nim perception library at policy-import time so the build (if
# any) happens *before* the cogames runner starts streaming frames, not
# inside the hot loop. Silent on failure — the kernels fall back to
# pure-Python and modulabot still works, just slower. Set
# ``MODULABOT_DISABLE_NATIVE=1`` to skip the load entirely.
from . import nim_perception as _nim_perception  # noqa: F401


class _ModulabotAgentPolicy(AgentPolicy):
    """One per controlled agent; sequences through the shared policy."""

    def __init__(self, policy_env_info, parent: "AmongThemPolicy", agent_id: int):
        super().__init__(policy_env_info)
        self._parent = parent
        self._agent_id = agent_id

    def step(self, obs):
        del obs  # AmongThemPolicy.step_batch populates actions; .step is unused
        action_index = self._parent.last_action(self._agent_id)
        talk = self._parent.last_chat(self._agent_id)
        return Action(
            name=bitworld_action_name(action_index),
            talk=talk,
        )


class AmongThemPolicy(MultiAgentPolicy):
    """Modulabot-in-Python: modular, pluggable, ready to iterate.

    v0 behaviour mirrors the Nim modulabot's decision structure (crewmate
    task play, imposter follow-and-fake-task, evidence-based voting).
    Extensibility is the point: swap policies by subclassing and overriding
    ``_build_core``, or drop in an LLM chat composer via :mod:`modulabot.
    chat`.

    Parameters
    ----------
    policy_env_info:
        Standard cogames policy env interface. Validated for the BitWorld
        27-action space at construction.
    device:
        Ignored; this is a pure-Python scripted policy. Kept for API
        compatibility with neural policies.
    seed:
        RNG seed used to derive each agent's :class:`random.Random` stream.
        Different seeds produce different fake-task rolls and followee
        swaps but otherwise identical behaviour.
    reference_data:
        Optional :class:`~modulabot.data.ReferenceData` bundle
        (sprites, font, game map). Defaults to
        :func:`~modulabot.data.load_reference_data` on first use —
        override only when the shipped data dir isn't usable (e.g. a
        stripped test environment, or to inject synthetic assets for
        unit tests). When ``None`` *and* the default data dir is
        missing, the policy falls back to the legacy state-obs
        dispatcher, which is the right behaviour for purely
        structured-observation harnesses.
    trace_dir, trace_level, trace_meta:
        Optional trace configuration. When ``trace_dir`` is set (either
        directly or via the ``MODULABOT_TRACE_DIR`` environment variable),
        a :class:`~modulabot.trace.TraceWriter` is attached to every
        per-agent :class:`BotCore` and a JSONL session trace is emitted
        under ``<trace_dir>/modulabot/<session_id>/``. Explicit kwargs
        override environment variables. See :mod:`modulabot.trace` for the
        full schema and configuration surface.
    trace_writer:
        Advanced: supply a pre-built :class:`TraceWriter` directly. Takes
        precedence over the ``trace_*`` kwargs and environment variables.
        Useful for tests and for multi-policy harnesses that want to share
        a single writer across multiple policies.
    """

    short_names = ["modulabot_py", "modulabot"]

    def __init__(
        self,
        policy_env_info,
        device: str = "cpu",
        *,
        seed: int = 0,
        reference_data: "ReferenceData | None" = None,
        trace_dir: "str | None" = None,
        trace_level: "str | int | TraceLevel | None" = None,
        trace_meta: "dict | str | None" = None,
        trace_writer: "TraceWriter | None" = None,
    ):
        super().__init__(policy_env_info, device=device)
        if _MODULES_AVAILABLE and tuple(policy_env_info.action_names) != BITWORLD_ACTION_NAMES:
            raise ValueError(
                f"Modulabot requires the BitWorld AmongThem action space ({len(BITWORLD_ACTION_NAMES)} actions)"
            )
        self._seed = int(seed)
        self._cores: dict[int, BotCore] = {}
        self._last_actions: dict[int, int] = {}
        self._last_chats: dict[int, str] = {}

        # Load reference data once and share across every per-agent
        # BotCore. Callers may inject a pre-built bundle for tests.
        # Construction pulls the patch-hash localization index
        # (~130 ms); doing it once at policy init is strictly better
        # than paying that cost inside the first step_batch call.
        if reference_data is None:
            try:
                reference_data = load_reference_data()
            except FileNotFoundError:
                # No data dir shipped (e.g. stripped test environments).
                # Fall back to the legacy state-obs dispatcher.
                reference_data = None
        self._reference_data = reference_data
        self._localizer: Localizer | None = (
            Localizer(reference_data.map) if reference_data is not None else None
        )

        # Trace writer: explicit arg wins over kwargs wins over env vars.
        if trace_writer is not None:
            self._trace = trace_writer
            self._owns_trace = False
        else:
            self._trace = trace_from_env(
                trace_dir=trace_dir,
                trace_level=trace_level,
                trace_meta=trace_meta,
            )
            self._owns_trace = self._trace is not None

    # ------------------------------------------------------------------
    # Contract: cogames calls step_batch() with a batch of observations.
    # ------------------------------------------------------------------

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        batch_size = raw_observations.shape[0]
        self._last_chats.clear()
        for agent_id in range(batch_size):
            core = self._core(agent_id)
            action = core.step(raw_observations[agent_id])
            raw_actions[agent_id] = action
            self._last_actions[agent_id] = action
            chat_text = core.take_chat()
            if chat_text:
                self._last_chats[agent_id] = chat_text
                if self._trace is not None:
                    # core.step has already advanced bot.tick; the chat
                    # was queued on the frame we just recorded, so log
                    # against the frame's tick (bot.tick - 1).
                    self._trace.record_chat_sent(
                        agent_id, chat_text, tick=max(0, core.bot.tick - 1)
                    )

    # ------------------------------------------------------------------
    # Contract: cogames asks for one AgentPolicy per agent.
    # ------------------------------------------------------------------

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        # Make sure core exists so last_action / last_chat are always valid.
        self._core(agent_id)
        return _ModulabotAgentPolicy(self._policy_env_info, self, agent_id)

    # ------------------------------------------------------------------
    # Lookup helpers for the per-agent policy.
    # ------------------------------------------------------------------

    def last_action(self, agent_id: int) -> int:
        return int(self._last_actions.get(agent_id, 0))

    def last_chat(self, agent_id: int) -> str | None:
        return self._last_chats.get(agent_id)

    def bitworld_chat_messages(self, agent_ids):
        """Cogames-compatible chat fetch used by some BitWorld integrations."""
        return [self._last_chats.get(int(a)) for a in agent_ids]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _core(self, agent_id: int) -> BotCore:
        core = self._cores.get(agent_id)
        if core is None:
            core = BotCore(
                agent_id=agent_id,
                rng_seed=self._seed,
                reference_data=self._reference_data,
                localizer=self._localizer,
                trace_writer=self._trace,
            )
            self._cores[agent_id] = core
        return core

    # ------------------------------------------------------------------
    # Hook for subclasses who want to swap in custom policies / perception.
    # ------------------------------------------------------------------

    def _build_core(self, agent_id: int) -> BotCore:  # pragma: no cover
        """Override to supply a customized :class:`BotCore`.

        Default implementation instantiates the standard ``BotCore``. Unused
        by the v0 path but reserved so downstream tunings can experiment
        without forking :meth:`step_batch`.
        """
        return BotCore(
            agent_id=agent_id,
            rng_seed=self._seed,
            reference_data=self._reference_data,
            localizer=self._localizer,
            trace_writer=self._trace,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self, *, reason: str = "session_end") -> None:
        """Finalise the attached trace (if any).

        Safe to call multiple times. Only closes the trace writer when
        this policy constructed it; externally-supplied writers are
        left alone so a multi-policy harness can reuse them.
        """
        if self._trace is not None and self._owns_trace:
            self._trace.close(reason=reason)

    def __del__(self) -> None:  # pragma: no cover — best-effort finaliser
        # Best-effort so a script that exits without calling close() still
        # gets a flushed manifest. Exceptions in __del__ are silently
        # dropped by the runtime, which matches our non-perturbation stance.
        try:
            self.close(reason="process_exit")
        except Exception:
            pass


__all__ = ["AmongThemPolicy"]
