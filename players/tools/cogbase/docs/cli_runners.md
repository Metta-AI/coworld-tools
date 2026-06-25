# CLI Runner Reference

How to invoke Claude Code and Codex CLIs programmatically from Python
subprocesses. These are the two LLM runners used in cogbase pipelines.

## Claude Code CLI

**Version**: 2.1.136
**Binary**: `/Applications/cmux.app/Contents/Resources/bin/claude`

### Non-Interactive Invocation

```bash
claude -p "prompt here" [options]
```

The `-p` / `--print` flag runs non-interactively: processes the prompt, prints
the response to stdout, and exits.

### Key Flags for Scripting

| Flag | Purpose |
|------|---------|
| `-p` | Non-interactive mode (required for scripting) |
| `--allowedTools "Read,Edit,Bash"` | Pre-approve tools (no user prompts) |
| `--bare` | Skip hooks, plugins, CLAUDE.md, memory, auto-discovery |
| `--output-format json` | Structured output (`text`, `json`, `stream-json`) |
| `--append-system-prompt "..."` | Add to system prompt |
| `--system-prompt "..."` | Replace system prompt entirely |
| `--model <model>` | Override model (e.g., `opus`, `sonnet`) |
| `--max-budget-usd <amount>` | Spending cap |
| `--add-dir <path>` | Grant tool access to additional directories |

### Working Directory

Claude runs in the current directory of the subprocess. Set via Python's
`subprocess.run(cwd=...)`. Use `--add-dir` to grant access to directories
outside cwd.

### Output Capture

- **text** (default): Response text on stdout
- **json**: `{"result": "...", "session_id": "...", "usage": {...}, "total_cost_usd": ...}`
- **stream-json**: JSONL events as they stream

### Python Example

```python
import subprocess
import json

def run_claude(prompt, *, cwd, allowed_tools=None, system_prompt=None,
               output_format="text", extra_dirs=None):
    cmd = ["claude", "-p", prompt, "--bare"]

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])
    if output_format != "text":
        cmd.extend(["--output-format", output_format])
    if extra_dirs:
        for d in extra_dirs:
            cmd.extend(["--add-dir", d])

    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Claude failed: {result.stderr}")

    if output_format == "json":
        return json.loads(result.stdout)
    return result.stdout
```

### Notes

- Piped stdin capped at 10MB
- `--bare` recommended for automation (deterministic, no side effects)
- Non-zero exit on failure
- `--allowedTools` supports granular patterns: `"Bash(git *)"`, `"Read"`

---

## Codex CLI

**Version**: 0.128.0
**Binary**: `/opt/homebrew/bin/codex`

### Non-Interactive Invocation

```bash
codex exec "prompt here" [options]
```

The `exec` subcommand (alias `e`) runs without the interactive TUI.

### Key Flags for Scripting

| Flag | Purpose |
|------|---------|
| `-C, --cd <dir>` | Working directory for the agent |
| `-s, --sandbox <mode>` | `read-only`, `workspace-write`, `danger-full-access` |
| `--json` | Output events as JSONL to stdout |
| `-o, --output-last-message <file>` | Write final agent message to file |
| `--ephemeral` | Don't persist session files |
| `--skip-git-repo-check` | Allow running outside a git repo |
| `--ignore-user-config` | Skip loading config.toml |
| `--ignore-rules` | Skip execution policy files |
| `-m, --model <model>` | Override model |
| `--add-dir <dir>` | Additional writable directories |
| `--output-schema <file>` | JSON Schema for structured final response |

### Working Directory

```bash
codex exec -C /path/to/project "prompt"
```

### Output Capture

- **Default**: Final agent message on stdout, progress on stderr
- **`--json`**: JSONL event stream on stdout
- **`-o file.md`**: Write final message to specified file

### Sandbox Modes

- `read-only` (default in exec): Can read files, no writes or commands
- `workspace-write`: Can write files within workspace
- `danger-full-access`: Unrestricted (use in sandboxed environments only)

### Python Example

```python
import subprocess

def run_codex(prompt, *, cwd, sandbox="workspace-write", output_file=None,
              model=None, extra_dirs=None):
    cmd = ["codex", "exec", "-C", cwd, "-s", sandbox, "--ephemeral",
           "--skip-git-repo-check"]

    if output_file:
        cmd.extend(["-o", output_file])
    if model:
        cmd.extend(["-m", model])
    if extra_dirs:
        for d in extra_dirs:
            cmd.extend(["--add-dir", d])

    cmd.append(prompt)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Codex failed: {result.stderr}")

    if output_file:
        with open(output_file) as f:
            return f.read()
    return result.stdout
```

### Notes

- Requires git repo by default (override with `--skip-git-repo-check`)
- `--ephemeral` prevents session file clutter
- stderr has progress updates; stdout has the final output
- Prompt can be piped via stdin (use `-` as prompt arg)

---

---

## Model Configuration

### Claude Code

Model is configurable per-invocation:

```bash
claude -p "..." --model opus    # Claude Opus (most capable)
claude -p "..." --model sonnet  # Claude Sonnet (faster, cheaper)
claude -p "..." --model haiku   # Claude Haiku (fastest, cheapest)
```

Aliases (`opus`, `sonnet`, `haiku`) resolve to the latest version of each.
Full model IDs also accepted (e.g., `claude-sonnet-4-6`).

**Default**: Inherits from the user's Claude Code settings (currently Opus).
**Cost per call**: ~$0.01 for a short prompt (observed $0.009-$0.012 in testing).

### Codex

Model is set in `~/.codex/config.toml`:

```toml
model = "gpt-5.5"
model_reasoning_effort = "xhigh"  # low, medium, high, xhigh
```

Override per-invocation:

```bash
codex exec -m gpt-5.5 "..."
```

**Constraint**: When authenticated via ChatGPT account (current setup), model
selection is limited to what the account tier supports. Attempting unsupported
models (e.g., `o4-mini`) produces a 400 error. An API key (`CODEX_API_KEY`)
would unlock the full model roster.

**Current default**: `gpt-5.5` with `xhigh` reasoning effort.

### Pipeline Model Strategy

The `generate_guides.py` script accepts `--runner` to select the draft runner
CLIs and `--claude-model` / `--codex-model` flags to override defaults. This
allows:

- **Single-runner debugging**: `--runner clod` or `--runner codec`
- **Fast/cheap runs** during development: `--claude-model sonnet`
- **High-quality runs** for final output: `--claude-model opus`
- **Codex model overrides**: `--codex-model gpt-5.5`

Runner aliases are `claude`/`clod` and `codex`/`codec`. With one selected
runner, Guide skips synthesis and promotes that runner draft directly to the
final document. Codex reasoning-effort tuning is not exposed by the current
`guide_v1` CLI.

---

## Comparison for Pipeline Use

| Concern | Claude | Codex |
|---------|--------|-------|
| Non-interactive flag | `-p` | `exec` subcommand |
| Working dir | `cwd=` in subprocess | `-C <dir>` |
| Tool permissions | `--allowedTools` | `-s <sandbox>` |
| Output to file | Agent writes via Edit tool | Agent writes via prompt; `-o <file>` is available but not used by `guide_v1` |
| Structured output | `--output-format json` | `--json` (JSONL events) |
| Skip config | `--bare` | `--ignore-user-config --ignore-rules` |
| Extra dirs | `--add-dir` | `--add-dir` |

## Pipeline Pattern

For the current `guide_v1` implementation, the runner invocations are:

**Claude runner:**
```bash
claude -p "<prompt>" \
  --bare \
  --allowedTools "Read,Edit,Bash" \
  --add-dir /path/to/game/source \
  --add-dir /path/to/output
```

**Codex runner:**
```bash
codex exec \
  -C /path/to/output \
  -s workspace-write \
  --skip-git-repo-check \
  --ephemeral \
  "<prompt>"
```

The prompt tells Codex the absolute game source path and the draft output file.
The pipeline reads that file after it is non-empty and stable, falling back to
stdout if the file was not written before Codex exits.

**Synthesizer (Claude):**
```bash
claude -p "<synthesis prompt with both drafts>" \
  --bare \
  --allowedTools "Read,Edit" \
  --add-dir /path/to/output \
  --add-dir /path/to/game/source
```
