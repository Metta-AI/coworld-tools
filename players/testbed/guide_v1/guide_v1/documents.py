from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentSpec:
    name: str
    filename: str
    prompt_template: str
    dependencies: tuple[str, ...]
    stage: int
    description: str

    @property
    def slug(self) -> str:
        return self.name.lower().replace("_", "-")


_STAGE_1_TO_5: tuple[DocumentSpec, ...] = (
    DocumentSpec(
        name="GAME_OVERVIEW",
        filename="GAME_OVERVIEW.md",
        prompt_template="doc_game_overview.md",
        dependencies=(),
        stage=1,
        description="Game orientation, entities, vocabulary, and core loop",
    ),
    DocumentSpec(
        name="RULES_AND_MECHANICS",
        filename="RULES_AND_MECHANICS.md",
        prompt_template="doc_rules_and_mechanics.md",
        dependencies=("GAME_OVERVIEW",),
        stage=2,
        description="Formal logical rules, legality, scoring, and win conditions",
    ),
    DocumentSpec(
        name="INTERFACE_CONTRACT",
        filename="INTERFACE_CONTRACT.md",
        prompt_template="doc_interface_contract.md",
        dependencies=("GAME_OVERVIEW",),
        stage=2,
        description="Agent-game protocol, observations, actions, rewards, and timing",
    ),
    DocumentSpec(
        name="STATE_AND_VIEW_MODEL",
        filename="STATE_AND_VIEW_MODEL.md",
        prompt_template="doc_state_and_view_model.md",
        dependencies=("RULES_AND_MECHANICS",),
        stage=3,
        description="State graph, game phases, transitions, and view boundaries",
    ),
    DocumentSpec(
        name="CONNECTION_AND_EPISODE_LIFECYCLE",
        filename="CONNECTION_AND_EPISODE_LIFECYCLE.md",
        prompt_template="doc_connection_and_episode_lifecycle.md",
        dependencies=("INTERFACE_CONTRACT",),
        stage=3,
        description="Cold start, reset, shutdown, and episode lifecycle",
    ),
    DocumentSpec(
        name="TRAINING_AND_EVALUATION",
        filename="TRAINING_AND_EVALUATION.md",
        prompt_template="doc_training_and_evaluation.md",
        dependencies=("INTERFACE_CONTRACT",),
        stage=3,
        description="Training loops, determinism, parallelism, replay, and benchmarks",
    ),
    DocumentSpec(
        name="OBSERVATION_DECODING",
        filename="OBSERVATION_DECODING.md",
        prompt_template="doc_observation_decoding.md",
        dependencies=("INTERFACE_CONTRACT", "STATE_AND_VIEW_MODEL"),
        stage=4,
        description="Raw observations to semantic state interpretation",
    ),
    DocumentSpec(
        name="ACTION_SEMANTICS_AND_CONTROL",
        filename="ACTION_SEMANTICS_AND_CONTROL.md",
        prompt_template="doc_action_semantics_and_control.md",
        dependencies=("INTERFACE_CONTRACT", "STATE_AND_VIEW_MODEL"),
        stage=4,
        description="Action effects, legality, timing, and control semantics",
    ),
    DocumentSpec(
        name="MEMORY_AND_HIDDEN_INFORMATION",
        filename="MEMORY_AND_HIDDEN_INFORMATION.md",
        prompt_template="doc_memory_and_hidden_information.md",
        dependencies=("STATE_AND_VIEW_MODEL",),
        stage=4,
        description="Partial observability, hidden state, belief tracking, and memory",
    ),
    DocumentSpec(
        name="REWARDS_AND_PROGRESS_SIGNALS",
        filename="REWARDS_AND_PROGRESS_SIGNALS.md",
        prompt_template="doc_rewards_and_progress_signals.md",
        dependencies=("STATE_AND_VIEW_MODEL",),
        stage=4,
        description="Reward signals, shaping candidates, progress, and evaluation metrics",
    ),
    DocumentSpec(
        name="MINIMUM_VIABLE_AGENT",
        filename="MINIMUM_VIABLE_AGENT.md",
        prompt_template="doc_minimum_viable_agent.md",
        dependencies=("CONNECTION_AND_EPISODE_LIFECYCLE",),
        stage=4,
        description="Shortest path to a working baseline agent",
    ),
    DocumentSpec(
        name="ERROR_RECOVERY_AND_ROBUSTNESS",
        filename="ERROR_RECOVERY_AND_ROBUSTNESS.md",
        prompt_template="doc_error_recovery_and_robustness.md",
        dependencies=("INTERFACE_CONTRACT", "STATE_AND_VIEW_MODEL"),
        stage=5,
        description="Failure detection, recovery, stuck handling, and robustness",
    ),
    DocumentSpec(
        name="STRATEGY_AND_POLICY_GUIDE",
        filename="STRATEGY_AND_POLICY_GUIDE.md",
        prompt_template="doc_strategy_and_policy_guide.md",
        dependencies=("RULES_AND_MECHANICS", "STATE_AND_VIEW_MODEL"),
        stage=5,
        description="Heuristics, tactics, policy structure, and strategic implications",
    ),
)

_PRIOR_TO_IMPLEMENTATION = tuple(document.name for document in _STAGE_1_TO_5)

DOCUMENTS: tuple[DocumentSpec, ...] = (
    *_STAGE_1_TO_5,
    DocumentSpec(
        name="IMPLEMENTATION_NOTES",
        filename="IMPLEMENTATION_NOTES.md",
        prompt_template="doc_implementation_notes.md",
        dependencies=_PRIOR_TO_IMPLEMENTATION,
        stage=6,
        description="Source-code internals for debugging, validation, and extension",
    ),
    DocumentSpec(
        name="README",
        filename="README.md",
        prompt_template="doc_readme.md",
        dependencies=(*_PRIOR_TO_IMPLEMENTATION, "IMPLEMENTATION_NOTES"),
        stage=7,
        description="Guide map, reading order, MVP path, and document routing",
    ),
)

_BY_NAME = {document.name: document for document in DOCUMENTS}
_BY_SLUG = {document.slug: document for document in DOCUMENTS}


def all_documents() -> tuple[DocumentSpec, ...]:
    return DOCUMENTS


def documents_by_stage(
    documents: Iterable[DocumentSpec] | None = None,
) -> dict[int, list[DocumentSpec]]:
    grouped: dict[int, list[DocumentSpec]] = defaultdict(list)
    for document in DOCUMENTS if documents is None else documents:
        grouped[document.stage].append(document)
    return dict(sorted(grouped.items()))


def get_document(name_or_slug: str) -> DocumentSpec:
    normalized = name_or_slug.strip()
    document = _BY_NAME.get(normalized.upper().replace("-", "_"))
    if document is not None:
        return document

    document = _BY_SLUG.get(normalized.lower())
    if document is not None:
        return document

    raise KeyError(f"Unknown guide document: {name_or_slug}")


def validate_doc_slugs(slugs: Sequence[str]) -> list[str]:
    unknown = [slug for slug in slugs if slug.lower() not in _BY_SLUG]
    return unknown
