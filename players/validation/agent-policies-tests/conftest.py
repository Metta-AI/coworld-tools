"""Shared fixtures and import mocking for agent-policies tests.

The installed mettagrid 0.2.0.58 has a circular import in
mettagrid.simulator that prevents normal imports.  This conftest
patches the problematic module before any test module triggers
the import chain.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from unittest.mock import MagicMock


def _ensure_mettagrid_mock() -> None:
    """Ensure mettagrid.simulator is importable even when the real package
    has circular-import issues.  Only patches if the real import fails."""
    try:
        from mettagrid.simulator import Action  # noqa: F401, PLC0415

        return  # real import works, nothing to do
    except (ImportError, AttributeError):
        pass

    # Build a lightweight stub for mettagrid.simulator
    sim_mod = types.ModuleType("mettagrid.simulator")

    @dataclass
    class _Action:
        name: str = "noop"
        arg: int = 0

    @dataclass
    class _AgentObservation:
        grid: object = None
        inventory: object = None

    @dataclass
    class _ObservationToken:
        name: str = ""
        value: int = 0

    sim_mod.Action = _Action  # type: ignore[attr-defined]
    sim_mod.AgentObservation = _AgentObservation  # type: ignore[attr-defined]
    sim_mod.ObservationToken = _ObservationToken  # type: ignore[attr-defined]
    sim_mod.Simulation = MagicMock  # type: ignore[attr-defined]

    # Stub all sub-modules that the real import chain might pull in.
    # Every name here becomes an auto-attribute MagicMock module.
    _stub_names = [
        "mettagrid.config",
        "mettagrid.config.mettagrid_c_config",
        "mettagrid.config.mettagrid_config",
        "mettagrid.config.id_map",
        "mettagrid.mettagrid_c",
        "mettagrid.config.action_config",
        "mettagrid.simulator.interface",
        "mettagrid.simulator.replay_log_writer",
        "mettagrid.simulator.simulator",
        "mettagrid.policy",
        "mettagrid.policy.policy",
        "mettagrid.policy.policy_env_interface",
    ]
    for mod_name in _stub_names:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()

    # The simulator module itself needs the proper Action dataclass
    sys.modules["mettagrid.simulator"] = sim_mod

    # Ensure mettagrid.simulator.interface also has AgentObservation
    iface_mod = sys.modules["mettagrid.simulator.interface"]
    iface_mod.AgentObservation = _AgentObservation

    # Ensure mettagrid.policy.policy has needed base classes
    # StatefulPolicyImpl must be subscriptable (used as StatefulPolicyImpl[T])
    class _SubscriptableMeta(type):
        def __getitem__(cls, item):
            return cls

    class _MultiAgentPolicy:
        pass

    class _StatefulPolicyImpl(metaclass=_SubscriptableMeta):
        pass

    class _StatefulAgentPolicy:
        pass

    policy_mod = sys.modules["mettagrid.policy.policy"]
    policy_mod.MultiAgentPolicy = _MultiAgentPolicy
    policy_mod.StatefulPolicyImpl = _StatefulPolicyImpl
    policy_mod.StatefulAgentPolicy = _StatefulAgentPolicy


def _ensure_cogames_stubs() -> None:
    """Ensure cogames submodules are importable."""
    try:
        from cogsguard.stations import GEAR_COSTS  # noqa: F401, PLC0415
    except (ImportError, AttributeError):
        cvc_mod = sys.modules.get("cogsguard.stations")
        if cvc_mod is None:
            cvc_mod = types.ModuleType("cogsguard.stations")
            sys.modules["cogsguard.stations"] = cvc_mod
        if not hasattr(cvc_mod, "GEAR_COSTS"):
            # Values are dicts mapping resource name -> cost
            cvc_mod.GEAR_COSTS = {  # type: ignore[attr-defined]
                "miner": {"ore": 1},
                "scout": {"compass": 1},
                "aligner": {"wrench": 1},
                "scrambler": {"bomb": 1},
            }


# Run at conftest load time, before any test collection
_ensure_mettagrid_mock()
_ensure_cogames_stubs()
