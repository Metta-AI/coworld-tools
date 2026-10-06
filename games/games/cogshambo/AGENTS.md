# Repository guidance

## Deployment configuration

Read `scripts/deploy-main-to-ec2.sh` and its `--help` output for the configured
account, profile, region, bucket, instance discovery, and public endpoint.
Do not infer live infrastructure from copied identifiers or another checkout.
Keep credentials outside the repository and use the environment owner's
approved authentication setup.

## EC2 deployment

Deployment changes a shared service and requires explicit authorization.
For an authorized deployment, use `npm run deploy:ec2`. The script builds the
selected committed ref in a temporary worktree; dirty local changes are excluded.
`COGSHAMBO_DEPLOY_REF` selects an explicitly requested non-default revision.

The script uploads the artifact, deploys it through SSM, restarts the app,
and verifies `/health` and `/version`. Verify the expected `deployId` both
on the origin and through the configured public endpoint before reporting success.
Keep public verification enabled for normal deployments; bypass it only for
an explicitly authorized replacement-origin staging operation.

Resolve the current origin through the deployment script's configured tags.
Use `COGSHAMBO_EC2_INSTANCE_ID` only for an explicitly selected instance.
Keep the tunnel connector independent of the application service so app crashes
remain visible as origin failures. Never reactivate an old connector or rollback
origin without an explicit request. Store tunnel tokens in the configured secret
store; never commit tokens or provider credentials.

## Frontend Control State

- HUD renders replace large DOM sections. Any new input, textarea, select, tab, or button that can be focused must have a stable restore selector.
- Prefer explicit `data-*` identifiers such as `data-config-key`, `data-trait-config-id` plus `data-trait-config-key`, `data-builder-field`, `data-profile-field`, or another unique domain-specific marker.
- When adding a new control family, update the HUD render-restore framework so focus, value, selection, checked state, and scroll position survive websocket snapshots, config reloads, and other render refreshes.
- Add or update a smoke test for any new editable surface to prove a focused control keeps focus and unsaved text while live updates refresh the app.
