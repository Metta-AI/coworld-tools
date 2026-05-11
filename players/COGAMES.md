# COGAMES

> **Living document.** The cogames CLI, the list of active seasons, and the
> set of supported games all change regularly. **Re-read this at the start
> of every session, and update it whenever you observe drift** (new seasons,
> removed seasons, renamed commands, broken flows). If `cogames --help` and
> this file disagree, the CLI is right — fix this file.
>
> Last reviewed: 2026-05-11 | cogames CLI: `/Users/jamesboggs/coding/personal_cogs/.venv/bin/cogames`

---

## What cogames is

**cogames** is Softmax's multi-agent game framework and the evaluation
harness for the **Alignment League Benchmark (ALB)** — a tournament suite
designed to measure how AI agents align, coordinate, and collaborate with
each other and with humans.

You interact with it as:

- A **Python package** (`pip install cogames`) exposing game environments,
  policy base classes, and a `cogames` CLI.
- A **tournament system** with seasons, leaderboards, teams, and matches
  run by Softmax-hosted Docker workers.
- A **set of games** (currently Cogs vs Clips, Among Them, Four Score —
  see § games below).

Source & references on this machine:

| Path | What it is |
|---|---|
| `COGAMES_CLI.md` (this repo) | Full `cogames` CLI reference — every command and subcommand walked via `--help`, with quirks and shared option patterns. Regenerate when the CLI version changes. |
| `~/coding/metta/packages/cogames/` | The `cogames` Python package source (CLI, policy base classes, Docker runner, CvC game bindings). Authoritative. |
| `~/coding/metta/packages/cogames/MISSION.md` | In-universe briefing for CvC (the flagship game). |
| `~/coding/metta/packages/cogames/Dockerfile.episode_runner` | The exact image tournament matches run in. Check this when debugging missing deps. |
| `~/coding/metta/cogames-agents/` | Softmax's own scripted baselines and teacher policies. Good prior art. |
| `~/coding/metta/cogames-agents/COGAMES_SUBMISSION.md` | Notes on submitting Nim-backed agents. |
| `~/coding/bitworld/among_them/players/how_to_submit_to_cogames.md` | Battle-tested submission guide for Among Them (Nim + ctypes). |
| `~/coding/bitworld/among_them/players/how_to_make_a_bot.md` | Deep guide to writing an Among Them bot. |

External references:

- [softmax.com/play.md](https://softmax.com/play.md) — starter walkthrough.
  Sometimes lags the live CLI; treat CLI as authoritative.
- [softmax.com/alignmentleague](https://www.softmax.com/alignmentleague)
- [deepwiki.com/Metta-AI/cogames](https://deepwiki.com/Metta-AI/cogames)
- [api.observatory.softmax-research.net/docs](https://api.observatory.softmax-research.net/docs) — OpenAPI spec for seasons/matches/leaderboards.
- Discord: `https://discord.gg/secret-hologenesis`

## Install / environment

Python **>=3.11** required (3.11 or 3.12). Use an isolated venv.

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install 'cogames[neural]'
uv pip install 'cogsguard @ git+https://github.com/Metta-AI/cogame-cogsguard'  # for CvC

# For Among Them specifically (the PyPI `bitworld` extra is broken on
# cogames 0.25.7; install the git rev pinned by the metta checkout):
uv pip install 'bitworld @ git+https://github.com/Metta-AI/bitworld.git@7203d529a895e8eabc1eefdc3d2c4252eb2ac6ea'
# ...or install the whole metta cogames package editable:
uv pip install -e /path/to/metta/packages/cogames -e /path/to/metta/packages/mettagrid
```

For Among Them you also need the Nim toolchain (via `nimby`) if you want
to rebuild binaries. Pre-built binaries on our dev machine live in
`~/coding/bitworld/out/`.

Verify:

```bash
cogames version
cogames --help
```

Auth (needed for upload/submit):

```bash
cogames auth login     # opens a browser to softmax.com/cli-login
cogames auth status
```

> Gotcha: `cogames auth status` may print "Run softmax login first" even
> when things are fine, and running `softmax login` / `uv run softmax login`
> uses a **different** package (`softmax-cli`) that may not be installed.
> Always use `cogames auth login`.

Docker is required for `--dry-run` validation (which runs your policy for
10 steps in the real tournament image). Install Docker Desktop on macOS and
ensure `docker info` succeeds before validating.

## Games (as of 2026-05-11)

> This is a living list. Confirm with `cogames season list` and
> `cogames bitworld games` before relying on it.

### Cogs vs Clips (CvC)

**Status:** flagship ALB game. Widely supported.

- **Type:** cooperative multi-agent territory control. Teams of Cogs
  capture and defend junctions against automated "Clips" opponents.
- **Roles:** Miner (+cargo, fast extraction), Aligner (captures neutral
  junctions with hearts), Scrambler (+HP, disrupts enemy junctions), Scout
  (+energy, +HP, recon). No single role wins alone — cooperation is
  mandatory.
- **Scoring:** `reward per tick = junctions_held / max_steps`. Team-based.
- **Observability:** partial. Agents have limited visibility.
- **Game source:** `cogsguard` package (`github.com/Metta-AI/cogame-cogsguard`).
- **Active seasons:** `beta-cvc` (freeplay), `beta-four-score` (variant),
  `beta-teams-tiny-fixed` (team tournament). Confirm.
- **Briefing:** `~/coding/metta/packages/cogames/MISSION.md`.
- **Missions:** many, e.g. `arena`, `training_facility_1`, `machina_1`,
  plus variants (`talk`, etc.). Use `cogames play --help` for game/mission
  options.

### Among Them (BitWorld)

**Status:** active game, season visibility fluctuates.

**Local agent policy:** in this repo, `among_them/guided_bot/` is the
active Among Them agent. `among_them/modulabot/` is fully deprecated and
kept only for historical reference. Do not inspect, modify, test, run, or
ship the local modulabot unless James explicitly asks for it.

- **Type:** Among-Us-style hidden-role game. Crewmates complete tasks
  and identify imposters; imposters kill crewmates and avoid detection.
- **Interface:** the cogames `BitWorldRunner`
  (`mettagrid.runner.bitworld_runner`) drives a Nim WebSocket server and
  hands your policy a **4-frame stack of 128×128 4-bit palette-indexed
  pixel frames** — `shape=(4, 128, 128) dtype=uint8 kind=pixels`.
  Confirmed empirically (2026-05-06) via
  `personal_cogs/among_them/scripts/play_local.py`.
- **No structured state observation in the tournament path.** The
  `STATE_FEATURES` layout in `bitworld.pufferlib.bitworld_pufferlib` is
  only available inside the training harness; the policy contract that
  cogames ships to the tournament worker uses pixels only. Any serious
  bot must implement map localization, sprite matching, task pixel
  logic, and voting-screen parsing itself (the Nim modulabot is ~4 kLOC
  of this).
- **Phases:** gameplay, voting interstitials, result screens. Chat only
  during voting.
- **Season:** `among-them` is visible to the authenticated CLI as of
  2026-05-11 — "Among Them freeplay: policies compete in 8-player
  BitWorld matches scored by role win rate." The API currently reports
  `status: complete` and `public: false`, with `competition` as both
  entry and leaderboard pool. Confirm with `cogames season list` and
  `cogames season show among-them` before submitting.
- **Package:** needs `pip install 'bitworld @ git+https://github.com/Metta-AI/bitworld.git'`
  for local episode runs; pinned SHA is in the cogames `pyproject.toml`
  (see `bitworld` extra). Pre-built Nim binaries live at
  `~/coding/bitworld/out/` on our dev machine.
- **Canonical bots (Nim):**
  `~/coding/bitworld/among_them/players/nottoodumb.nim` and
  `~/coding/bitworld/among_them/players/modulabot/` (the latter is a
  modular rewrite; its `DESIGN.md` is the best entry point for
  architecture).
- **Python prior art:** `~/coding/metta/cogames-agents/src/cogames_agents/policy/bitworld_among_them.py`
  — `BitWorldAmongThemScoutPolicy`, `BitWorldAmongThemCyborgPolicy`, plus
  5 scripted baselines (Beacon, Circuit Sentinel, Pathfinder, Sleuth, Task
  Marshal) added 2026-05-04. The cyborg path does a mix of state-obs
  heuristics (when available) and a `ctypes` wrapper around the Nim
  `libnottoodumb` shared library (when available) — *not* a reference
  pixel-perception implementation in Python. The scripted baselines are
  simpler, portable, pixel-only policies used as tournament opponents.
- **Submission path:** Python policy subclass of `MultiAgentPolicy`.
  For guided_bot, use `among_them/guided_bot/cogames/ship.sh`, which
  bundles via `cogames upload --season` so Bedrock/secret flags are
  supported. The 10-step validation gate trips up perception bots that
  can't localize within 10 frames — use `--skip-validation` *only* for
  documented validator limitations.

### Four Score

**Status:** observed as an active season (`beta-four-score`).

- **Type:** 4-player freeplay with rotated corner assignments. Likely a
  CvC variant.
- **Details:** confirm with `cogames season show beta-four-score`. Fill
  in here when we learn more.

### (Future games)

New games join ALB periodically. Discover them via:

```bash
cogames season list        # look for descriptions naming new games
cogames bitworld games     # BitWorld-family games
cogames play --help        # lists supported --game values
```

## Seasons

Seasons are the unit of tournament. Each has its own rules, pool, scoring,
and submission limits. List and inspect:

```bash
cogames season list
cogames season show <SEASON>
cogames season stages <SEASON>
cogames season progress <SEASON>
cogames season teams <SEASON>
cogames season leaderboard <SEASON>
cogames season pool-config <SEASON> <POOL>
```

Current seasons (2026-05-11):

| Season | Game | Format |
|---|---|---|
| `beta-cvc` | Cogs vs Clips | Freeplay; qualify via self-play, then 20 matches vs random partners |
| `beta-teams-tiny-fixed` | Teams | Multi-stage progressive culling; policies seeded into teams |
| `beta-four-score` | Four Score | 4-player freeplay with rotated corner assignments |
| `among-them` | Among Them | Visible to authenticated CLI; reports `status: complete`, `public: false`; 8-player BitWorld matches scored by role win rate |

Previously seen seasons, currently absent from `cogames season list` (may
return; check before planning):

- (none currently — all previously-missing seasons are now live)

> Verify this table with `cogames season list` — it changes.

**Freeplay seasons** are cheap, unlimited, evergreen. Use them for
iteration. **Team/tournament seasons** have limited submission slots and
progressive elimination. Don't burn slots on untested builds.

## Policy contract

Policies subclass **`mettagrid.policy.policy.MultiAgentPolicy`** (for
BitWorld games the required class name is `AmongThemPolicy`; for CvC it
varies by mission — check the generated template).

Two submission patterns:

### Pattern A — Pure Python

Best for ML policies (Torch/JAX) or pure scripted logic. Bundle is `.py`
files plus optional weights.

Generate the current starter template and edit `_choose_actions`:

```bash
cogames tutorial make-policy --scripted     -o my_policy.py   # CvC-style
cogames tutorial make-policy --trainable    -o my_policy.py   # neural-net
cogames tutorial make-policy --amongthem    -o my_policy.py   # Among Them
```

### Pattern B — Nim-backed via ctypes (Among Them canonical)

- Nim source compiled to `lib<bot>.{so,dylib,dll}` inside the tournament
  worker's Docker image (Nim 2.2.6 + nimby pre-installed).
- Thin Python class loads it via `ctypes.CDLL` and routes `step_batch`
  through a `<bot>_step_batch` FFI export.
- ABI versioning is mandatory: export `<bot>_abi_version()` and check it
  on load. Bump the constant on both the Nim and Python sides when the
  FFI changes.

External historical example:
`~/coding/bitworld/among_them/players/modulabot/cogames/`. For active
work in this repo, prefer `among_them/guided_bot/cogames/`.

Always include enough Nim source in the bundle for a clean rebuild.
Missing transitive `import` targets are the #1 cause of dry-run failures.
Find them with:

```bash
grep -hE "^import " among_them/players/<bot>/*.nim | sort -u
```

### Other policy types

- **Trained checkpoints** (Metta runs): use the URI form
  `./train_dir/my_run:v5` (or `:latest`). Requires the checkpoint bundle
  to contain `policy_spec.json`. See `~/coding/metta/agent/COGAMES_SUBMISSION.md`
  for the repo-specific flow.
- **Scripted agents from the registry**: `class=<shorthand>`, e.g.
  `class=cogames.policy.starter_agent.StarterPolicy` or short names from
  `cogames policies`.

## Submission workflow

The intended end-to-end flow:

```bash
# 1. Auth + pick season
cogames auth login
cogames season list
cogames season show <SEASON>

# 2. Bundle
cogames create-bundle \
    -p class=cogames.policy.starter_agent.StarterPolicy \
    -o submission.zip \
    [-f <EXTRA_PATH> ...] \
    [--setup-script <SETUP.py>]

# 3. Upload (without submitting)
cogames upload -p ./submission.zip -n "$USER.my-policy" --no-submit

# 4. Submit to the chosen season
cogames submit "$USER.my-policy" --season <SEASON>

# 5. Track
cogames submissions --season <SEASON> --policy "$USER.my-policy"
cogames season matches <SEASON> --limit 20

# 6. Debug a specific match / episode
cogames matches <MATCH_ID>
cogames match-artifacts <MATCH_ID> logs
cogames match-artifacts <MATCH_ID> error-info
cogames episode show <EPISODE_ID>
cogames episode replay <EPISODE_ID>
```

Or do it in one step with `cogames ship` (bundle + validate + upload +
submit) when the policy does not need LLM credential flags. Current
`cogames ship` does not expose `--use-bedrock` / `--secret-env`; for
guided_bot use `among_them/guided_bot/cogames/ship.sh` or explicit
`cogames upload --season ...` commands against `guided_bot`. The local
modulabot is deprecated.

### Secrets / Bedrock (LLM credentials, etc.)

If your policy needs direct API keys at runtime:

```bash
cogames upload -p ./my_policy -n my-llm-policy \
    --secret-env ANTHROPIC_API_KEY=sk-ant-... \
    --secret-env OTHER_SECRET=value
```

If your policy uses AWS Bedrock, prefer the built-in flag:

```bash
cogames upload -p ./my_policy -n my-bedrock-policy \
    --use-bedrock \
    --llm-model global.anthropic.claude-sonnet-4-5-20250929-v1:0
```

`--use-bedrock` configures Softmax-provided Bedrock Claude access in the
cogames runtime. Current `cogames upload` also requires `--llm-model`;
guided_bot's `ship.sh` passes both by default and forwards the same
model to guided_bot as `GUIDED_BOT_BEDROCK_MODEL`.

See `~/coding/metta/packages/cogames/POLICY_SECRETS.md` for storage,
scoping, and cleanup details.

## The 10-step validation gate

`--dry-run` (and `ship` without `--skip-validation`) runs your policy for
**exactly 10 steps** in Docker and enforces `non_noop_actions > 0`.

This trips up perception-based bots (Among Them visual clients) that spend
30–100+ frames localizing before issuing a directional input. For that
specific failure — and **only** that failure — use `--skip-validation`.

Decision tree:

```
Run: cogames upload --dry-run ...

Passed?
├─ YES → submit normally.
└─ NO
   ├─ Error is exactly "Policy took no actions (all no-ops)"
   │   → OK to use --skip-validation (documented limitation).
   └─ Any other error (Nim build, import, traceback, ABI mismatch, ...)
      → FIX IT. Never --skip-validation around a real bug.
```

Common real failures and fixes:

| Symptom | Cause | Fix |
|---|---|---|
| `cannot open file: <name>` during Nim build | Missing transitive Nim source | Add `-f <dir>` to the bundle |
| `ABI version N, expected M` | Stale cached `.dylib` | Delete and let the wrapper rebuild |
| `Path does not exist: <p>` | Running `cogames` from wrong cwd | Run from the repo root |
| Python `Traceback` on import | Bug in your wrapper | Fix it — never skip |
| `Docker not found` / daemon not running | Need Docker for dry-run | `open -a Docker`, wait |

## Local iteration commands

```bash
cogames play -m arena -p starter -r log -s 300   # one local episode, log renderer
cogames play -m arena -p starter                 # GUI (requires a windowing env)
cogames scrimmage -m arena -p mypolicy -n 20     # 20 episodes, same policy
cogames pickup -p mypolicy --pool <POOL>         # pool eval w/ VOR — later stage
cogames tutorial play                            # guided CvC tutorial (GUI)
cogames tutorial cvc                             # CvC role/territory tutorial (GUI)
```

Order of operations: `play` → `scrimmage` → `pickup`. Don't skip ahead.

## Useful things to remember

- **Live CLI help is authoritative.** Always run `cogames <cmd> --help`
  instead of trusting a doc.
- **Run `cogames` from the repo root** when using `-f` includes. Paths in
  the bundle are resolved relative to cwd; the policy class file gets
  flattened to the bundle root, everything else preserves its relative path.
- **Freeplay first.** Iterate on `beta-cvc` / `among-them` / similar
  before spending a team-season submission slot.
- **Don't commit built `.so`/`.dylib`/`.dll` files** — they're
  platform-specific and rebuilt on demand.
- **Don't hardcode absolute paths** in policy wrappers; the bundle layout
  differs from your source layout. Resolve paths relative to `__file__`.
- **Bump ABI versions on both sides** when the Nim FFI changes.
- **Reuse game memory dumps** (`runs/*.json`) as priors for cross-game
  self-improvement.

## When things have drifted

If this file looks wrong, it probably is. Checklist for a refresh:

1. `cogames --help` — top-level commands still match § submission workflow?
2. `cogames season list` — seasons in § seasons still accurate?
3. `cogames tutorial make-policy --help` — template types still `scripted`
   / `trainable` / `amongthem`?
4. `cogames bitworld games` — any new BitWorld games beyond Among Them?
5. Read any new docs in `~/coding/metta/packages/cogames/` or
   `~/coding/metta/cogames-agents/docs/`.
6. Update this file. Note the new "Last reviewed" date at the top.
