from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .artifacts import write_json, write_text
from .decoder_spec import generate_decoder_artifacts
from .framework import (
    AgentFrameworkRef,
    FrameworkValidationError,
    build_agent_framework_ref,
    validate_agent_framework_ref,
)
from .guide_index import (
    ActionCandidate,
    ActionWireContract,
    GuideBundle,
    ObservationSurface,
    build_play_card,
    classify_observation_surface,
    extract_action_candidates,
    extract_runtime_notes,
    infer_action_wire_contract,
    load_guide_bundle,
)
from .symbolic_agent import generate_symbolic_agent
from .visual_agent import generate_visual_agent_shell
from .vlm.schema import VLM_FRAME_SCHEMA, VLM_REQUEST_SCHEMA


class MakerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MakerResult:
    guide_bundle: GuideBundle
    output_dir: Path
    manifest_file: Path
    plan_file: Path
    play_card_file: Path
    vlm_request_schema_file: Path
    vlm_schema_file: Path
    observation_surface: ObservationSurface
    action_candidates: tuple[ActionCandidate, ...]
    action_wire_contract: ActionWireContract
    agent_framework: AgentFrameworkRef
    decoder_files: tuple[Path, ...]
    agent_files: tuple[Path, ...]


def generate_plan(
    guide_dir: Path,
    *,
    output_dir: Path | None = None,
    game_source: Path | None = None,
    agent_framework: AgentFrameworkRef | None = None,
) -> MakerResult:
    bundle = load_guide_bundle(guide_dir)
    if not bundle.documents:
        raise MakerError(f"guide_dir contains no markdown guide documents: {bundle.guide_dir}")

    surface = classify_observation_surface(bundle)
    actions = extract_action_candidates(bundle)
    wire_contract = infer_action_wire_contract(bundle, actions)
    runtime_notes = extract_runtime_notes(bundle)
    play_card = build_play_card(bundle, surface, actions, runtime_notes)
    framework_ref = agent_framework or build_agent_framework_ref(bundle=bundle)
    if _requires_framework_runtime(surface.category):
        try:
            validate_agent_framework_ref(framework_ref)
        except FrameworkValidationError as exc:
            raise MakerError(f"invalid agent framework: {exc}") from exc

    output_path = _default_output_dir(bundle) if output_dir is None else output_dir.expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    manifest_file = output_path / "maker_manifest.json"
    plan_file = output_path / "AGENT_BUILD_PLAN.md"
    play_card_file = output_path / "visual_bootstrap" / "play_card.md"
    vlm_request_schema_file = output_path / "visual_bootstrap" / "vlm_request_schema.json"
    vlm_schema_file = output_path / "visual_bootstrap" / "vlm_schema.json"
    decoder_files = generate_decoder_artifacts(
        bundle=bundle,
        output_dir=output_path,
        surface=surface,
    )
    agent_files = _generate_agent_artifacts(
        bundle=bundle,
        output_dir=output_path,
        surface=surface,
        actions=actions,
        wire_contract=wire_contract,
        agent_framework=framework_ref,
    )

    manifest = _build_manifest(
        bundle=bundle,
        output_dir=output_path,
        game_source=game_source.expanduser().resolve() if game_source is not None else None,
        surface=surface,
        actions=actions,
        wire_contract=wire_contract,
        agent_framework=framework_ref,
        runtime_notes=runtime_notes,
        generated_files=(
            manifest_file,
            plan_file,
            play_card_file,
            vlm_request_schema_file,
            vlm_schema_file,
            *decoder_files,
            *agent_files,
        ),
    )

    write_json(manifest_file, manifest)
    write_text(
        plan_file,
        _render_plan(
            bundle,
            output_path,
            game_source,
            surface,
            actions,
            wire_contract,
            framework_ref,
            runtime_notes,
        ),
    )
    write_text(play_card_file, play_card)
    write_json(vlm_request_schema_file, VLM_REQUEST_SCHEMA)
    write_json(vlm_schema_file, VLM_FRAME_SCHEMA)

    return MakerResult(
        guide_bundle=bundle,
        output_dir=output_path,
        manifest_file=manifest_file,
        plan_file=plan_file,
        play_card_file=play_card_file,
        vlm_request_schema_file=vlm_request_schema_file,
        vlm_schema_file=vlm_schema_file,
        observation_surface=surface,
        action_candidates=actions,
        action_wire_contract=wire_contract,
        agent_framework=framework_ref,
        decoder_files=decoder_files,
        agent_files=agent_files,
    )


def _default_output_dir(bundle: GuideBundle) -> Path:
    return (Path("./output") / bundle.game_slug).resolve()


def _guide_contract_status(bundle: GuideBundle) -> str:
    if bundle.contract is None:
        return "not found; using markdown fallback extraction"
    schema = bundle.contract.get("schema_version", "unknown schema")
    return f"{schema} ({bundle.contract_hash})"


def _build_manifest(
    *,
    bundle: GuideBundle,
    output_dir: Path,
    game_source: Path | None,
    surface: ObservationSurface,
    actions: tuple[ActionCandidate, ...],
    wire_contract: ActionWireContract,
    agent_framework: AgentFrameworkRef,
    runtime_notes: tuple,
    generated_files: tuple[Path, ...],
) -> dict[str, object]:
    generated_symbolic_agent = surface.category == "symbolic_primary"
    generated_visual_shell = surface.category in {"visual_primary", "mixed_or_alternate"}
    return {
        "schema_version": "maker.manifest.v1",
        "maker_version": "maker_v1.phase4.decoder_impl_visual_bootstrap_policy_seed",
        "generated_at": datetime.now(UTC).isoformat(),
        "game_slug": bundle.game_slug,
        "guide_dir": str(bundle.guide_dir),
        "game_source": None if game_source is None else str(game_source),
        "output_dir": str(output_dir),
        "guide_bundle_hash": bundle.bundle_hash,
        "guide_contract_hash": bundle.contract_hash,
        "guide_contract_schema_version": None
        if bundle.contract is None
        else bundle.contract.get("schema_version"),
        "agent_framework": agent_framework.as_dict(),
        "documents_present": sorted(bundle.documents),
        "documents_missing": list(bundle.missing_documents),
        "observation_surface": surface.as_dict(),
        "candidate_actions": [action.as_dict() for action in actions],
        "action_wire_contract": wire_contract.as_dict(),
        "runtime_notes": [note.as_dict() for note in runtime_notes],
        "implemented_capabilities": [
            "guide_bundle_indexing",
            *(
                ["guide_contract_ingestion"]
                if bundle.contract is not None
                else ["markdown_contract_fallback"]
            ),
            "observation_surface_classification",
            "candidate_action_extraction",
            "agent_build_plan_generation",
            "cyborg_framework_handoff",
            "vlm_play_card_generation",
            "vlm_request_schema_export",
            "vlm_schema_export",
            "observation_decoder_spec_generation",
            "observation_decoder_impl_generation",
            "visual_bootstrap_frame_directory_labeling",
            "bedrock_vlm_provider_adapter",
            "label_derived_policy_bootstrap",
            "local_smoke_test_harness",
            *(
                [
                    "symbolic_agent_scaffold_generation",
                    "symbolic_cyborg_runtime_generation",
                    "symbolic_action_serialization_tests",
                ]
                if generated_symbolic_agent
                else []
            ),
            *(
                [
                    "visual_agent_shell_generation",
                    "visual_live_starter_agent_generation",
                    "visual_cyborg_runtime_generation",
                    "visual_action_protocol_generation",
                    "visual_frame_store_generation",
                    "visual_mock_vlm_client_generation",
                ]
                if generated_visual_shell
                else []
            ),
        ],
        "not_implemented": [
            "automatic_run_config_discovery",
            "automatic_visual_exploration",
            "additional_vlm_provider_adapters",
            "parser_generation",
            "policy_refinement_from_decoder_parser_fixtures",
            "cogames_submission_packaging",
            *(["unknown_surface_agent_scaffold"] if not generated_symbolic_agent and not generated_visual_shell else []),
        ],
        "generated_files": [str(path.relative_to(output_dir)) for path in generated_files],
    }


def _render_plan(
    bundle: GuideBundle,
    output_dir: Path,
    game_source: Path | None,
    surface: ObservationSurface,
    actions: tuple[ActionCandidate, ...],
    wire_contract: ActionWireContract,
    agent_framework: AgentFrameworkRef,
    runtime_notes: tuple,
) -> str:
    source_text = "not provided" if game_source is None else f"`{game_source.expanduser().resolve()}`"
    missing = "\n".join(f"- `{filename}`" for filename in bundle.missing_documents) or "- None"
    evidence = "\n".join(
        f"- `{item.document}:{item.line}`: {item.text}" for item in surface.evidence
    ) or "- No high-confidence evidence found."
    action_lines = "\n".join(
        f"- `{action.action_id}` from {action.source}" for action in actions[:40]
    ) or "- No candidate actions extracted."
    wire_evidence = "\n".join(
        f"- `{item.document}:{item.line}`: {item.text}" for item in wire_contract.evidence[:5]
    ) or "- No action-wire evidence extracted."
    runtime_lines = "\n".join(
        f"- `{note.document}:{note.line}`: {note.text}" for note in runtime_notes[:12]
    ) or "- No runtime notes extracted."
    build_path = _recommended_build_path(surface.category)
    vlm_policy = _vlm_policy(surface.category)

    return f"""# {bundle.game_slug} Agent Build Plan

Generated by `maker_v1`.

This is a generated artifact. Update `maker_v1` when changing the generator;
regenerate this bundle when changing the target game artifact.

## Inputs

- Guide bundle: `{bundle.guide_dir}`
- Guide bundle hash: `{bundle.bundle_hash}`
- Guide contract: `{_guide_contract_status(bundle)}`
- Game source: {source_text}
- Agent framework: `{agent_framework.framework_dir}`
- Agent framework package: `{agent_framework.package}`
- Agent framework source root: `{agent_framework.package_source_root}`
- Output directory: `{output_dir}`

## Guide Bundle Health

Missing core documents:

{missing}

## Observation Surface

- Category: `{surface.category}`
- Confidence: `{surface.confidence}`
- Visual score: `{surface.visual_score}`
- Symbolic score: `{surface.symbolic_score}`

Evidence:

{evidence}

## Recommended Build Path

{build_path}

## Candidate Action Registry

These are guide-derived candidates, not a final validated action registry.

{action_lines}

## Action Wire Contract

- Style: `{wire_contract.style}`
- Default action: `{wire_contract.default_action}`
- Requires message type: `{wire_contract.requires_message_type}`

Evidence:

{wire_evidence}

## Runtime And Lifecycle Notes

{runtime_lines}

## VLM Policy

{vlm_policy}

## Next Implementation Steps

1. Validate the candidate action registry against `INTERFACE_CONTRACT.md` and
   source code.
2. Review the generated `agent/` scaffold if this is a symbolic-primary,
   visual-primary, or mixed/alternate game. The live runner should use the
   Cyborg runtime adapter in `agent/cyborg_agent.py`; `policy.py` and
   `protocol.py` remain small testable helpers.
3. Run generated action serialization tests before sending any live actions.
4. Review `agent/perception/decoder_spec.json`,
   `agent/perception/DECODER_GENERATION_TASK.md`, and
   `agent/perception/decoder.py` before turning raw observations into image
   fixtures or typed symbolic state.
5. Run the generated decoder tests, then add source-derived observation
   fixtures for edge cases the guide docs did not prove.
6. For visual or mixed games, use `visual_bootstrap/play_card.md` and
   `visual_bootstrap/vlm_schema.json` for any VLM labeling work.
7. Build `agent/policy_from_labels.py` from schema-valid labels once enough
   decoded frame labels exist for a starter rule set.
8. Measure VLM calls per episode and replace repeated VLM labels with
   deterministic parser tests.
"""


def _generate_agent_artifacts(
    *,
    bundle: GuideBundle,
    output_dir: Path,
    surface: ObservationSurface,
    actions: tuple[ActionCandidate, ...],
    wire_contract: ActionWireContract,
    agent_framework: AgentFrameworkRef,
) -> tuple[Path, ...]:
    if surface.category == "symbolic_primary":
        return generate_symbolic_agent(
            bundle=bundle,
            output_dir=output_dir,
            surface=surface,
            actions=actions,
            wire_contract=wire_contract,
            agent_framework=agent_framework,
        )
    if surface.category in {"visual_primary", "mixed_or_alternate"}:
        return generate_visual_agent_shell(
            bundle=bundle,
            output_dir=output_dir,
            surface=surface,
            actions=actions,
            wire_contract=wire_contract,
            agent_framework=agent_framework,
        )

    agent_readme = output_dir / "agent" / "README.md"
    write_text(agent_readme, _render_agent_placeholder_readme(bundle, surface))
    return (agent_readme,)


def _requires_framework_runtime(category: str) -> bool:
    return category in {"symbolic_primary", "visual_primary", "mixed_or_alternate"}


def _recommended_build_path(category: str) -> str:
    if category == "symbolic_primary":
        return """Build a typed symbolic observation decoder first. The first generated
agent should connect, parse one observation, choose a valid action from the
registry, and survive a smoke episode without any VLM dependency."""
    if category == "visual_primary":
        return """Build a connection/control shell and minimal deterministic frame
decoder first. Use the VLM only for novel or low-confidence frames, save those
labels as fixtures, and turn repeated labels into parser tests before adding
policy complexity."""
    if category == "mixed_or_alternate":
        return """Resolve which structured channels are online-admissible for the
submitted agent. Prefer admissible symbolic data for control. Use VLM and
debug/global/replay channels only as build-time supervision unless the guide
and source prove they are part of the player contract."""
    return """Do not generate policy code yet. Re-read `INTERFACE_CONTRACT.md` and
`OBSERVATION_DECODING.md`, inspect the source if needed, and classify the
player observation surface before building an agent."""


def _vlm_policy(category: str) -> str:
    if category == "symbolic_primary":
        return """No VLM should be required for the baseline path. Keep the VLM schema
available for future diagnostics, but treat any VLM use as optional annotation
work rather than part of normal control."""
    if category in {"visual_primary", "mixed_or_alternate"}:
        return """Use the VLM as a schema-bound observation labeler and fallback action
recommender only. The controller must validate every recommended action, and
the parser/test loop should reduce VLM calls over time."""
    return """VLM use is premature until the observation contract is classified."""


def _render_agent_placeholder_readme(bundle: GuideBundle, surface: ObservationSurface) -> str:
    return f"""# {bundle.game_slug} Generated Agent

This directory is reserved for generated agent code.

Current status: `maker_v1` did not generate a runnable agent scaffold because
this guide bundle is classified as `{surface.category}`. Phase 2 currently
generates runnable scaffolds only for `symbolic_primary` games.

Observation surface classification: `{surface.category}`.

Use `../AGENT_BUILD_PLAN.md` as the source for the next generated slice.
"""
