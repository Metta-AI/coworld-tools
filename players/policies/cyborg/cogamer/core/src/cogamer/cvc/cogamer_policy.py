"""CogamerPolicy: program-table-driven CvC policy.

Dispatches through a flat program table operating on GameState.
Each agent is fully independent — no shared state between agents.

Architecture:
  CvCPolicy (MultiAgentPolicy)
    └─ StatefulAgentPolicy[CvCAgentState]  (one per agent)
         └─ CvCPolicyImpl (StatefulPolicyImpl)
              └─ GameState (observation processing + mutable state)
              └─ Program table (step/heal/retreat/mine/align/scramble/explore)
              └─ LLM brain (periodic analysis via "analyze" program)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cogamer.cvc.game_state import GameState
from cogamer.cvc.programs import all_programs
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

try:
    from cogamer.cvc.llm_executor import LLMExecutor
    from cogamer.cvc.proglet import Program
except ImportError:
    LLMExecutor = None  # type: ignore[assignment,misc]
    Program = None  # type: ignore[assignment,misc]

_LLM_INTERVAL = 500
_LOG_INTERVAL = 500
_LEARNINGS_DIR = os.environ.get("COGLET_LEARNINGS_DIR", "/tmp/coglet_learnings")


@dataclass
class CvCAgentState:
    """All mutable state for one agent."""

    game_state: GameState | None = None
    last_llm_step: int = 0
    llm_interval: int = _LLM_INTERVAL
    llm_latencies: list[float] = field(default_factory=list)
    resource_bias_from_llm: str | None = None
    llm_log: list[dict[str, Any]] = field(default_factory=list)
    snapshot_log: list[dict[str, Any]] = field(default_factory=list)
    last_snapshot_step: int = 0
    experience: list[dict] = field(default_factory=list)


class CvCPolicyImpl(StatefulPolicyImpl[CvCAgentState]):
    """Per-agent decision logic using the program table."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        programs: dict[str, Program],
        llm_executor: LLMExecutor | None = None,
        game_id: str = "",
        shared_junctions: dict[tuple[int, int], tuple[str | None, int]] | None = None,
        shared_claims: dict[tuple[int, int], tuple[int, int]] | None = None,
    ) -> None:
        self._policy_env_info = policy_env_info
        self._agent_id = agent_id
        self._programs = programs
        self._llm_executor = llm_executor
        self._game_id = game_id
        self._shared_junctions = shared_junctions
        self._shared_claims = shared_claims

    def initial_agent_state(self) -> CvCAgentState:
        gs = GameState(
            self._policy_env_info,
            agent_id=self._agent_id,
            shared_junctions=self._shared_junctions,
            shared_claims=self._shared_claims,
        )
        return CvCAgentState(game_state=gs)

    def _invoke_sync(self, name: str, *args: Any) -> Any:
        """Synchronous program invocation for code programs."""
        prog = self._programs[name]
        if prog.executor == "code" and prog.fn is not None:
            return prog.fn(*args)
        raise ValueError(f"Cannot sync-invoke {name} (executor={prog.executor})")

    def step_with_state(self, obs: AgentObservation, state: CvCAgentState) -> tuple[Action, CvCAgentState]:
        gs = state.game_state
        assert gs is not None

        # 1. Process observation — builds MettagridState, updates world model
        gs.process_obs(obs)

        # 2. Determine role via desired_role program
        gs.role = self._invoke_sync("desired_role", gs)

        # 3. Invoke main dispatch program (returns (Action, summary))
        action, summary = self._invoke_sync("step", gs)

        # 4. Finalize — record navigation observation, bookkeep
        gs.finalize_step(summary)

        step = gs.step_index

        # 5. Periodic LLM analysis
        if self._llm_executor is not None and step - state.last_llm_step >= state.llm_interval:
            state.last_llm_step = step
            self._llm_analyze(gs, state)
            self._adapt_interval(state)

        # 6. Periodic snapshots (experience collection)
        if step - state.last_snapshot_step >= _LOG_INTERVAL:
            state.last_snapshot_step = step
            summary_dict = self._invoke_sync("summarize", gs)
            if summary_dict:
                state.experience.append(summary_dict)
                state.snapshot_log.append(summary_dict)

        return action, state

    def _llm_analyze(
        self,
        gs: GameState,
        state: CvCAgentState,
    ) -> None:
        """Run the analyze LLM program via the program table."""
        try:
            summary = self._invoke_sync("summarize", gs)
            prog = self._programs.get("analyze")
            if prog is None or prog.executor != "llm":
                return

            prompt = prog.system(summary) if callable(prog.system) else str(prog.system)
            cfg = prog.config

            t0 = time.perf_counter()
            response = self._llm_executor.client.messages.create(
                model=cfg.get("model", "claude-sonnet-4-20250514"),
                max_tokens=cfg.get("max_tokens", 150),
                temperature=cfg.get("temperature", 0.2),
                messages=[{"role": "user", "content": prompt}],
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            text = self._llm_executor._extract_text(response)
            parsed = prog.parser(text) if prog.parser else {"analysis": text}

            if "resource_bias" in parsed:
                state.resource_bias_from_llm = parsed["resource_bias"]
                gs.resource_bias = parsed["resource_bias"]

            # Apply role override from LLM
            if "role" in parsed:
                gs.role = parsed["role"]

            # Apply objective to engine directive
            if "objective" in parsed and hasattr(gs.engine, "_llm_objective"):
                gs.engine._llm_objective = parsed["objective"]

            state.llm_latencies.append(latency_ms)
            state.llm_log.append(
                {
                    "step": gs.step_index,
                    "agent": self._agent_id,
                    "latency_ms": round(latency_ms),
                    "analysis": parsed.get("analysis", ""),
                    "resource_bias": state.resource_bias_from_llm,
                    "role_override": parsed.get("role"),
                    "objective": parsed.get("objective"),
                }
            )
            print(
                f"[table] a{self._agent_id} step={gs.step_index} "
                f"llm={latency_ms:.0f}ms interval={state.llm_interval}: "
                f"{parsed.get('analysis', '')[:100]}",
                flush=True,
            )
        except Exception as e:
            state.llm_log.append(
                {
                    "step": gs.step_index,
                    "agent": self._agent_id,
                    "error": str(e),
                }
            )

    def _adapt_interval(self, state: CvCAgentState) -> None:
        """Adjust LLM call frequency based on latency."""
        if not state.llm_latencies:
            return
        recent = state.llm_latencies[-5:]
        avg_ms = sum(recent) / len(recent)
        if avg_ms < 2000:
            state.llm_interval = max(200, state.llm_interval - 50)
        elif avg_ms > 5000:
            state.llm_interval = min(1000, state.llm_interval + 100)


class CvCPolicy(MultiAgentPolicy):
    """Top-level CvC policy backed by a mutable program table.

    Dispatches through the program table instead of hard-coded
    CvcEngine._choose_action.
    """

    short_names = ["cvc", "cvc-policy"]
    minimum_action_timeout_ms = 30_000

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        programs: dict[str, Program] | None = None,
        **kwargs: Any,
    ):
        super().__init__(policy_env_info, device=device, **kwargs)
        self._programs = programs or all_programs()
        self._agent_policies: dict[int, StatefulAgentPolicy[CvCAgentState]] = {}
        self._llm_executor: LLMExecutor | None = None
        self._episode_start = time.time()
        self._game_id = kwargs.get("game_id", f"game_{int(time.time())}")
        # Shared junction memory and claims across all agents in this policy
        self._shared_junctions: dict[tuple[int, int], tuple[str | None, int]] = {}
        self._shared_claims: dict[tuple[int, int], tuple[int, int]] = {}
        self._init_llm()

        import atexit

        atexit.register(self._write_learnings)

    def _init_llm(self) -> None:
        if LLMExecutor is None:
            return
        api_key = os.environ.get("COGORA_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return
        try:
            import anthropic

            self._llm_executor = LLMExecutor(anthropic.Anthropic(api_key=api_key))
        except ImportError:
            pass

    @property
    def programs(self) -> dict[str, Program]:
        return self._programs

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[CvCAgentState]:
        if agent_id not in self._agent_policies:
            impl = CvCPolicyImpl(
                self._policy_env_info,
                agent_id,
                programs=self._programs,
                llm_executor=self._llm_executor,
                game_id=self._game_id,
                shared_junctions=self._shared_junctions,
                shared_claims=self._shared_claims,
            )
            self._agent_policies[agent_id] = StatefulAgentPolicy(
                impl,
                self._policy_env_info,
                agent_id=agent_id,
            )
        return self._agent_policies[agent_id]

    def collect_experience(self) -> list[dict]:
        """Collect experience from all agents."""
        all_exp: list[dict] = []
        for _aid, wrapper in self._agent_policies.items():
            st: CvCAgentState | None = getattr(wrapper, "_state", None)
            if st:
                all_exp.extend(st.experience)
        return sorted(all_exp, key=lambda x: x.get("step", 0))

    def reset(self) -> None:
        if self._agent_policies:
            self._write_learnings()
        self._episode_start = time.time()
        for p in self._agent_policies.values():
            p.reset()

    def _write_learnings(self) -> None:
        learnings_dir = Path(_LEARNINGS_DIR)
        learnings_dir.mkdir(parents=True, exist_ok=True)

        agents_data: dict[str, Any] = {}
        all_llm: list[dict] = []
        all_snaps: list[dict] = []

        for aid, wrapper in self._agent_policies.items():
            st: CvCAgentState | None = getattr(wrapper, "_state", None)
            if st is None:
                continue
            gs = st.game_state
            agents_data[str(aid)] = {
                "steps": gs.step_index if gs else 0,
            }
            all_llm.extend(st.llm_log)
            all_snaps.extend(st.snapshot_log)

        learnings = {
            "game_id": self._game_id,
            "duration_s": round(time.time() - self._episode_start, 1),
            "agents": agents_data,
            "llm_log": sorted(all_llm, key=lambda x: (x.get("step", 0), x.get("agent", 0))),
            "snapshots": sorted(all_snaps, key=lambda x: (x.get("step", 0), x.get("agent", 0))),
        }

        path = learnings_dir / f"{self._game_id}.json"
        path.write_text(json.dumps(learnings, indent=2, default=str))
