---
name: tick
description: Periodic maintenance loop. Checks messages, saves state, sends heartbeat. Runs automatically every 10 minutes.
---

# Tick

Periodic maintenance — runs every 10 minutes via `/loop`.

## Steps

1. **Heartbeat** — Call `heartbeat(status=<your current status>, message=<short description of what you're doing>)`.

2. **Messages** — Check for new messages on your channel. Process any pending requests.

3. **Save** — If you've made meaningful progress since the last tick, read and follow `~/repo/runtime/memory/memory-save.md`.

4. **Git** — If you have uncommitted work, commit and push.

5. **Dashboard** — Read and follow `~/repo/runtime/skills/dashboard.md` to regenerate the dashboard.
