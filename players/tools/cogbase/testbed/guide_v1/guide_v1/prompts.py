from __future__ import annotations

from collections.abc import Mapping, Set
from pathlib import Path

from .documents import DocumentSpec, get_document
from .framework import AgentFrameworkRef


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def render_template(template: str, variables: Mapping[str, object]) -> str:
    rendered = template
    for name, value in variables.items():
        rendered = rendered.replace(f"{{{{{name}}}}}", str(value))
    return rendered


def load_template(filename: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    return (prompts_dir / filename).read_text(encoding="utf-8")


def format_prior_docs(
    document: DocumentSpec,
    output_dir: Path,
    completed_documents: Set[str],
) -> str:
    lines = []
    for dependency_name in document.dependencies:
        if dependency_name not in completed_documents:
            continue
        dependency = get_document(dependency_name)
        lines.append(f"- {output_dir / dependency.filename} — {dependency.description}")
    return "\n".join(lines) if lines else "(none)"


def build_runner_prompt(
    document: DocumentSpec,
    *,
    game_source_path: Path,
    agent_framework: AgentFrameworkRef,
    output_dir: Path,
    output_file: Path,
    completed_documents: Set[str],
) -> str:
    template = load_template("_preamble.md") + "\n\n" + load_template(document.prompt_template)
    return render_template(
        template,
        {
            "game_source_path": game_source_path,
            "agent_framework_path": agent_framework.framework_dir,
            "agent_framework_package": agent_framework.package,
            "agent_framework_package_source_root": agent_framework.package_source_root,
            "output_dir": output_dir,
            "output_file": output_file,
            "prior_docs": format_prior_docs(document, output_dir, completed_documents),
            "doc_name": document.filename,
        },
    )


def build_synthesizer_prompt(
    document: DocumentSpec,
    *,
    game_source_path: Path,
    agent_framework: AgentFrameworkRef,
    output_dir: Path,
    output_file: Path,
    draft_a: Path,
    draft_b: Path,
    completed_documents: Set[str],
) -> str:
    return render_template(
        load_template("_synthesizer.md"),
        {
            "game_source_path": game_source_path,
            "agent_framework_path": agent_framework.framework_dir,
            "agent_framework_package": agent_framework.package,
            "agent_framework_package_source_root": agent_framework.package_source_root,
            "output_dir": output_dir,
            "output_file": output_file,
            "prior_docs": format_prior_docs(document, output_dir, completed_documents),
            "draft_a": draft_a,
            "draft_b": draft_b,
            "doc_name": document.filename,
        },
    )
