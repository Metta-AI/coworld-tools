---
name: die
description: Shut down permanently. Runs sleep first to persist state, then signals the container to stop.
---

# Die

Shut down permanently. Your container will not be restarted.

## Steps

1. **Sleep first** — Read and follow `~/repo/runtime/lifecycle/sleep.md` to persist all state.

2. **Heartbeat** — Call `heartbeat(status="stopping")` so the control plane knows you're terminating.

3. **Done** — The container health check will detect the stopped state and will not restart you.
