from __future__ import annotations

from collections.abc import Mapping, Set
from pathlib import Path

from .documents import DocumentSpec, get_document
from .framework import AgentFrameworkRef
from .sidecar import sidecar_path


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Per-doc cap on inlined summary lines. Stage-6/7 documents depend on every
# prior doc; inlining a short summary keeps the prompt comfortably under the
# model context window even when 13+ deps are summarized at once.
_PRIOR_DOC_SUMMARY_LINES = 12


def render_template(template: str, variables: Mapping[str, object]) -> str:
    rendered = template
    for name, value in variables.items():
        rendered = rendered.replace(f"{{{{{name}}}}}", str(value))
    return rendered


def load_template(filename: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    return (prompts_dir / filename).read_text(encoding="utf-8")


def summarize_prior_doc(doc_path: Path, *, max_lines: int = _PRIOR_DOC_SUMMARY_LINES) -> str:
    """Return the H1 title plus the first body paragraph of a guide doc.

    Used to inline a short summary of each prior doc into the prompt so the
    runner does not have to ``Read`` every dependency in full. Stops at the
    first second-level heading or after ``max_lines`` of body lines.
    """

    try:
        text = doc_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    summary: list[str] = []
    body_lines = 0
    seen_title = False
    for line in text.splitlines():
        if not seen_title:
            if line.startswith("# "):
                summary.append(line)
                seen_title = True
            continue
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("###"):
            break
        summary.append(line)
        if stripped:
            body_lines += 1
        if body_lines >= max_lines:
            break

    while summary and not summary[-1].strip():
        summary.pop()
    return "\n".join(summary)


def format_prior_docs(
    document: DocumentSpec,
    output_dir: Path,
    completed_documents: Set[str],
) -> str:
    """Inline brief summaries of each completed dependency document.

    The runner should treat these summaries as the primary context for what a
    prior doc covers. Reading the full file is allowed but should be reserved
    for verifying a specific claim with a quoted line, not for general
    orientation.
    """

    blocks: list[str] = []
    for dependency_name in document.dependencies:
        if dependency_name not in completed_documents:
            continue
        dependency = get_document(dependency_name)
        dep_path = output_dir / dependency.filename
        summary = summarize_prior_doc(dep_path)
        header = f"### {dependency.filename}\nPath: `{dep_path}`\nPurpose: {dependency.description}"
        block = f"{header}\n\n{summary}" if summary else header
        blocks.append(block)
    return "\n\n".join(blocks) if blocks else "(none)"


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
    sidecar_file = sidecar_path(output_dir, document.filename)
    return render_template(
        template,
        {
            "game_source_path": game_source_path,
            "agent_framework_path": agent_framework.framework_dir,
            "agent_framework_package": agent_framework.package,
            "agent_framework_package_source_root": agent_framework.package_source_root,
            "output_dir": output_dir,
            "output_file": output_file,
            "sidecar_file": "" if sidecar_file is None else str(sidecar_file),
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
