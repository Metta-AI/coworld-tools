# PaintArena And Cogs Vs Clips Grader Implementation Plan

## Purpose

Add two starter Coworld grader implementations that match the current tentative
grader contract already used by `among-them-grader`:

- `paint-arena-grader`
- `cogs-v-clips-grader`

The goal is not to build a complete game-analysis framework. The goal is to add
small, deterministic, dependency-light graders that produce one scalar
interestingness score for post-episode ranking.

## Source Of Truth

Use the current Coworld grader contract as the runtime source of truth:

- `~/coding/metta/packages/coworld/src/coworld/docs/roles/grader.md`
- `~/coding/metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md`
- `~/coding/metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md`
- This repo's current `README.md` and `docs/GRADER_DESIGN.md`
- The existing implementation:
  `graders/among_them/among_them_grader/among_them_grader.py`

Important contract facts:

- Graders are post-episode supporting runnables.
- Graders are on-demand; the episode runner does not launch them automatically.
- A grader reads `COGAME_EPISODE_BUNDLE_URI`.
- A grader writes JSON to `COGAME_GRADE_URI`.
- Output JSON must include `score`.
- Output JSON should include `grader_id`.
- `score` meaning and normalization are currently grader-defined.

## Current Repo State

`among-them-grader` is the only real cataloged implementation today. It is a
self-contained Python file with local path, `file://`, HTTP(S), and `s3://` URI
support. It reads a bundle zip, uses root `manifest.json` to locate
`results.json`, writes `{"grader_id": ..., "score": ...}`, and exits.

`paint_arena_grader.py`, `cogs_v_clips_grader.py`, and their READMEs/build
scripts are empty placeholders. They should become real starter
implementations and be added to `CATALOG.yaml`.

## Non-Goals

- Do not change authoritative Coworld docs in `~/coding/metta`.
- Do not implement `coworld run-grader`.
- Do not publish Docker images.
- Do not push branches or open a PR.
- Do not introduce a shared package that would complicate single-image leaf
  builds. Some small IO duplication with `among-them-grader` is acceptable.
- Do not add heavyweight Metta, Coworld, Cogsguard, or Pydantic dependencies to
  the grader containers.
- Do not require live episodes, Docker, S3, HTTP servers, or Metta imports in
  the unit tests.

## Shared Implementation Pattern

Each grader should be a single self-contained Python script in its leaf
directory:

- `graders/paint_arena/paint_arena_grader/paint_arena_grader.py`
- `graders/cogs_v_clips/cogs_v_clips_grader/cogs_v_clips_grader.py`

Each script should:

1. Read `COGAME_EPISODE_BUNDLE_URI`.
2. Open the zip bundle.
3. Read root `manifest.json`.
4. Use `manifest.files.<token>` to locate bundle entries.
5. Compute a deterministic score.
6. Write JSON to `COGAME_GRADE_URI`.
7. Print a short stderr status line.

URI support should match `among-them-grader`:

- local path
- `file://`
- HTTP(S)
- `s3://` via lazy `boto3` import

Output JSON should stay minimal and match `among-them-grader`:

```json
{
  "grader_id": "paint-arena-grader",
  "score": 0.42
}
```

and:

```json
{
  "grader_id": "cogs-v-clips-grader",
  "score": 0.42
}
```

Extra diagnostic fields are intentionally omitted from runtime output for now.
Tests can assert internal signal helpers directly.

## PaintArena Grader

### Artifact Shape

PaintArena game results are produced by the PaintArena game server and include:

- `scores`: numeric final score per player
- `painted_tiles`: tile count per player
- `ticks`: episode length in ticks

PaintArena replay payload includes:

- `config.width`
- `config.height`
- `frames`
- `results`

The grader needs the replay config only to know the maximum possible final-score
difference: `width * height`.

### Scoring Intent

The user-requested PaintArena interestingness definition is simple:

> difference in final score, normalized for maximum possible score difference

Implementation:

1. Read `results` from the bundle.
2. Read `replay` from the bundle.
3. Extract `width` and `height` from `replay.config`.
4. Extract numeric final scores from `results.scores`.
5. If there are fewer than two final scores, return `0.0`; there is no
   between-player difference to rank.
6. Sort scores descending.
7. Compute `margin = top_score - second_score`.
8. Compute `max_margin = width * height`.
9. Return `round(clamp(margin / max_margin, 0.0, 1.0), 4)`.

If replay config is absent or invalid, fail clearly instead of silently
inventing a board size. That keeps the normalization contract honest: the
requested score is normalized by maximum possible score difference, and that
maximum is not knowable without the board dimensions. This also matches the
current Coworld supporting-runnable assumption that episode bundles include a
replay artifact for successful episodes.

### PaintArena Tests

Add `tests/test_paint_arena_grader.py` covering:

- Pure scoring: e.g. scores `[80, 20, 10]`, `width=10`, `height=10` returns
  `0.6`.
- Ties return `0.0`.
- Single-player results return `0.0`.
- Score clamps at `1.0` if malformed scores exceed the board capacity.
- Full entrypoint reads a synthetic bundle with `manifest.files.results` and
  `manifest.files.replay`, then writes the expected grade JSON.
- Missing replay config raises a clear error in the helper or entrypoint path.
- Malformed replay JSON raises a clear error in the entrypoint path.

## Cogs Vs Clips Grader

### Artifact Shape

Cogs vs Clips results currently include:

- `scores`: numeric per-agent rewards
- `steps`: episode length
- `mission`: mission name

Cogs vs Clips replay is a MettaScope/Mettagrid replay. Relevant current
top-level fields include:

- `version`
- `item_names`
- `type_names`
- `tags`
- `num_agents`
- `max_steps`
- `objects`
- `infos`

This shape is based on the current local implementation and tests:

- `~/coding/metta/worlds/cogs_vs_clips/game/server.py`
  - writes `EpisodeReplay.get_replay_data()` as the replay artifact;
  - writes results as `{"scores": ..., "steps": ..., "mission": ...}`.
- `~/coding/metta/packages/mettagrid/python/src/mettagrid/simulator/replay_log_writer.py`
  - defines replay format version 4;
  - stores top-level `item_names`, `type_names`, `tags`, `objects`, and
    `infos`;
  - writes compact value histories with `[step, value]` entries.
- `~/coding/metta/packages/mettagrid/python/src/mettagrid/util/grid_object_formatter.py`
  - defines object fields such as `type_name`, `location`, `inventory`,
    `color`, `tag_ids`, `agent_id`, `is_agent`, `alive`, `total_reward`,
    `vibe`, and `vibe_id`.
- `~/coding/metta/packages/coworld/tests/test_cogs_vs_clips_coworld.py`
  - asserts that saved Cogs vs Clips replays are version 4 and include
    `objects`;
  - asserts policy metadata is stored on agent objects.

Important replay detail: object fields may either be plain scalar/list values or
compact value histories of the form:

```json
[[0, "initial value"], [12, "new value"]]
```

The grader must use helper functions that can read both forms:

- `last_value(value)` returns the final value.
- `first_value(value)` returns the first value.
- `all_values(value)` returns the sequence of values if the field is compacted,
  or a one-item sequence otherwise.

To avoid confusing ordinary lists with compact histories, the generic helper
should treat a list as a compact history only when:

- it is non-empty;
- every entry is a two-item list or tuple;
- the first element of every entry is numeric; and
- the first step is `0`.

This matters because object `inventory` is itself represented as a list of
`[resource_id, amount]` pairs and can legitimately start with resource id `0`.
For list-valued fields such as `inventory` and `tag_ids`, use field-specific
helpers that only unwrap a compact history when the stored value has the
expected container shape, e.g. inventory history
`[[0, [[resource_id, amount], ...]], ...]`. Empty lists and malformed
history-like lists should be treated as scalar values.

Agent objects can be identified by `is_agent == true`, or by the presence of
`agent_id`.

Junction objects can be identified by final or historical `type_name ==
"junction"` or the `type:junction` tag.

Inventory values are numeric resource ids in current replays, not names. The
grader should map ids through `item_names`.

Missing or malformed optional replay fields should zero out the affected signal
rather than fail the whole grader. Missing replay JSON or missing top-level
`objects` should fail clearly, because then the grader cannot satisfy the
requested replay-based scoring goal.

### Scoring Intent

The user requested that Cogs vs Clips interestingness reflect performance
differences inside the game as well as possible from replay data:

- resources mined or carried
- hearts made or carried
- junctions captured
- death stats
- role changes
- other available performance differences

Current replay data does not reliably expose per-agent "mined total",
"hearts made", or "junction captured by agent" counters in the saved replay.
The available dependency-free approximation is:

- score/reward spread from `results.scores`, agent `total_reward`, and
  `infos.episode_rewards`;
- per-agent peak inventory differences for resources and hearts;
- per-agent role/gear coverage and role/vibe changes;
- death/survival and HP differences inferred from `alive` and `hp` inventory;
- team-level junction activity inferred from junction color/tag changes.

This is deliberately a heuristic "review-worthy difference" score, not a
formal CogsGuard skill score.

### Cogs Vs Clips Signals

Compute these normalized components, each `0.0..1.0`:

1. `score_signal`
   - Compute normalized spread for each available source:
     - `results.scores`;
     - final per-agent `total_reward` from agent objects;
     - `replay.infos.episode_rewards`.
   - Use the maximum available spread.
   - Use normalized numeric spread:
     `(max(values) - min(values)) / max(abs(max(values)), abs(min(values)), 1.0)`.
   - Clamp to `0.0..1.0`.

2. `inventory_signal`
   - For each agent, compute peak inventory total for core resources:
     `oxygen`, `carbon`, `germanium`, `silicon`.
   - Add `2 * peak_heart` so heart pickup/carrying is visible even when raw
     resource counts are low.
   - Use normalized spread across agents. This approximates mining/resource
     pipeline differences, but does not claim exact mined-total attribution.

3. `role_survival_signal`
   - For each agent, compute a role activity value:
     - number of role gear types ever held among `aligner`, `scrambler`,
       `miner`, `scout`;
     - plus number of distinct role-like `vibe` values observed when those ids
       map to role names.
   - Compute `role_signal` as normalized spread of those role activity values.
   - For each agent, infer whether it ever dies from `alive` histories.
   - Infer final HP and minimum observed HP from the `hp` inventory if present.
   - Compute `death_divergence = 1.0` when at least one agent dies and at least
     one agent survives; otherwise `0.0`.
   - Compute `hp_signal` as the maximum normalized spread of final HP and
     minimum observed HP.
   - Compute `survival_signal = min(1.0, 0.6 * death_divergence + 0.4 * hp_signal)`.
   - Compute `role_survival_signal = max(role_signal, survival_signal)`.

4. `junction_signal`
   - For each junction, inspect `color` and `tag_ids` histories.
   - Count junctions whose color or tags changed at least once.
   - Normalize by total junction count.
   - This is team-level territory activity, not per-agent attribution.

### Cogs Vs Clips Final Formula

Use a weighted sum:

```text
score =
  0.35 * score_signal
  + 0.30 * inventory_signal
  + 0.20 * role_survival_signal
  + 0.15 * junction_signal
```

Clamp to `0.0..1.0` and round to 4 decimals.

Reasoning:

- Final scores/rewards matter, but should not dominate because current Cogs vs
  Clips results can be flat early in an episode.
- Inventory and heart signals capture player-behavior divergence when final
  reward is still uninformative.
- Role and survival/HP differences are useful but should not dominate.
- Junction activity is important to game interestingness, but current replay
  data does not reliably attribute captures to a specific player, so it is
  capped as a team-level signal.

### Cogs Vs Clips Tests

Add `tests/test_cogs_v_clips_grader.py` covering:

- Pure helper handles scalar fields and compact `[[step, value], ...]`
  histories.
- Pure helper does not misclassify inventory `[[item_id, amount], ...]` as a
  compact history, including the valid case where `item_id` is `0`.
- Pure scoring returns `0.0` for flat results and no replay activity.
- Pure scoring increases when one agent has higher reward, resources, hearts,
  role gear, or another agent dies.
- Junction color/tag changes contribute even when per-agent scores are flat.
- Full entrypoint reads a synthetic bundle with `manifest.files.results` and
  `manifest.files.replay`, then writes grade JSON.
- Replay without `replay` token should fail clearly; Cogs vs Clips cannot meet
  the requested "given what's in a replay" goal from results alone.
- Missing `item_names` should not fail the whole grader; inventory and role
  signals should become `0.0`.
- Missing top-level `objects` should fail clearly.

## Catalog And Build Files

Update `CATALOG.yaml` to include:

- `paint-arena-grader`
- `cogs-v-clips-grader`

Keep status as `starter`, family as `symbolic`, and image names local:

- `paint-arena-grader:latest`
- `cogs-v-clips-grader:latest`

Add Dockerfiles matching the Among Them pattern:

- `python:3.13-slim`
- install `boto3>=1.34`
- copy the grader script into `/app`
- entrypoint `python /app/<grader>.py`

Add build scripts matching the Among Them pattern:

- default `linux/amd64`
- default image name matching catalog
- pass through additional Docker build args

## Documentation Updates

Update these docs:

- `README.md`
  - mark PaintArena and Cogs vs Clips as starter implementations, cataloged.
  - keep template as uncataloged placeholder.
- `docs/GRADER_DESIGN.md`
  - no major contract change expected; only update if implementation details
    should be reflected.
- `docs/COWORLD_REFERENCE.md`
  - no major contract change expected; only update if catalog status is
    described there.
- Per-grader READMEs
  - document required env vars.
  - document supported URI schemes.
  - document score meaning and limitations.

## Validation

Run:

```bash
python3 -m unittest discover -s tests
python3 -m compileall graders
git diff --check
rg -n "COGAME_RESULTS_URI|COGAME_GRADE_OUTPUT_URI|no documented runtime contract|undefined stubs" .
```

The tests should not need Docker, network, or Metta imports.

## External Review Request

Ask the reviewer to focus on:

- whether the plan violates the current Coworld grader contract;
- whether the PaintArena normalization should fail without replay config;
- whether Cogs vs Clips score formula is too complex for a starter grader;
- whether the Cogs vs Clips replay extraction is robust enough for scalar and
  compact history fields;
- whether any missing tests would allow a likely regression;
- whether output should remain minimal or include debug signals.

## External Review Result

`auggie` reviewed the initial plan and found no Coworld grader contract
violations. It raised three blocking concerns for the Cogs vs Clips portion:

1. The first plan did not cite a replay-schema source.
2. The first Cogs vs Clips scorer was too complex for a starter grader.
3. The spread, survival, and history-handling formulas were not exact enough.

This revised plan addresses those findings by citing the current Cogs vs Clips
server, MettaGrid replay writer, grid-object formatter, and Coworld tests;
reducing the Cogs vs Clips scorer from six signals to four; defining exact
normalization and survival formulas; and specifying missing-field and compact
history behavior.
