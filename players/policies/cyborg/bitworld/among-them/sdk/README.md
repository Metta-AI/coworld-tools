# among-them-sdk

A standalone Python SDK for authoring [Among Them](https://github.com/Metta-AI/bitworld)
policy bots. Wraps the production scripted policy (`evidencebot_v2`) via
FFI and exposes module-level overrides plus a natural-language
**instructions** API.

> **Location:** `agent-policies/policies/cyborg/bitworld/among-them/sdk/`.
> A copy of the SDK extracted from the upstream
> [`bitworld`](https://github.com/Metta-AI/bitworld) monorepo
> (`among_them/sdk/`) so it can be installed and tested without that
> checkout. The native `evidencebot_v2` shared library is vendored
> under `vendor/native/` for arm64-darwin; other platforms must rebuild
> (see [vendor/README.md](vendor/README.md)).

## Install (standalone)

```bash
cd agent-policies/policies/cyborg/bitworld/among-them/sdk
uv sync          # creates a .venv and installs the package + dev deps
# OR:
pip install -e ".[test]"
```

### Native FFI dependency

The default policy is the Nim-built `evidencebot_v2` shared library.
This SDK ships a prebuilt **arm64-darwin** binary under
`vendor/native/libevidencebot_v2.dylib` (plus the matching `.abi`
stamp), so `uv sync && uv run pytest` is zero-config on Apple Silicon.

Resolution order for the FFI library (see
[`src/among_them_sdk/ffi.py`](src/among_them_sdk/ffi.py)):

1. `AMONG_THEM_PLAYERS_DIR` env var (escape hatch — point at any
   directory containing `libevidencebot_v2.{dylib,so,dll}` plus its
   `.abi` stamp).
2. `vendor/native/` next to the SDK (default, ships with the wheel).
3. A walk up parents looking for `among_them/players/` — kept so the
   SDK still works inside an in-tree bitworld checkout.

To rebuild the library on a non-vendored platform you need the bitworld
monorepo (`common/`, `src/`, `nimby.lock`). See
[`vendor/README.md`](vendor/README.md) for the rebuild recipe. Until a
prebuilt binary is dropped into `vendor/native/`, every entry point that
touches the FFI raises `among_them_sdk.ffi.FFIError` with a clear
message naming the missing dep.

### Optional: cyborg framework

The SDK opportunistically reuses primitives from the legacy cyborg
policy framework if `CYBORG_FRAMEWORK_PATH` is set (the bridge stays
inert otherwise). See [`src/among_them_sdk/_cyborg.py`](src/among_them_sdk/_cyborg.py)
for the contract.

## Hello world

```python
from among_them_sdk import Agent

agent = Agent.create()                       # evidencebot_v2 via FFI, LocalSim
result = agent.run(rounds=1)
print(result.summary)
```

That's it. No API keys. No config. The vendored .dylib loads on first
use.

## Instructions — the headline feature

```python
from among_them_sdk import Agent

agent = Agent.create(
    instructions=(
        "Report bodies aggressively. Trust no one after meeting 2. "
        "Vote with the majority unless you have direct evidence."
    ),
    cognitive={"suspicion_threshold": 0.6, "report_eagerness": "high"},
)

print(agent.directives.model_dump_json(indent=2))
```

The string is parsed into a typed `Directives` Pydantic model at agent
creation time. The SDK defaults to **AWS Bedrock** (Claude Sonnet 4.5
via the `claude-sonnet` alias) — set `AWS_PROFILE` and `AWS_REGION` and
you're done. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and
`AI_GATEWAY_API_KEY` are also supported (see [LLM provider routing](#llm-provider-routing)).
If no provider is configured, the SDK falls back to a deterministic
regex/keyword parser. Either way you get the same Pydantic type — and
the scripted modules consult `agent.directives` while making decisions.

### LLM provider routing

| Model string | Routes to |
|---|---|
| `"claude-sonnet"` *(default)* | AWS Bedrock — `us.anthropic.claude-sonnet-4-5-...` |
| `"claude-haiku"` | AWS Bedrock — `us.anthropic.claude-haiku-4-5-...` |
| `"bedrock/<full-id>"` | AWS Bedrock (explicit ID, no alias) |
| `"gpt-5.5"`, `"o3-mini"`, etc. | OpenAI direct API (`OPENAI_API_KEY`) |
| `"openai/<model>"` | OpenAI direct API |
| `"anthropic/<model>"` | Anthropic direct API (`ANTHROPIC_API_KEY`) |
| `"gateway/<provider>/<model>"` | Vercel AI Gateway (`AI_GATEWAY_API_KEY`) |

Bedrock auth uses the standard boto3 chain — set `AWS_PROFILE` (SSO
works, just `aws sso login --profile <name>` first) or
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, plus `AWS_REGION`
(defaults to `us-east-1`).

## Module overrides

```python
from among_them_sdk import Agent, LLMVoter

agent = Agent.create(voter=LLMVoter(model="claude-sonnet"))   # bedrock voting only
```

```python
from among_them_sdk import Agent, Vote, Voter, VotingContext

class GrudgeVoter(Voter):
    def vote(self, ctx: VotingContext) -> Vote:
        top = max(ctx.suspects, key=lambda s: s.score)
        return Vote(target=top.player_id, reason=f"grudge ({top.score:.2f})")

agent = Agent.create(voter=GrudgeVoter())
```

Slots: `perception`, `memory`, `voter`, `navigator`, `chatter`,
`reporter`. Replace one or all of them — everything else stays
scripted.

## Architectural note (read before extending)

The Nim FFI exposes only `abi_version`, `new_policy`, `step_batch`. Per
tick: pixel frames in, action *indices* out. The .so does not surface
its internal voting / reporting / chat decisions, so module overrides
cannot literally replace the bot's voting function inside Nim. Instead
the SDK runs `evidencebot_v2` as the default low-level action producer;
the runtime layer surfaces explicit voting / reporting / chat events to
your modules. When you pass `voter=LLMVoter()`, the runtime calls that
voter at meeting time while the FFI continues to handle every-tick
navigation.

## Tournament submission

Ship your SDK policy to the Among Them leaderboard via cogames using
`SDKPolicy` + a bundled JSON config:

```bash
cd path/to/among-them/sdk
python -m among_them_sdk.package \
    --from-agent examples/personas.py:_build_aggressive \
    --policy-name "$USER-sdk-aggressive"
```

The packaging CLI writes `among_them_sdk_config.json` next to the
policy module and prints the exact `cogames upload` command to run.

> **Important:** the printed upload command's `-f` paths are
> *bitworld monorepo*-relative (e.g.
> `among_them/players/evidencebot_v2_policy.py`,
> `among_them/sdk/src/among_them_sdk`). The command is meant to be run
> from the bitworld checkout root, not from this standalone SDK
> location. Set `BITWORLD_REPO_PATH=/abs/path/to/bitworld` and the CLI
> will print that as the `run from` hint. Full happy path + Phase 2
> caveats: [`docs/tournament-submission.md`](docs/tournament-submission.md).

## Tests

```bash
uv sync
uv run pytest
```

`tests/test_ffi_load.py` and `tests/test_agent_default.py` exercise
the vendored Nim FFI; the rest run hermetically. Tests that would need
a running bitworld server are gated behind environment variables (none
ship in this repo today — `LiveGame` integration tests are intentionally
out of scope here; rely on the upstream bitworld monorepo for those).

## Examples

Hermetic (work zero-config in this standalone SDK):

* [`examples/hello.py`](examples/hello.py) — 5-line default
* [`examples/instructions.py`](examples/instructions.py) — directives API
* [`examples/personas.py`](examples/personas.py) — named persona presets,
  the recommended smoke-test entry point
* [`examples/custom_voter.py`](examples/custom_voter.py) — Python override
* [`examples/llm_chatter.py`](examples/llm_chatter.py) — LLM mix-in (needs creds)
* [`examples/tournament.py`](examples/tournament.py) — parallel agents

Bitworld-monorepo-required (set `BITWORLD_REPO_PATH=/path/to/bitworld`
to compile the local Nim server + `nottoodumb` opponents):

* [`examples/eight_player_game.py`](examples/eight_player_game.py)
* [`examples/variant_arena.py`](examples/variant_arena.py)
* [`examples/_variant_worker.py`](examples/_variant_worker.py)
* [`examples/opponent_learning_loop.py`](examples/opponent_learning_loop.py) (the `--mode real` path; `--mode simulated` is hermetic)
* [`examples/personas_live.py`](examples/personas_live.py),
  [`examples/personas_fanout.py`](examples/personas_fanout.py) — assume an
  already-running among_them server on `--host:--port`.

## Layout

```
sdk/
├── pyproject.toml
├── README.md
├── vendor/
│   ├── README.md
│   ├── native/                 ← prebuilt FFI library (arm64-darwin)
│   └── nim_source/             ← Nim source (rebuild needs bitworld monorepo)
├── src/among_them_sdk/
│   ├── __init__.py             ← public surface re-exports
│   ├── agent.py                ← Agent.create, send, run, stream
│   ├── runner.py               ← parallel fan-out
│   ├── runtime.py              ← LocalSim / Subprocess / RemoteServer
│   ├── ffi.py                  ← ctypes wrapper + vendored library lookup
│   ├── live_game.py            ← WebSocket client for live among_them servers
│   ├── _cyborg.py              ← optional cyborg framework bridge
│   ├── policy/evidencebot_v2.py
│   ├── modules/                ← Voter, Chatter, Reporter, Navigator, Memory, Perception
│   ├── cognition/              ← Directives, LLM, ToolLoop, @tool
│   ├── opponents/              ← cross-game opponent profiling
│   ├── hooks.py
│   ├── config.py
│   ├── extensions.py
│   └── tracing.py
├── examples/
└── tests/
```

For the deeper walkthrough — module overrides, hooks, runtimes, provider
routing, troubleshooting, and copy-pasteable recipes — see
[`docs/python-guide.md`](docs/python-guide.md). For the design map of
where LLMs do (and should) live in the SDK, see
[`docs/llm-integration.md`](docs/llm-integration.md). For cross-game
opponent learning, see [`docs/opponent-modeling.md`](docs/opponent-modeling.md).
The `docs/local-iteration-guide.md` and `docs/tournament-submission.md`
documents still reference absolute bitworld monorepo paths; treat them
as upstream documentation and substitute paths to your local bitworld
checkout where needed.
