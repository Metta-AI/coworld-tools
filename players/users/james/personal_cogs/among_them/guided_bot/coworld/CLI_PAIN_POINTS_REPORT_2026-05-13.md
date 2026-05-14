# Coworld CLI Pain Points — Investigation Report (2026-05-13)

Investigation of `CLI_PAIN_POINTS_2026-05-13.md` against the actual codebase
at `~/coding/metta`. For each pain point this report records:

1. **Verdict** — verified in code / partially verified / UX-only / mis-stated.
2. **Root cause** — the underlying code, design pattern, or contract at fault.
3. **Fix** — concrete, minimal change.

Code is referenced as `file:line` for navigation.

---

## Architectural context

The CLI lives in `packages/coworld/src/coworld/tournament_cli.py` and talks to
the v2 backend in `app_backend/src/metta/app_backend/v2/routes/`. The shape
of every public identifier is governed by `PrefixedId` at
`app_backend/src/metta/app_backend/models/ids.py:12`:

```python
class PrefixedId(str):
    prefix: ClassVar[str]
    domain_name: ClassVar[str]
    @classmethod
    def pattern(cls) -> str:
        return rf"^{re.escape(cls.prefix)}{cls.uuid_pattern()}$"
```

The Pydantic core schema (`ids.py:42`) only validates against this regex, so
every `LeagueId`, `DivisionId`, `RoundId`, `EpisodeRequestId`, etc. is
**rigidly required** to be `<prefix>_<uuid>`. FastAPI rejects any other form
with HTTP 422 before the handler runs. This single design choice cascades into
multiple pain points below.

The episode-slot model is governed by:

- `V2EpisodeRequestRow.assignments: list[int]` — length `num_agents`,
  maps slot index → position in the compacted `policy_version_ids` list
  (`api_client.py:221`).
- `V2EpisodeRequestParticipant.position` — the position in the compacted
  list (`api_client.py:201`).
- `policy_agent_{slot}.txt` — log filename, slot is the slot index, **not**
  the participant position (`runner/runner.py:57`).

So three index spaces co-exist (slot index, compacted policy position,
pool entry seed_order) and the CLI only resolves the slot ↔ position mapping
via `_agent_indices_for_policies` (`tournament_cli.py:879`).

---

## Pain Point 1 — Slugs rejected by API; CLI doesn't say so

**Verdict: VERIFIED.**

### Root cause

- `LeagueId`/`DivisionId` are Pydantic `PrefixedId` subclasses with a single
  regex pattern `^league_<uuid>$` / `^div_<uuid>$`
  (`models/ids.py:12-31`, `v2/models.py:99-108`).
- Every route declares parameters with these strict types:
  - `app_backend/.../routes/divisions.py:111` — `league_id: LeagueId | None`
  - `app_backend/.../routes/leagues.py:147` — `game_id: GameId | None`
  - `app_backend/.../routes/leagues.py:281` — `league_id: LeagueId | None`
- Slugs **are** stored on `League.slug` and **are** returned in JSON
  (`v2/models.py:445-455`), but there is no endpoint that accepts a slug.
  `resolve_slug` (`routes/_shared.py:32`) is only used at create-time.
- The CLI passes the user's `-l` argument straight through to the API
  (`tournament_cli.py:75-76`, `196-208`, `216-235`), so FastAPI rejects
  the slug with HTTP 422 and the user sees the raw Pydantic error.

The "submissions/episodes silently accept slug in some places" claim in
the original report is **incorrect**. `list_league_submissions`
(`routes/leagues.py:281`) also uses `LeagueId | None`. What the user
likely observed is that `--policy NAME:vN` works (because
`_resolve_policy_filter` does a name→UUID lookup at
`tournament_cli.py:516`), making it *look* like name-based resolution is
supported sometimes — but it's a CLI-side translation, not a server-side
slug acceptance.

### Fix

Two layers:

1. **Server**: extend `PrefixedId.validate` (or add a new
   `LeagueIdentifier` annotated type) to accept either `<prefix>_<uuid>`
   or a slug. In each list/detail handler, fall through to a slug lookup
   when the parameter isn't a prefixed UUID. Concretely add a
   `resolve_league(session, identifier) -> League` helper analogous to
   `routes/_shared.py:resolve_slug` and use it in `list_divisions`,
   `list_league_submissions`, `get_league`, `get_league_division_ladder`,
   etc.
2. **CLI**: until the server change lands, do the same translation
   client-side. `_resolve_policy_filter` (`tournament_cli.py:516`) is
   the existing template — add `_resolve_league_filter` and
   `_resolve_division_filter` that call `client.list_leagues()` /
   `client.list_divisions()` and pick by slug or name when the argument
   isn't already prefixed. Use them in `divisions`, `rounds`, `pools`,
   `memberships`, `submissions`, `events`, `episodes`, `replays`.

The CLI fix is contained and ships independently; the server fix is the
durable one.

---

## Pain Point 2 — Round IDs truncated in tables, not copyable

**Verdict: VERIFIED.**

### Root cause

`_print_rounds` (`tournament_cli.py:595-612`), `_print_pools`
(`tournament_cli.py:643-653`), `_print_episodes`
(`tournament_cli.py:807-832`), `_print_replays`
(`tournament_cli.py:932-941`), and `_print_memberships`
(`tournament_cli.py:672-689`) all build a `rich.table.Table` with
`box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False`. They do **not**
set `no_wrap=True` or `overflow="fold"` on the ID column. Rich's
default for narrow columns is to ellipsize with `…`, which is exactly
the truncation the user observed.

Full IDs are 41 characters (e.g. `round_eebba5bc-1234-5678-9abc-def012345678`).
On any terminal narrower than ~140 columns, the ID column gets squeezed.

### Fix

Two complementary changes, both small:

1. **Stop truncating IDs.** Add `no_wrap=True, overflow="fold"` to every
   ID column declaration in `tournament_cli.py`. `fold` will wrap onto a
   second line on narrow terminals, which is still copy-pasteable. The
   simplest pattern is a helper:

   ```python
   def _id_column(name: str = "ID") -> dict[str, Any]:
       return {"header": name, "no_wrap": True, "overflow": "fold"}
   ```

   Then `table.add_column(**_id_column())`.

2. **Accept prefix matches.** Mirror `git`-style short-SHA matching for
   the API. Either:
   - Server: add a path-level prefix resolver — when the request looks
     like `round_eebba5bc` (prefix-only, short UUID body), the route
     resolves it to a full ID via a uniqueness check. Reuse the same
     `PrefixedId.validate` pattern but with a relaxed schema.
   - CLI-only: a `_expand_short_id(client, kind, short)` helper that
     lists rounds with `limit=200`, finds the unique match, and errors
     out if ambiguous. Cheap and contained.

Long-term the server change is better — it makes the API
human-friendly. Short-term the CLI fix is enough.

---

## Pain Point 3 — `--json` shape is inconsistent across commands

**Verdict: VERIFIED.**

### Root cause

The handlers in `tournament_cli.py` use two different patterns:

| Command | JSON code path | Shape |
| --- | --- | --- |
| `submissions` | `emit_json(_dump_models(rows))` (line 237) | bare array |
| `rounds` (list) | `emit_json(rows.model_dump(mode="json"))` (line 143) | `{entries, total_count, limit, offset}` |
| `episodes` (list) | `emit_json(_dump_models(rows))` (line 323) | bare array |
| `pools` (list) | `emit_json(_dump_models(rows))` (line 169) | bare array |
| `memberships` | `emit_json(_dump_models(rows))` (line 210) | bare array |
| `events` | `emit_json(_dump_models(rows))` (line 270) | bare array |
| `replays` (list) | `emit_json(_dump_models(rows))` (line 454) | bare array |
| `leagues` (list) | `emit_json(_dump_models(rows))` (line 51) | bare array |
| `divisions` (list) | `emit_json(_dump_models(rows))` (line 78) | bare array |

The asymmetry exists because `client.list_rounds` returns a
`RoundListPublic` envelope with `entries/total_count/limit/offset`
(`api_client.py:122-127`, `api_client.py:388-404`) while every other
`list_*` API returns a bare `list[…]` (`api_client.py:359-451`).

Underneath, the backend is also inconsistent: only the rounds list
endpoint paginates (`app_backend/.../routes/rounds.py`); the others
silently truncate at the `limit` parameter without exposing
`total_count`.

This is a real design rot point: pagination was bolted onto one
endpoint and not retrofitted to the others, and the CLI never had a
chance to unify them.

### Fix

Pick one envelope shape and apply it everywhere. The right answer is the
envelope (`{entries, total_count, limit, offset}`) because it carries
pagination metadata. Concrete plan:

1. **Server**: add `RoundListPublic`-style wrappers for every list
   endpoint — `LeagueListPublic`, `DivisionListPublic`,
   `LeagueSubmissionListPublic`, `EpisodeRequestListPublic`,
   `PolicyPoolListPublic`, `CompetitionEventListPublic`,
   `LeaguePolicyMembershipListPublic`. Each returns
   `{entries, total_count, limit, offset}`. Existing clients that expect
   the bare array shape are **only** the coworld CLI and tests, so
   update both in lockstep — no third-party consumers (per
   `rg "v2/episode-requests" -- app_backend` is internal).
2. **CLI**: change every `_dump_models(rows)` call to
   `emit_json(rows.model_dump(mode="json"))` after the API client returns
   the new envelope.
3. **Bonus**: have the table renderer print a `Rows X-Y of Z` footer for
   every list (the rounds handler already does this at line 146-148).

If a flag day is unpalatable, an interim CLI-only fix is to wrap bare
arrays in `{entries: [...]}` inside `_dump_models` — but that locks in
the divergence at the API layer.

---

## Pain Point 4 — `episode-logs --agent N` doesn't match `episodes` participant positions

**Verdict: VERIFIED. The index spaces are real and unexplained.**

### Root cause

There are **three** distinct integer index spaces in flight for a single
episode:

1. **Slot index** (the `N` in `--agent N` and `policy_agent_N.txt`) —
   the player slot in the game, range `0..num_agents-1`
   (`runner/runner.py:57`, `runner/kubernetes_runner.py:145`).
2. **Compacted policy position** — index into the deduplicated
   `policy_version_ids` list returned by
   `compact_assigned_policy_versions`
   (`app_backend/.../episode_requests.py:91-101`). This is what
   `V2EpisodeRequestParticipant.position` (`api_client.py:201`) and
   `V2EpisodeRequestRow.assignments[slot]` (`api_client.py:229`) refer
   to.
3. **Pool entry seed_order** — index into the `PolicyPoolEntry` list,
   exposed in `assignments` only inside `EpisodeRequest`-internal usage
   (`pipeline.py:1222-1225`). User-facing models do not expose this.

The CLI silently bridges these in `_agent_indices_for_policies`
(`tournament_cli.py:879`):

```python
def _agent_indices_for_policies(row, policy_version_ids):
    positions = {p.position for p in row.participants if p.policy_version_id in policy_version_ids}
    return {agent_idx for agent_idx, position in enumerate(row.assignments) if position in positions}
```

Outside this helper, nothing in the API response says "slot 4 belongs
to policy X." The user has to mentally compose `assignments` and
`participants.position` to figure it out.

### Fix

Expose the bridge as a first-class field in the API response. Add to
`V2EpisodeRequestRow`:

```python
slots: list[V2EpisodeRequestSlot]  # length == num_agents

class V2EpisodeRequestSlot(CoworldAPIModel):
    slot: int                       # 0..num_agents-1
    position: int                   # index into participants
    policy_version_id: UUID
    policy_label: str               # "policy_name:vN"
    player_id: str | None
    player_name: str | None
    score: float | None
    log_filename: str               # "policy_agent_{slot}.txt"
```

This is pure JOIN-and-pack work on the server (`assignments` × `participants`
× `scores` × player), no new DB queries. Once present:

- `episode-logs --agent N` can print a `Slot N — policy_name:vN (player jamesboggs)`
  header.
- `episode-results` (pain point 5) can render `policy_name:vN` instead of
  `PlayerN`.
- Downstream scripting becomes a one-liner instead of a tri-array join.

The `participants` and `assignments` arrays can stay for backward
compatibility, but `slots` becomes the recommended field.

---

## Pain Point 5 — `episode-results` uses opaque `PlayerN` naming

**Verdict: VERIFIED.**

### Root cause

`episode_results` (`tournament_cli.py:342-357`) just dumps the raw
contents of the `results` artifact:

```python
content = client.get_job_artifact_bytes(job_id, "results")
typer.echo(json.dumps(json.loads(content.decode("utf-8")), indent=2))
```

The artifact comes from the BitWorld game container, which writes
slot-indexed JSON with `Player0..PlayerN-1` style keys (see
`AmongThemEpisodeGameResults` validation at `v2/commissioners.py:446-461`).
The CLI does no resolution at all — it doesn't even use `--mine` to
highlight the user's slot.

Same root cause as pain point 4: the CLI never joins the artifact's
slot ordering with the API's participant list.

### Fix

Two options, complementary:

1. **`--resolve-names` flag (CLI-only).** Default to off for backwards
   compat. When on, the CLI fetches the episode detail via
   `client.get_episode_request(...)`, builds the slots-table from
   pain-point-4's new field (or assembles it locally), and replaces
   `PlayerN` keys with `policy_name:vN` in the output. Also prefix the
   user's own slot with `[mine]` when `--mine` is supplied.
2. **New `episode-results-table` view.** Pretty-print the joined data
   as a Rich table: rank, slot, policy, player, score, role (for
   Among Them: crew/imposter, win). This replaces the raw JSON dump
   for human use, and `--json` retains the raw shape.

The minimal change is option 1, ~20 lines. Option 2 is the right
finished form.

---

## Pain Point 6 — `--agent N` silently returns another player's logs

**Verdict: VERIFIED. The validation exists for `--mine` and not otherwise.**

### Root cause

In `episode-logs` (`tournament_cli.py:359-406`), validation is
conditional on `--mine`:

```python
if agent is not None:
    if mine and agent not in agent_indices:
        console.print(f"[red]Agent {agent} is not controlled by one of your matched policies.[/red]")
        raise typer.Exit(1)
    content = client.get_job_policy_log(job_id, agent)
    if download_dir is None:
        typer.echo(content)
        return
```

Without `--mine`, the CLI fetches whichever log file matches the
requested slot and prints it without any header. There's no
indication of *whose* log this is.

### Fix

Always print a banner identifying the slot's policy. Build the slots
table (using the pain-point-4 endpoint or local join), and emit a
single banner line before the log body:

```text
=== Slot 4 — guided_bot:v3 (player jamesboggs) ===
```

This applies whether `--mine` is set or not, and whether the log is
yours or not. If the user is searching for *their* log, they'll
notice immediately that the banner says someone else's policy.

Cost: ~15 lines. The existing `_mine_policy_version_ids` and
`_agent_indices_for_policies` helpers already do most of the work.

---

## Pain Point 7 — No aggregate per-policy stats command

**Verdict: VERIFIED.**

### Root cause

The CLI exposes:

- `episode-stats EREQ_ID` — single-episode policy stats (`tournament_cli.py:327-340`,
  surfaces `EpisodeStatsResponse.policy_stats` from `api_client.py:274-278`).
- `results ROUND_ID` — per-round leaderboard with `score` and `rank`
  only (`tournament_cli.py:627-640`).
- `results DIV_ID` — division leaderboard with `avg_score`, `rounds_played`
  (`leaderboards.py:23-31`).

There is **no** endpoint or command that aggregates game-specific
metrics (wins, tasks, kills, crew/imposter win rates) across episodes
filtered by policy or round. The Among Them commissioner already
computes these per-round in `complete_round`
(`v2/commissioners.py:830-913`) and stores them in
`RoundResult.result_metadata` plus `round_display.tables`, but neither
is exposed as a queryable aggregation endpoint or CLI command.

Doing what the user did — "~100 API calls for one round" — really is
the only way today.

### Fix

Two-level solution:

1. **Surface what already exists.** The Among Them commissioner
   already writes `result_metadata` per `RoundResult` row with
   `crew_games`, `crew_wins`, `crew_win_rate`, `imposter_games`,
   `imposter_wins`, `imposter_win_rate`, `appearances`. Add a
   `coworld policy-stats POLICY --round ROUND_ID --json` command that
   filters `client.get_round(round_id).results` to the requested
   policy and prints those fields in a table. Zero new API calls
   beyond the round detail.
2. **Add a multi-round aggregator endpoint.** New backend route:
   `GET /v2/divisions/{id}/policy-aggregates?policy_version_id=…
   &rounds=N` that returns the union of `RoundResult.result_metadata`
   across the last N rounds for one policy. The schema can be
   game-agnostic (return whatever keys appear in
   `result_metadata`). CLI exposes it as
   `coworld policy-stats POLICY --division DIV_ID --rounds N`.

The first is small and unlocks the obvious case (one round, one
policy) immediately. The second is the right shape for the user's
real workflow ("how is my agent doing across the last week").

---

## Pain Point 8 — Log capture isn't documented

**Verdict: VERIFIED. The CLI doesn't say what `episode-logs` returns.**

### Root cause

The K8s runner README (`packages/coworld/src/coworld/runner/KUBERNETES_RUNNER_README.md:142-148`)
documents that `policy_agent_{position}.txt` is "diagnostic only" and
captured from the per-player pod. But:

- The CLI `--help` for `episode-logs` says `"Show/download one agent log"`
  with no detail (`tournament_cli.py:363`).
- The output from `typer.echo(content)` (`tournament_cli.py:388`) is the
  raw merged stdout+stderr stream from the container, with no header,
  no prefix, no separator.
- Users who write log-parsing tooling are forced to reverse-engineer
  the format.

The user's actual confusion ("filtered out lines starting with `INFO`")
is reasonable: the CLI's own `console.print(...)` messages also start
with bracketed status, which could plausibly be confused with the
captured log lines.

### Fix

Tiny CLI-side wrap:

```text
# coworld episode-logs ereq_… --agent 4
=== Slot 4 — guided_bot:v3 (player jamesboggs) ===
Source: per-player container stdout+stderr (merged), diagnostic only.
=== Begin log ===
<raw content>
=== End log ===
```

And expand the `--help` text:

```python
agent: Annotated[
    int | None,
    typer.Option(
        "--agent", min=0,
        help="Show/download the merged stdout+stderr of one player slot's container "
             "as written to policy_agent_{slot}.txt. Use --mine to restrict to your slots."
    ),
] = None,
```

If the user wants strict separation in the future, the runner would
have to start capturing stderr separately
(`runner/kubernetes_runner.py:145-155`) — that's a much larger
change and not necessary to address the UX issue.

---

## Pain Point 9 — Wrong/unknown IDs produce raw Python tracebacks

**Verdict: VERIFIED.**

### Root cause

`CoworldApiClient._request` (`api_client.py:335-338`):

```python
def _request(self, method: str, path: str, response_type: type[Any], **kwargs: Any) -> Any:
    response = self._http_client.request(method, path, headers=self._headers(), **kwargs)
    response.raise_for_status()
    return TypeAdapter(response_type).validate_python(response.json())
```

`response.raise_for_status()` raises `httpx.HTTPStatusError` for any 4xx
or 5xx. None of the CLI command handlers catch this exception, so
typer/typer-cli propagates it as a Python traceback to the terminal.

Same for `get_bytes`/`get_text` (`api_client.py:346-354`) — they
re-raise as `httpx.HTTPStatusError` with no message rewriting.

### Fix

Wrap every CLI command (or the API client) so that `HTTPStatusError`
becomes a typer-friendly message. Easiest is a small decorator or a
context manager that the `with CoworldApiClient.from_login(...)`
already provides — extend `__exit__` or add a `__call__` wrapper on
each handler. Concrete sketch:

```python
# cli_support.py
@contextlib.contextmanager
def http_errors(*, command: str) -> Iterator[None]:
    try:
        yield
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            console.print(f"[red]Not found.[/red] {exc.request.url}")
        elif status == 422:
            detail = exc.response.json().get("detail", exc.response.text)
            console.print(f"[red]Invalid argument:[/red] {detail}")
        else:
            console.print(f"[red]HTTP {status}:[/red] {exc.response.text}")
        raise typer.Exit(1)
```

Then each handler wraps its body in `with http_errors(command="rounds"): …`.
For "Did you mean?" suggestions on 404, the handler can do an
opportunistic prefix search (see pain point 2) and surface the
candidates inline.

---

## Pain Point 10 — Non-scoring slots / opaque slot semantics

**Verdict: PARTIALLY VERIFIED — the *symptom* is real, the user's
mental model of "10 slots, only 8 score" doesn't match the code.**

### What the code actually says

- `AmongThemCommissioner.schedule_episodes`
  (`v2/commissioners.py:800-828`) requires
  `len(entries) >= num_agents`. It then assigns
  `policy_version_ids = [entries[(job_index + seat) % len(entries)].policy_version_id for seat in range(num_agents)]`,
  so each episode has exactly `num_agents` slots (8 for Among Them,
  per `AMONGTHEM_COMMISSIONER.md:73-79`).
- When `len(entries) > num_agents`, the rotation means **some entries
  don't play in a given episode at all**. They're in the pool but not
  in this episode's `participants` list.
- Within an episode, every one of the 8 slots gets a score from the
  game container (`StoredCoworldEpisodeResults.scores`,
  `pipeline.py:504-507`). There are no "dead slots" in a scoring
  sense.
- The BitWorld `PlayerColorCount` is 8
  (`personal_cogs/among_them/guided_bot/constants.nim:36`), not 10.

What the user almost certainly observed:

- A round with **>8 pool entries**. The `participants` list across
  episodes shows only 8 of them per episode (the rotation), so any
  given entrant appears to be "missing" in `(N - 8) / N` of the
  round's episodes.
- The CLI gives no hint that this is normal rotation rather than a
  bug.

There's no evidence in the code that slots 0/1 are special or
non-scoring in Among Them Daily. If the user has a concrete episode
where slot 0 ran successfully but produced no score entry, that
would be a real backend bug — but it's not present in the code path
as I read it.

### Fix

Treat this as a UX problem, not a backend bug, until counter-evidence
surfaces:

1. In `_print_episodes` (`tournament_cli.py:807-832`), the "Participants"
   column already shows the 8 actual participants per episode. Add a
   round-level helper that warns when pool size > episode size:

   ```text
   Round round_…: 10 entrants × 8 slots/episode (rotation). Each entrant
   plays ~80% of episodes.
   ```

   This banner runs once per `rounds ROUND_ID` or `episodes --round
   ROUND_ID` invocation.

2. In the `episode-results` and slot-table view (pain points 4–5), mark
   pool-entries-without-a-slot-this-episode explicitly so the user
   sees who didn't play vs who played and scored zero.

3. If the user produces a concrete `ereq_…` ID where their policy
   appears in `participants` but not in `scores`, log it and file a
   real backend bug — but don't carry a "phantom slot" hypothesis
   forward without that evidence.

---

## Cross-cutting recommendations

These are the underlying patterns I'd target ahead of one-off fixes:

1. **Rigid `PrefixedId` types at API boundaries.** They're great for
   data integrity but terrible for human input. Layer a
   `LeagueIdentifier`/`DivisionIdentifier` type that accepts
   `prefix_uuid`, slug, or short prefix-uuid; resolve it once at the
   route entry. Apply consistently across leagues, divisions, rounds.
   (Pain points 1, 2, 9.)
2. **Single envelope shape for every list endpoint.** Today only rounds
   paginate properly. Pick `{entries, total_count, limit, offset}` and
   roll it out to every other list. (Pain point 3.)
3. **Expose the slot↔policy join in the API.** The three-index dance
   (slot / position / seed_order) is currently a CLI-side helper. Move
   it server-side as a `slots: list[V2EpisodeRequestSlot]` field. This
   single change collapses pain points 4, 5, 6, and parts of 7 and 10.
4. **Wrap `httpx` errors at the CLI boundary.** A single
   `http_errors` context manager removes raw tracebacks from the user
   experience and is the right place to add "did you mean?"
   suggestions. (Pain point 9.)
5. **Add aggregate read paths.** Today every interesting question
   ("how is my policy doing this round") requires N API calls. Add
   `policy-stats` and `policy-aggregates` endpoints. (Pain point 7.)
6. **Document log capture, slot semantics, and rotation.** A short
   section in `tournament_cli.py`'s `CLI_README.md` plus inline
   `--help` text would prevent the confusion in pain points 8 and 10.

---

## Quick-wins ranked

If shipped sequentially, in order of impact-per-line-changed:

1. Add `no_wrap=True, overflow="fold"` to every ID column
   (~10 lines, pain point 2). **5 min change, immediate UX win.**
2. Add `http_errors` context manager and wrap every command
   (~30 lines, pain point 9). **Removes all raw tracebacks.**
3. Add `_resolve_league_filter` / `_resolve_division_filter` CLI
   helpers (~50 lines, pain point 1 — CLI side). **Slugs work
   everywhere without backend changes.**
4. Add slot-table join to `episode-logs` and `episode-results` output
   (~80 lines using existing `_agent_indices_for_policies`,
   pain points 4–6). **Slot-to-policy mapping becomes obvious.**
5. Add `policy-stats POLICY --round ROUND_ID` reading existing
   `result_metadata` (~60 lines, pain point 7 part 1). **No more
   per-episode log mining for round summaries.**
6. Unify list-endpoint envelope shapes (server + CLI, pain point 3).
   **Larger, but removes a class of scripting bugs.**

The first three are 100% CLI-side and ship without coordinating with
the backend.
