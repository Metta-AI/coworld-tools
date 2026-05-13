#!/usr/bin/env bash
set -euo pipefail

# Launch the CvC Policy Optimizer on a remote cluster.
#
# Usage:
#   ./launch.sh                          # Deploy to aaron-8x-1 (default)
#   ./launch.sh my-cluster               # Deploy to a named cluster
#   ./launch.sh my-cluster --attach      # Deploy and tail logs
#   ./launch.sh --local                  # Run locally with docker-compose

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

CLUSTER="${1:-aaron-8x-1}"
ATTACH="${2:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log() { echo -e "${CYAN}[optimizer]${NC} $*"; }
success() { echo -e "${GREEN}✓${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }

# ── Local mode ────────────────────────────────────────────────────────────────

if [ "$CLUSTER" = "--local" ]; then
  log "Running locally with docker-compose..."
  cd "$SCRIPT_DIR"
  docker compose up --build -d
  success "Optimizer running locally"
  echo ""
  echo "  View logs:    docker compose -f $SCRIPT_DIR/docker-compose.yml logs -f"
  echo "  Stop:         docker compose -f $SCRIPT_DIR/docker-compose.yml down"
  echo "  Shell:        docker exec -it cvc-policy-optimizer bash"
  exit 0
fi

# ── Remote mode ───────────────────────────────────────────────────────────────

log "Deploying to ${BOLD}${CLUSTER}${NC}..."

# Check SSH connectivity
log "Testing SSH connection..."
ssh -o ConnectTimeout=10 -o BatchMode=yes "$CLUSTER" "echo ok" >/dev/null 2>&1 || {
  fail "Cannot SSH into $CLUSTER. Make sure it's running and SSH is configured."
}
success "SSH connection OK"

# Create workspace on remote
log "Setting up workspace on $CLUSTER..."
ssh "$CLUSTER" "mkdir -p ~/cvc-optimizer/docker/policy-optimizer"

# Sync the policy-optimizer directory
log "Syncing optimizer files..."
rsync -avz --progress \
  "$SCRIPT_DIR/" \
  "$CLUSTER:~/cvc-optimizer/docker/policy-optimizer/"

# Sync the repository source tree
log "Syncing agent-policies repo..."
rsync -avz --progress \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude '.venv' \
  "$PROJECT_ROOT/" \
  "$CLUSTER:~/cvc-optimizer/repo/"

# Build and launch on remote
log "Building and launching on $CLUSTER..."
ssh "$CLUSTER" bash <<'REMOTE_SCRIPT'
set -euo pipefail

cd ~/cvc-optimizer/docker/policy-optimizer

# Ensure docker is available
if ! command -v docker &>/dev/null; then
  echo "Docker not found, installing..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER
fi

# Set up env vars
export REPO_ROOT=~/cvc-optimizer/repo
export AWS_DIR=~/.aws
export AWS_PROFILE=${AWS_PROFILE:-softmax}
export AWS_REGION=${AWS_REGION:-us-east-1}

# Build
echo "Building Docker image..."
docker compose build

# Stop any existing optimizer
docker compose down 2>/dev/null || true

# Launch
echo "Starting optimizer..."
docker compose up -d

echo ""
echo "=== Policy Optimizer Launched ==="
echo "  View logs:    ssh CLUSTER 'docker logs -f cvc-policy-optimizer'"
echo "  Shell:        ssh CLUSTER 'docker exec -it cvc-policy-optimizer bash'"
echo "  Stop:         ssh CLUSTER 'cd ~/cvc-optimizer/docker/policy-optimizer && docker compose down'"
echo "  Results:      ssh CLUSTER 'docker exec cvc-policy-optimizer cat /app/results/results.jsonl'"
REMOTE_SCRIPT

success "Optimizer deployed to $CLUSTER"

echo ""
echo -e "  ${BOLD}Monitor:${NC}"
echo "    ssh $CLUSTER 'docker logs -f cvc-policy-optimizer'"
echo ""
echo -e "  ${BOLD}Shell into container:${NC}"
echo "    ssh $CLUSTER 'docker exec -it cvc-policy-optimizer bash'"
echo ""
echo -e "  ${BOLD}Check results:${NC}"
echo "    ssh $CLUSTER 'docker exec cvc-policy-optimizer python /app/eval_harness.py --compare /app/results/results.jsonl'"
echo ""
echo -e "  ${BOLD}Stop:${NC}"
echo "    ssh $CLUSTER 'cd ~/cvc-optimizer/docker/policy-optimizer && docker compose down'"

# Optionally attach to logs
if [ "$ATTACH" = "--attach" ]; then
  log "Attaching to logs (Ctrl+C to detach)..."
  ssh "$CLUSTER" "docker logs -f cvc-policy-optimizer"
fi
