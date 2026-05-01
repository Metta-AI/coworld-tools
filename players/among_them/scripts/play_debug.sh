#!/usr/bin/env bash
# One-shot: spin up a BitWorld Among Them server filled with N-1
# nottoodumb fillers and one Python modulabot with a live debug
# overlay window (play_watch.py). Use when you want to see exactly
# what one agent is perceiving and deciding in real time.
#
# Usage:
#   scripts/play_debug.sh [N] [duration_seconds] [seed]
#
#   N         total player slots (default 8 — Among Them standard)
#   duration  seconds to keep the session alive (default 600)
#   seed      server seed (default random)
#
# The debug overlay window pops up automatically; the global viewer
# URL is printed so you can also watch the match from the server's
# perspective. Ctrl-C in the terminal tears everything down.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

N=${1:-8}
DURATION=${2:-600}
SEED=${3:-$(( RANDOM % 10000 ))}
MIN_PLAYERS=${N}

VENV_PY="$REPO_ROOT/.venv/bin/python"
SERVER_BIN="$HOME/coding/bitworld/out/among_them"
FILLER_BIN="$HOME/coding/bitworld/out/nottoodumb"
BITWORLD_REPO="$HOME/coding/bitworld"

for bin in "$SERVER_BIN" "$FILLER_BIN" "$VENV_PY"; do
  if [ ! -x "$bin" ]; then
    echo "ERROR: required binary missing or not executable: $bin" >&2
    exit 1
  fi
done

PORT=$("$VENV_PY" -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
RUNDIR=$(mktemp -d -t "modula_debug.XXXXXXXX")
echo "=== modulabot debug harness ==="
echo "  server port : $PORT"
echo "  fillers     : $((N - 1)) (nottoodumb)"
echo "  duration    : ${DURATION}s"
echo "  seed        : $SEED"
echo "  run dir     : $RUNDIR"
echo ""

# Start the server in the bitworld repo so any data-file relative
# lookups resolve. Config mirrors play_eight.sh so match behaviour
# is the same. ``exec`` inside the subshell replaces the bash wrapper
# with the server binary so ``$!`` is the actual server pid — without
# it, killing ``$!`` only kills the subshell and orphans the server.
(cd "$BITWORLD_REPO" && exec "$SERVER_BIN" \
  --address:127.0.0.1 --port:$PORT \
  --config:"{\"seed\":$SEED,\"maxTicks\":$((DURATION * 24 * 2)),\"minPlayers\":$MIN_PLAYERS,\"imposterCount\":2,\"tasksPerPlayer\":8,\"imposterCooldownTicks\":1200,\"voteTimerTicks\":600}" \
  > "$RUNDIR/server.log" 2>&1) &
SERVER_PID=$!
echo "server pid: $SERVER_PID (log: $RUNDIR/server.log)"

# Wait for server listening.
for i in $(seq 1 15); do
  if nc -z 127.0.0.1 $PORT 2>/dev/null; then break; fi
  sleep 0.2
done
if ! nc -z 127.0.0.1 $PORT 2>/dev/null; then
  echo "ERROR: server did not start on port $PORT; see $RUNDIR/server.log" >&2
  kill $SERVER_PID 2>/dev/null
  exit 1
fi
echo "server listening."
echo ""

# Spawn N-1 nottoodumb fillers so the lobby fills to minPlayers.
FILLER_PIDS=()
for i in $(seq 1 $((N - 1))); do
  "$FILLER_BIN" --address:127.0.0.1 --port:$PORT --name:"filler$i" \
    > "$RUNDIR/filler$i.log" 2>&1 &
  FILLER_PIDS+=($!)
  sleep 0.25
done
echo "spawned ${#FILLER_PIDS[@]} fillers."
echo ""

echo "=== LAUNCHING DEBUG WINDOW ==="
echo "  Viewer URL: ws://127.0.0.1:$PORT/global"
echo "             (open your global_client.html and point it there)"
echo "  Debug window opens in the foreground; close window or press"
echo "  q/Esc to stop."
echo ""

_SHUTDOWN_DONE=0
shutdown() {
  # INT/TERM/EXIT can all fire in a single Ctrl-C (SIGINT delivered
  # to the shell, then EXIT on trap completion). Guard against running
  # the teardown twice so we don't spam "done" messages or double-kill
  # pids whose slot has been reused.
  [ "$_SHUTDOWN_DONE" = "1" ] && return
  _SHUTDOWN_DONE=1
  echo ""
  echo "Shutting down…"
  local pids=("${FILLER_PIDS[@]}" "$SERVER_PID")
  # TERM everything that's still alive.
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null
    fi
  done
  # Wait up to ~2s for clean exits — avoids KILLing a process mid-flush.
  for _ in 1 2 3 4 5 6 7 8; do
    local any_alive=0
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then any_alive=1; break; fi
    done
    [ "$any_alive" = "0" ] && break
    sleep 0.25
  done
  # KILL stragglers and confirm. If anything survives KILL, it's either
  # zombied (harmless) or uninterruptible; log so the user knows.
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null
      sleep 0.1
      if kill -0 "$pid" 2>/dev/null; then
        echo "  warning: pid $pid survived SIGKILL (check manually)" >&2
      fi
    fi
  done
  # Reap any remaining backgrounded children so the script doesn't
  # leave zombies behind.
  wait 2>/dev/null || true
  echo "done. Artefacts in $RUNDIR"
}
trap shutdown INT TERM EXIT

# Run play_watch.py in the foreground. Its window is the UI, the
# terminal just shows log output. When the user closes the window
# (or the duration elapses), play_watch exits and the trap above
# tears down the fillers + server.
PYTHONPATH=among_them "$VENV_PY" among_them/scripts/play_watch.py \
  --host 127.0.0.1 --port $PORT --name modulabot-debug \
  --duration "$DURATION" \
  --trace-dir "$RUNDIR/trace" \
  --capture-frames "$RUNDIR/frames.npy"
