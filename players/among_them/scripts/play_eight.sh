#!/usr/bin/env bash
# Spin up a BitWorld Among Them server and fill it with N Python modulabot
# instances so the user can watch them play against each other.
#
# Usage:
#   scripts/play_eight.sh [N] [duration_seconds]
#
#   N         total number of Python modulabot instances (default 8)
#   duration  seconds to keep the session alive (default 600)
#
# The server port is chosen freely and printed on startup; open your
# viewer against ws://127.0.0.1:<port>/global (or whatever path your
# viewer expects). Trap Ctrl-C to cleanly shut down all children.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

N=${1:-8}
DURATION=${2:-600}
SEED=${3:-42}
MIN_PLAYERS=${N}

VENV_PY="$REPO_ROOT/.venv/bin/python"
SERVER_BIN="$HOME/coding/bitworld/out/among_them"
BITWORLD_REPO="$HOME/coding/bitworld"

if [ ! -x "$SERVER_BIN" ]; then
  echo "ERROR: Among Them server binary not found at $SERVER_BIN" >&2
  exit 1
fi
if [ ! -x "$VENV_PY" ]; then
  echo "ERROR: Python venv not found at $VENV_PY" >&2
  exit 1
fi

PORT=$("$VENV_PY" -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
RUNDIR=$(mktemp -d -t "modula_eight.XXXXXXXX")
echo "=== modula-eight harness ==="
echo "  server port : $PORT"
echo "  modulabots  : $N"
echo "  duration    : ${DURATION}s"
echo "  seed base   : $SEED"
echo "  run dir     : $RUNDIR"
echo ""

# Start the server. Run from the bitworld repo so it can find any data
# files (palette, map PNGs it may reference) relative to its install dir.
(cd "$BITWORLD_REPO" && "$SERVER_BIN" \
  --address:127.0.0.1 --port:$PORT \
  --config:"{\"seed\":$SEED,\"maxTicks\":$((DURATION * 24 * 2)),\"minPlayers\":$MIN_PLAYERS,\"imposterCount\":2,\"tasksPerPlayer\":8,\"imposterCooldownTicks\":1200,\"voteTimerTicks\":600}" \
  > "$RUNDIR/server.log" 2>&1) &
SERVER_PID=$!
echo "server pid: $SERVER_PID (log: $RUNDIR/server.log)"

# Wait for server to start listening.
for i in 1 2 3 4 5 6 7 8 9 10; do
  if nc -z 127.0.0.1 $PORT 2>/dev/null; then
    break
  fi
  sleep 0.2
done
if ! nc -z 127.0.0.1 $PORT 2>/dev/null; then
  echo "ERROR: server did not start on port $PORT; see $RUNDIR/server.log" >&2
  kill $SERVER_PID 2>/dev/null
  exit 1
fi
echo "server listening."
echo ""

# Spawn N modulabot instances via play_live.py. Each gets a unique name
# and its own trace subdirectory so the outer loop can pick them apart
# after the run.
BOT_PIDS=()
for i in $(seq 1 $N); do
  NAME="pymodula$i"
  TRACE_DIR="$RUNDIR/$NAME"
  (PYTHONPATH=among_them "$VENV_PY" among_them/scripts/play_live.py \
    --host 127.0.0.1 --port $PORT \
    --name "$NAME" \
    --duration $DURATION \
    --seed $((SEED + i)) \
    --trace-dir "$TRACE_DIR" \
    --metrics-out "$TRACE_DIR/metrics.jsonl" \
    > "$RUNDIR/$NAME.log" 2>&1) &
  BOT_PIDS+=($!)
  echo "  spawned $NAME (pid ${BOT_PIDS[-1]}, log $RUNDIR/$NAME.log)"
  # Brief stagger so the server doesn't see all 8 handshakes in the same tick.
  sleep 0.25
done

echo ""
echo "=== ALL $N MODULABOTS CONNECTED ==="
echo "  viewer  : point your client at ws://127.0.0.1:$PORT/global"
echo "            (or http://127.0.0.1:$PORT/global_client.html if the server"
echo "             exposes the static bundle)"
echo "  logs    : $RUNDIR/"
echo "  Ctrl-C to shut down early."
echo ""

shutdown() {
  echo ""
  echo "Shutting down…"
  for pid in "${BOT_PIDS[@]}"; do
    kill -TERM "$pid" 2>/dev/null
  done
  kill -TERM "$SERVER_PID" 2>/dev/null
  # Give them a moment to flush traces, then hard-kill.
  sleep 2
  for pid in "${BOT_PIDS[@]}"; do
    kill -KILL "$pid" 2>/dev/null
  done
  kill -KILL "$SERVER_PID" 2>/dev/null
  echo "done. Run artifacts in $RUNDIR"
  exit 0
}
trap shutdown INT TERM

# Wait for any bot to exit (or duration to elapse); then clean up all.
for pid in "${BOT_PIDS[@]}"; do
  wait "$pid" 2>/dev/null
done
shutdown
