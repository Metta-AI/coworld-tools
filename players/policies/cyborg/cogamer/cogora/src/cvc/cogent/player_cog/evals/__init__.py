from __future__ import annotations

import importlib

__all__ = [
    "BehavioralScenario",
    "InterviewProbeAnswer",
    "InterviewProbeRequest",
    "ProbeQuestion",
    "ScenarioResult",
    "ScenarioStepResult",
    "SemanticPolicyDecision",
    "SemanticPolicyEvaluationHarness",
]

_EXPORTS = {
    "BehavioralScenario": ("cog_cognition.evals", "SemanticBehavioralScenario"),
    "InterviewProbeAnswer": ("cog_cognition.evals", "SemanticInterviewProbeAnswer"),
    "InterviewProbeRequest": ("cog_cognition.evals", "SemanticInterviewProbeRequest"),
    "ProbeQuestion": ("cog_cognition.evals", "SemanticProbeQuestion"),
    "ScenarioResult": ("cog_cognition.evals", "SemanticScenarioResult"),
    "ScenarioStepResult": ("cog_cognition.evals", "SemanticScenarioStepResult"),
    "SemanticPolicyDecision": ("cog_cognition.evals", "SemanticPolicyDecision"),
    "SemanticPolicyEvaluationHarness": ("cog_cognition.evals", "SemanticPolicyEvaluationHarness"),
}


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, export_name = _EXPORTS[name]
    return getattr(importlib.import_module(module_name), export_name)
