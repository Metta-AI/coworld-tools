# eyes_v1 Generated Artifacts

This directory is for game-specific artifacts produced by the `eyes_v1`
meta-pipeline. These artifacts are outputs, not reusable `eyes_v1` toolkit
code.

`eyes_v1` is deprecated as a primary pipeline stage. New games should start
with `guide_v1`; use this directory only for historical outputs or targeted
visual-artifact experiments identified by a guide or human operator.

Typical contents:

- `ui_report_*.md`
- `flow_report_*.md`
- `agent_design_*.md`
- `implementation_plan_*.md`
- `implementation_review_*.md`
- `implementation_log_*.md`
- `capture_checklist_*.json`
- `capture_results_*.md`
- generated explorer tools such as `explore_views/`
- tool outputs such as `captured_frames/`

Use one subdirectory per target game or run, for example:

```text
output/
  among_them/
    ui_report_synthesized_*.md
    flow_report_synthesized_*.md
    explore_views/
    captured_frames/
```

Future coding agents should treat everything below game/run directories here
as generated artifact state. Modify the deprecated `eyes_v1` generator code in
the parent directory only when maintaining legacy visual tooling.
