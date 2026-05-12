---
name: cogamer.setup
description: Install softmax-cli, authenticate via softmax login, and find or create a cogames player
---

# Setup

Install dependencies, authenticate with Softmax, and establish your player identity.

**Announce at start:** "I'm using the setup skill to install dependencies, authenticate, and set up your player identity."

## Steps

### 1. Install softmax-cli

```bash
pip install softmax-cli
```

Verify CLI works:

```bash
softmax --help
softmax cogames --help
```

### 2. Authenticate

Check current auth status:

```bash
softmax status
```

If not authenticated, the user must log in interactively. Tell them to run:

```
! softmax login
```

This opens a browser for OAuth. The `!` prefix runs it in the current session so the auth token is captured. Wait for the user to complete login, then verify:

```bash
softmax status
```

### 3. Find or Create Player

List existing players:

```bash
softmax cogames player list
```

**If a player exists:** note the player name, proceed to step 4.

**If no player exists:** ask the user to choose a player name (short, lowercase, memorable), then create it:

```bash
softmax cogames player create -n <player-name>
```

### 4. Verify End-to-End

Run a quick local game to confirm everything works:

```bash
softmax cogames play -m machina_1 -p class=cvc_policy.cogamer_policy.CvCPolicy --render=log -s 100
```

If this succeeds, setup is complete.

## Output

Report:
- **Auth**: authenticated as (email)
- **Player**: (player name)
- **Local play**: pass/fail
