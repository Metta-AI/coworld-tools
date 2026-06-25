#!/usr/bin/env bash
set -euo pipefail

APP_NAME="cogshambo-redvblue"
DEFAULT_AWS_PROFILE="softmax-sandbox"
DEFAULT_AWS_REGION="us-east-1"
DEFAULT_DEPLOY_REF="main"
DEFAULT_PUBLIC_URL="https://redvblue.dbloom.in"
DEFAULT_BUCKET="cogshambo-redvblue-deploy-015142856185-us-east-1"
INSTANCE_NAME_TAG="cogshambo-redvblue"
INSTANCE_APP_TAG="cogshambo"
INSTANCE_SERVICE_TAG="redvblue"
SSM_TIMEOUT_SECONDS=900

usage() {
  cat <<USAGE
Usage: scripts/deploy-main-to-ec2.sh [--ref REF]

Builds REF, uploads the built artifact to S3, sends an SSM deploy command to the
Cogshambo EC2 origin, restarts cogshambo.service, and verifies the public tunnel.

Environment:
  COGENT_ORG_PROFILE          AWS profile to use. Defaults to ${DEFAULT_AWS_PROFILE}.
  AWS_REGION                  AWS region. Defaults to ${DEFAULT_AWS_REGION}.
  COGSHAMBO_DEPLOY_REF        Git ref to deploy. Defaults to ${DEFAULT_DEPLOY_REF}.
  COGSHAMBO_EC2_INSTANCE_ID   EC2 instance id. If unset, the script discovers the running redvblue instance by tags.
  COGSHAMBO_DEPLOY_BUCKET     S3 artifact bucket. Defaults to ${DEFAULT_BUCKET}.
  COGSHAMBO_PUBLIC_URL        Public URL to verify. Defaults to ${DEFAULT_PUBLIC_URL}.
  COGSHAMBO_SKIP_PUBLIC_VERIFY Set to 1 only while staging a replacement origin before tunnel cutover.
USAGE
}

deploy_ref="${COGSHAMBO_DEPLOY_REF:-$DEFAULT_DEPLOY_REF}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      deploy_ref="${2:-}"
      if [[ -z "$deploy_ref" ]]; then
        echo "--ref requires a value" >&2
        exit 2
      fi
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

aws_profile="${COGENT_ORG_PROFILE:-$DEFAULT_AWS_PROFILE}"
aws_region="${AWS_REGION:-$DEFAULT_AWS_REGION}"
artifact_bucket="${COGSHAMBO_DEPLOY_BUCKET:-$DEFAULT_BUCKET}"
public_url="${COGSHAMBO_PUBLIC_URL:-$DEFAULT_PUBLIC_URL}"
skip_public_verify="${COGSHAMBO_SKIP_PUBLIC_VERIFY:-}"

repo_root="$(git rev-parse --show-toplevel)"
deploy_commit="$(git -C "$repo_root" rev-parse --verify "${deploy_ref}^{commit}")"
deploy_short="$(git -C "$repo_root" rev-parse --short "$deploy_commit")"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
deployed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
deploy_id="${deploy_short}-${timestamp}"
worktree="$(mktemp -d "${TMPDIR:-/tmp}/${APP_NAME}.worktree.XXXXXX")"
artifact="$(mktemp "${TMPDIR:-/tmp}/${APP_NAME}.${deploy_short}.${timestamp}.XXXXXX")"
remote_script="$(mktemp "${TMPDIR:-/tmp}/${APP_NAME}.remote.XXXXXX")"
ssm_params="$(mktemp "${TMPDIR:-/tmp}/${APP_NAME}.ssm.XXXXXX")"
health_body="$(mktemp "${TMPDIR:-/tmp}/${APP_NAME}.health.XXXXXX")"
version_body="$(mktemp "${TMPDIR:-/tmp}/${APP_NAME}.version.XXXXXX")"
artifact_key="releases/${APP_NAME}-${deploy_id}.tgz"
artifact_s3_uri="s3://${artifact_bucket}/${artifact_key}"

cleanup() {
  rm -f "$artifact" "$remote_script" "$ssm_params" "$health_body" "$version_body"
  git -C "$repo_root" worktree remove --force "$worktree" >/dev/null 2>&1 || rm -rf "$worktree"
}
trap cleanup EXIT

aws_cli() {
  aws --profile "$aws_profile" --region "$aws_region" "$@"
}

upload_artifact() {
  local presigned_url
  presigned_url="$(
    AWS_PROFILE="$aws_profile" AWS_REGION="$aws_region" python3 - "$artifact_bucket" "$artifact_key" <<'PY'
import boto3
import os
import sys

bucket, key = sys.argv[1:3]
session = boto3.Session(profile_name=os.environ["AWS_PROFILE"], region_name=os.environ["AWS_REGION"])
client = session.client("s3")
print(
    client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": "application/gzip"},
        ExpiresIn=3600,
        HttpMethod="PUT",
    )
)
PY
  )"

  echo "Uploading artifact with curl..."
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 2 --retry-all-errors \
    --connect-timeout 10 --max-time 1800 \
    --upload-file "$artifact" \
    --header "Content-Type: application/gzip" \
    "$presigned_url" \
    >/dev/null
}

discover_instance_id() {
  if [[ -n "${COGSHAMBO_EC2_INSTANCE_ID:-}" ]]; then
    printf '%s\n' "$COGSHAMBO_EC2_INSTANCE_ID"
    return
  fi

  instance_ids=()
  while IFS= read -r instance_id; do
    if [[ -n "$instance_id" ]]; then
      instance_ids+=("$instance_id")
    fi
  done < <(
    aws_cli ec2 describe-instances \
      --filters \
        "Name=tag:Name,Values=${INSTANCE_NAME_TAG}" \
        "Name=tag:App,Values=${INSTANCE_APP_TAG}" \
        "Name=tag:Service,Values=${INSTANCE_SERVICE_TAG}" \
        "Name=instance-state-name,Values=running" \
      --query 'Reservations[].Instances[].InstanceId' \
      --output text | tr '\t' '\n' | sed '/^$/d'
  )

  if [[ "${#instance_ids[@]}" -ne 1 ]]; then
    echo "Expected exactly one running ${APP_NAME} EC2 instance, found ${#instance_ids[@]}." >&2
    echo "Set COGSHAMBO_EC2_INSTANCE_ID to deploy explicitly." >&2
    exit 1
  fi

  printf '%s\n' "${instance_ids[0]}"
}

echo "Deploying ${deploy_ref} (${deploy_short}) to ${APP_NAME} using profile ${aws_profile} in ${aws_region}."

echo "Creating temporary worktree..."
rm -rf "$worktree"
git -C "$repo_root" worktree add --detach --quiet "$worktree" "$deploy_commit"

echo "Installing dependencies and building..."
(
  cd "$worktree"
  npm ci --no-audit --no-fund
  npm run build
)

echo "Packaging artifact..."
(
  cd "$worktree"
  node -e '
const fs = require("node:fs");
const [commit, shortCommit, deployId, deployedAt, ref] = process.argv.slice(1);
fs.writeFileSync(
  ".deploy-version.json",
  `${JSON.stringify({ commit, shortCommit, deployId, deployedAt, ref }, null, 2)}\n`,
);
' "$deploy_commit" "$deploy_short" "$deploy_id" "$deployed_at" "$deploy_ref"
  COPYFILE_DISABLE=1 tar --exclude='._*' --exclude='.DS_Store' -czf "$artifact" \
    package.json package-lock.json dist dist-server \
    public/assets/cogshambo/venue/venue-graph.json \
    tools/generate_sprite_sheet.py .deploy-version.json
)

echo "Uploading ${artifact_s3_uri}..."
if ! aws_cli s3api head-bucket --bucket "$artifact_bucket" >/dev/null 2>&1; then
  aws_cli s3api create-bucket --bucket "$artifact_bucket" >/dev/null
fi
aws_cli s3api put-public-access-block \
  --bucket "$artifact_bucket" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
  >/dev/null
upload_artifact

instance_id="$(discover_instance_id)"
echo "Deploying on ${instance_id} through SSM..."

cat > "$remote_script" <<'REMOTE_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_S3_URI="__ARTIFACT_S3_URI__"
REGION="__REGION__"
DEPLOY_ID="__DEPLOY_ID__"
APP_DIR="/opt/cogshambo/app"
RELEASES_DIR="/opt/cogshambo/releases"
DATA_DIR="/var/lib/cogshambo"
SERVICE_NAME="cogshambo.service"
TUNNEL_SERVICE_NAME="cloudflared-redvblue.service"
ARTIFACT="/tmp/cogshambo-deploy.tgz"
HEALTH_BODY="/tmp/cogshambo-health.json"
VERSION_BODY="/tmp/cogshambo-version.json"
STAGING="${RELEASES_DIR}/${DEPLOY_ID}"
BACKUP="${RELEASES_DIR}/rollback-$(date -u +%Y%m%dT%H%M%SZ)"

rollback() {
  if [[ -e "$BACKUP" || -L "$BACKUP" ]]; then
    echo "Rolling back to ${BACKUP}..."
    systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
    rm -rf "$APP_DIR"
    mv "$BACKUP" "$APP_DIR"
    systemctl start "$SERVICE_NAME"
    systemctl restart "$TUNNEL_SERVICE_NAME" >/dev/null 2>&1 || true
  fi
}

fail_with_logs() {
  local message="$1"
  echo "$message" >&2
  systemctl --no-pager status "$SERVICE_NAME" "$TUNNEL_SERVICE_NAME" || true
  journalctl -u "$SERVICE_NAME" -u "$TUNNEL_SERVICE_NAME" --no-pager -n 160 || true
  rollback
  exit 1
}

decouple_tunnel_service() {
  local unit_path="/etc/systemd/system/${TUNNEL_SERVICE_NAME}"
  if [[ ! -f "$unit_path" ]]; then
    return
  fi

  if grep -q '^Requires=cogshambo\.service$' "$unit_path"; then
    sed -i '/^Requires=cogshambo\.service$/d' "$unit_path"
    systemctl daemon-reload
  fi
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi

  echo "Installing uv for sprite normalization..."
  if ! command -v curl >/dev/null 2>&1; then
    fail_with_logs "curl is required to install uv for sprite normalization."
  fi
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
  command -v uv >/dev/null 2>&1 || fail_with_logs "uv install did not put uv on PATH."
}

mkdir -p "$RELEASES_DIR" "$DATA_DIR"
rm -rf "$STAGING"
mkdir -p "$STAGING"
decouple_tunnel_service
ensure_uv

aws s3 cp --no-progress --region "$REGION" "$ARTIFACT_S3_URI" "$ARTIFACT"
tar -xzf "$ARTIFACT" -C "$STAGING"

cd "$STAGING"
npm ci --omit=dev --no-audit --no-fund
chown -R cogshambo:cogshambo "$STAGING" "$DATA_DIR"

systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
rm -rf "$BACKUP"
if [[ -e "$APP_DIR" || -L "$APP_DIR" ]]; then
  mv "$APP_DIR" "$BACKUP"
fi
mv "$STAGING" "$APP_DIR"

if ! systemctl start "$SERVICE_NAME"; then
  fail_with_logs "Failed to start ${SERVICE_NAME}."
fi

if ! systemctl restart "$TUNNEL_SERVICE_NAME"; then
  fail_with_logs "Failed to restart ${TUNNEL_SERVICE_NAME}."
fi

for _ in {1..60}; do
  if curl -fsS --max-time 10 http://127.0.0.1:8787/health -o "$HEALTH_BODY" &&
    grep -q '"ok":true' "$HEALTH_BODY" &&
    curl -fsS --max-time 10 http://127.0.0.1:8787/version -o "$VERSION_BODY" &&
    grep -q "\"deployId\":\"${DEPLOY_ID}\"" "$VERSION_BODY"; then
    echo "Local EC2 health and version checks passed for ${DEPLOY_ID}."
    systemctl --no-pager --plain is-active "$SERVICE_NAME" "$TUNNEL_SERVICE_NAME"
    exit 0
  fi
  sleep 2
done

fail_with_logs "Local EC2 health/version check failed for ${DEPLOY_ID}."
REMOTE_SCRIPT

perl -0pi \
  -e "s#__ARTIFACT_S3_URI__#${artifact_s3_uri}#g; s#__REGION__#${aws_region}#g; s#__DEPLOY_ID__#${deploy_id}#g" \
  "$remote_script"

remote_script_b64="$(base64 < "$remote_script" | tr -d '\n')"
cat > "$ssm_params" <<JSON
{
  "commands": [
    "printf '%s' '${remote_script_b64}' | base64 -d >/tmp/cogshambo-ec2-deploy.sh",
    "chmod 0700 /tmp/cogshambo-ec2-deploy.sh",
    "/tmp/cogshambo-ec2-deploy.sh"
  ],
  "executionTimeout": ["${SSM_TIMEOUT_SECONDS}"]
}
JSON

command_id="$(
  aws_cli ssm send-command \
    --instance-ids "$instance_id" \
    --document-name AWS-RunShellScript \
    --parameters "file://${ssm_params}" \
    --timeout-seconds "$SSM_TIMEOUT_SECONDS" \
    --query 'Command.CommandId' \
    --output text
)"

while true; do
  status="$(
    aws_cli ssm get-command-invocation \
      --command-id "$command_id" \
      --instance-id "$instance_id" \
      --query Status \
      --output text 2>/dev/null || true
  )"

  case "$status" in
    Success)
      echo "Remote deploy completed."
      aws_cli ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        --query StandardOutputContent \
        --output text
      break
      ;;
    Failed|Cancelled|TimedOut)
      echo "Remote deploy failed with status ${status}." >&2
      aws_cli ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        --query '{stdout:StandardOutputContent,stderr:StandardErrorContent}' \
        --output json >&2
      exit 1
      ;;
    Pending|InProgress|Delayed|"")
      sleep 5
      ;;
    *)
      echo "Remote deploy status: ${status}"
      sleep 5
      ;;
  esac
done

if [[ "$skip_public_verify" == "1" || "$skip_public_verify" == "true" ]]; then
  echo "Skipping public tunnel verification for ${deploy_id}."
  echo "Deployment staged on EC2: ${deploy_id}."
  exit 0
fi

echo "Verifying ${public_url}/health..."
curl -fsS --max-time 15 "${public_url%/}/health" -o "$health_body"
if ! grep -q '"ok":true' "$health_body"; then
  echo "Public health check did not return ok: true." >&2
  head -c 1000 "$health_body" >&2
  exit 1
fi

echo "Verifying ${public_url}/version..."
curl -fsS --max-time 15 "${public_url%/}/version" -o "$version_body"
if ! grep -q "\"deployId\":\"${deploy_id}\"" "$version_body"; then
  echo "Public version check did not return deployId ${deploy_id}." >&2
  cat "$version_body" >&2
  exit 1
fi

echo "Deployment complete: ${public_url} is healthy at ${deploy_id}."
