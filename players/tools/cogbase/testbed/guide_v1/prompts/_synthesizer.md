You are synthesizing two independently-generated drafts of the same reference
document into a single, authoritative final version.

## Your Task

Document: {{doc_name}}

Two runners independently analyzed the game source and produced drafts of this
document. Your job is to merge them into one cohesive, high-quality document
that takes the best of both.

## Drafts

- Draft A: {{draft_a}}
- Draft B: {{draft_b}}

Read both drafts in full before writing.

## Agent Policy Framework

The final document should be compatible with the generic Cyborg policy
framework at {{agent_framework_path}} and its Python package
{{agent_framework_package}} under {{agent_framework_package_source_root}}.
When synthesizing implementation, MVP, or policy architecture guidance, check
the framework docs/source as needed and use its actual concepts: belief,
perception, deterministic modes, symbolic intents, action resolution, strategy
directives, TTL/fallback behavior, and trace boundaries. The framework does not
override the game source facts at {{game_source_path}}; use it as the target
agent architecture for those facts.

## Synthesis Rules

1. **Prefer specificity**: When one draft has concrete details (values, types,
   paths, function names) and the other is vague, use the specific version.

2. **Resolve contradictions**: If the drafts disagree on a fact, determine which
   is correct by checking the game source at {{game_source_path}}. Do not
   average or hedge — pick the correct answer.

3. **Union of coverage**: If one draft covers a topic the other missed, include
   it (as long as it's within this document's jurisdiction).

4. **Maintain jurisdiction**: This document has a specific scope. Do not include
   content that belongs to other documents in the suite, even if a draft
   included it. See the jurisdiction section below.

5. **No merge artifacts**: The output should read as a single coherent document,
   not a stitched-together patchwork. Rewrite as needed for flow.

6. **Preserve structure**: Use clear headings, tables, and lists. The document
   should be scannable.

## Prior Documents (for consistency, not duplication)

{{prior_docs}}

## Output

Write the final synthesized document to: {{output_file}}
