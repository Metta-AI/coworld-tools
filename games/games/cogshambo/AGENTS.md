## AWS Profiles

- Default org profile: `softmax-org` (parent/management account)
- For cogtainer account operations: use `get_aws_session()` from `src/cogtainer/aws.py` — it assumes into the cogtainer account automatically. Don't use a separate AWS profile.
- Direct `aws` CLI commands against the org: `--profile softmax-org`
- The env var `COGENT_ORG_PROFILE` overrides the default if set.
- Never guess or invent profile names. If unsure, check `src/cogtainer/aws.py`.

## EC2 Deployment

- Production URL: `https://redvblue.dbloom.in`.
- Production EC2 origin runs in AWS account `015142856185` (`Softmax Sandbox`) using local AWS profile `softmax-sandbox`.
- The previous origin in account `111005867451` should be treated as rollback-only unless explicitly reactivated.
- Deploy the current `main` ref to EC2 with `npm run deploy:ec2`.
- The deploy script builds from a temporary git worktree at `main`, stamps `.deploy-version.json`, uploads a build artifact to `s3://cogshambo-redvblue-deploy-015142856185-us-east-1/releases/`, sends an SSM command to the running `cogshambo-redvblue` instance, swaps `/opt/cogshambo/app`, restarts `cogshambo.service`, and verifies `/health` plus `/version` through the Cloudflare Tunnel.
- `/version` is the proof-of-deploy endpoint; the deploy script must see the newly generated `deployId` locally on EC2 and publicly through `https://redvblue.dbloom.in/version`.
- Commit or merge wanted changes to `main` before deploying; dirty local worktree changes are intentionally ignored by the deploy script.
- Use `COGSHAMBO_DEPLOY_REF=<ref> npm run deploy:ec2` only for an explicit non-main deployment.
- Use `COGSHAMBO_SKIP_PUBLIC_VERIFY=1` only while staging a replacement EC2 origin before stopping the old Cloudflare Tunnel connector; normal deploys must leave public verification enabled.
- Current EC2 origin is discovered by tags `Name=cogshambo-redvblue`, `App=cogshambo`, `Service=redvblue`; set `COGSHAMBO_EC2_INSTANCE_ID` only when replacing or targeting a specific instance.
- Cloudflare Tunnel is `redvblue-cogshambo` (`9a8cc1d7-ad44-4091-ad4a-611d5e174d33`) with remotely managed ingress for `redvblue.dbloom.in` pointing at `http://127.0.0.1:8787`.
- `cloudflared-redvblue.service` should not have `Requires=cogshambo.service`; keep the tunnel connector alive independently so app crashes surface as origin errors instead of Cloudflare 1033/no-active-connector outages.
- Do not restart the old local Mac launch agent `in.dbloom.redvblue-cogshambo-tunnel`; production traffic should use the EC2 Linux connector.
- Keep the tunnel token in SSM SecureString `/cogshambo/redvblue/cloudflared-token`; never put tunnel tokens or Cloudflare credentials in the repo.

## Frontend Control State

- HUD renders replace large DOM sections. Any new input, textarea, select, tab, or button that can be focused must have a stable restore selector.
- Prefer explicit `data-*` identifiers such as `data-config-key`, `data-trait-config-id` plus `data-trait-config-key`, `data-builder-field`, `data-profile-field`, or another unique domain-specific marker.
- When adding a new control family, update the HUD render-restore framework so focus, value, selection, checked state, and scroll position survive websocket snapshots, config reloads, and other render refreshes.
- Add or update a smoke test for any new editable surface to prove a focused control keeps focus and unsaved text while live updates refresh the app.
