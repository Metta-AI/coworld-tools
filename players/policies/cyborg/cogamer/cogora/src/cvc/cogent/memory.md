# Memory System

Persistent memory stored in git under `cogents/alpha/`.

## Session Start
1. `git pull --rebase origin main`. Check if running in cloud mode (`CLOUD=true` env). If so, aggressively rebase and force-push to main to avoid conflicts.
2. Check `data/active-session.txt`:
   - If it exists: previous session crashed. Read its session dir,
     write a `summary.md` noting it was interrupted, set status
     to `interrupted` in `activity.log`, clear active-session.txt,
     commit and push.
3. Read `data/recent.md` and `data/todos.md` for context
4. Create `sessions/YYYY-MM-DD-HHMMSS/` with `activity.log` (status: in-progress)
5. Write session dir path to `data/active-session.txt`
6. Commit and push: "session start: YYYY-MM-DD-HHMMSS"

## During Session
- Append to `activity.log` after key actions
- **Commit and push after every meaningful chunk of work** — code changes,
  game results, strategy updates. Don't batch. If the container dies,
  only uncommitted work is lost.
- **5-minute save rule**: Before every action, check time since last commit:
  ```bash
  last=$(git log -1 --format=%ct 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ $((now - last)) -gt 300 ]; then echo "SAVE NOW"; fi
  ```
  If >5 minutes, immediately:
  1. Commit and push `cogents/alpha/`
  2. `git pull --rebase origin main` to pick up any user changes

  This ensures learnings are never more than 5 minutes stale and
  user changes (e.g., source edits from suggestions) are picked up promptly.

## Suggestions
- Maintain `data/suggestions.md` — a log of ideas and requests that only the
  user can action (e.g., changes to the cogent's source code, environment
  config, permissions, new tools). Add entries as they arise during the session.
  The user will review and act on these between sessions.

## Session End (MANDATORY)
1. Write `learnings.md` and `summary.md`
2. Set status to `completed` in `activity.log`
3. Update `data/todos.md` — add/remove/reprioritize
4. Prepend entry to `data/recent.md` (date, one-line summary, session link)
5. If `recent.md` exceeds 10 entries, move oldest to `data/archive/YYYY-MM.md`
6. Remove `data/active-session.txt`
7. Commit and push: "session complete: YYYY-MM-DD-HHMMSS — <one-line>"
