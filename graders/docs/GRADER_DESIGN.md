# Grader Design

> **Status:** local mirror of the current tentative Coworld grader contract. The authoritative role doc remains
> `~/coding/metta/packages/coworld/src/coworld/docs/roles/grader.md`.

## Purpose

Graders score how interesting or useful a Coworld episode was from the game creator's perspective. The output is a
small ranking signal, not a full human-readable report.

## Current Contract From Metta

The grader role is still `reserved`, but its current tentative process contract is defined:

1. A CLI, hosted UI, or pipeline chooses a grader runnable from `manifest.grader[]`.
2. The invoker assembles an episode bundle zip.
3. The invoker starts the grader container with `COGAME_EPISODE_BUNDLE_URI` and `COGAME_GRADE_URI`.
4. The grader reads the bundle, computes a score, writes grade JSON, and exits.

The episode runner itself does not automatically launch graders.

## Input

`COGAME_EPISODE_BUNDLE_URI` points at an episode bundle zip. The current Coworld role doc calls out `file://` for
local runs and HTTP(S) for hosted runs. The starter graders in this repo also support plain local paths and `s3://` so
the same URI helpers can be used for inputs and outputs. The bundle contains `manifest.json` at the zip root. Consumers
should read that manifest to locate files such as `results.json` rather than hard-coding bundle paths.

## Output

`COGAME_GRADE_URI` points at the grade JSON destination. Local implementations should support local paths and
`file://`; hosted-compatible implementations should also support HTTP(S) and `s3://`.

The grade JSON must include:

```json
{
  "score": 0.85
}
```

It should also include:

```json
{
  "grader_id": "among-them-grader"
}
```

`grader_id` conventionally matches the runnable id in `manifest.grader[]`.

## Open Questions

These are Coworld contract questions, not repo-local decisions:

1. Whether `score` should stay grader-defined or move to a canonical range.
2. How scores from different graders should be compared or normalized.
3. How multiple graders scoring the same episode should be aggregated.
4. The exact CLI and hosted UI surfaces for invoking graders.
5. Whether future grader outputs need additional required provenance fields.

## Local Implementation Rules

- Follow the current Metta contract; do not invent alternate env vars.
- Keep one implementation per leaf directory under `graders/<target>/<name>/`.
- Add a root `CATALOG.yaml` entry only when an implementation is runnable and documented.
- Leave empty scaffold directories uncataloged.
- Update this file whenever the authoritative Coworld grader doc changes.
