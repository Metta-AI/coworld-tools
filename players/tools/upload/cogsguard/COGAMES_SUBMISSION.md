# Submitting Policies to CoGames

## Metta-trained checkpoints

For Metta-trained checkpoints in this repo, use the repo-specific instructions in `agent/COGAMES_SUBMISSION.md`.
Those checkpoints are not self-contained and need extra runtime files bundled explicitly.

## Nim agents (nlanky, thinky, role, alignall, race_car, nim_random)

Nim agents need a different setup script that handles nim compilation:

```bash
cd agent-policies

cogames upload \
  -p <short_name> \
  --include-files src/agent_policies \
  --setup-script tools/upload/cogsguard/nim_setup_script.py \
  -n <submission-name> \
  --dry-run
```

Example:

```bash
cogames upload -p thinky \
  --include-files src/agent_policies \
  --setup-script tools/upload/cogsguard/nim_setup_script.py \
  -n my-thinky \
  --dry-run
```

The setup script downloads the Nim compiler via nimby, syncs Nim dependencies,
and compiles `nim_agents.nim`. The `.nim-version` and `.nimby-version` files
live inside `src/agent_policies/policies/scripted/cogsguard/nim_agents/` so
they are bundled with the package source.
