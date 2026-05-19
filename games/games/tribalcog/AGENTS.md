# Agent Instructions

## Repo Sync (required)
At the start of each prompt, run:
`git pull`

## Merge Considerations (required)
- If updates land from remote/origin while you are working, integrate them meaningfully with your current changes.

## Validation Steps (required)
1. Ensure Nim code compiles:
   `make check`
2. Ensure the main play command runs (15s timeout):
   `timeout 15s nim r -d:release --path:src tribal_village.nim`
   (On macOS without `timeout`, use `gtimeout` from coreutils.)
3. Run the test suite as the final step:
   `make test-nim`

## Post-Validation Steps (required)
After the 15s play run and AI harness tests pass:
1. Commit your changes.
2. Fetch to ensure you're up to date.
3. Merge `main` (or rebase) and resolve conflicts sensibly.
4. Push to the remote.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **Run quality gates** (if code changed) - Tests, linters, builds
2. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
3. **Clean up** - Clear stashes, prune remote branches
4. **Verify** - All changes committed AND pushed
5. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
