# Beta-CVC Policy Validation (Local)

Date: 2026-01-29

This document summarizes the current state of local validation for the beta-cvc policies referenced in the
beta-cogsguard leaderboard list. The goal was to re-download the exact uploaded bundles and confirm they start correctly
on the beta-cvc mission (`cogsguard_machina_1.basic`).

## Scope

- Policies tested (19 total) match the earlier beta-cogsguard leaderboard list:
  - daveey.pinky:v5/v6/v7/v8/v9
  - daveey.planky:v6/v7/v8
  - relh.cogas:v6/v7/v8/v10
  - relh.wombo-mix:v1/v3/v4
  - noah::coggernaut:v4/v9
  - manvi_metcon:v3
  - cogsguard-roster-mix:v1

- All bundles were re-downloaded from the policy `s3_path` recorded in the backend, not from the older
  `policy-versions/` location.

## Bundle Download (Exact Uploaded Artifacts)

The backend stores a policy version’s `s3_path` at: `/stats/policies/versions/{policy_version_id}`.

We used the policy version lookup to get `s3_path`, then downloaded via S3:

```
aws s3 cp s3://observatory-private/cogames/submissions/<user>/<upload_id>.zip \
  outputs/beta-cvc-policy-bundles-redownload/<policy>_v<version>.zip
```

All 19 bundles are now in: `outputs/beta-cvc-policy-bundles-redownload/`

## Local Validation Commands

We validated against the beta-cvc mission (CogsGuard Machina1):

```
uv run cogames scrimmage -m cogsguard_machina_1.basic -c 5 -e 1 -s 300 --format json \
  -p ./outputs/beta-cvc-policy-bundles-redownload/<policy>.zip

uv run cogames run -m cogsguard_machina_1.basic -c 5 -e 1 -s 300 --format json \
  -p ./outputs/beta-cvc-policy-bundles-redownload/<policy>.zip
```

Notes:

- Use a relative path starting with `./` for local bundles; otherwise the CLI interprets the argument as a class name.

## Results: Scrimmage + Eval (CVC Map)

Summary:

- **18/19** bundles run successfully for both `scrimmage` and `eval`.
- **1/19** fails due to a missing class in the bundle.

Failures:

- `relh.wombo-mix:v3` fails to import: `cogames_agents.policy.scripted_agent.cogsguard.policy.CogsguardWomboMixPolicy`

Logs and summary:

- `outputs/beta-cvc-policy-bundles-redownload/smoke_logs/summary.txt`
- Per-policy logs: `outputs/beta-cvc-policy-bundles-redownload/smoke_logs/*__scrimmage.log` and `*__eval.log`

## Diagnose (Diagnostic Evals) Caveats

`cogames diagnose` runs **diagnostic evals**, which are not CogsGuard missions. These maps have:

- Max cogs = 4.
- A different action set.
- Variants incompatible with CogsGuard missions.

### Full diagnostic suite

Running `diagnose` with the full `diagnostic_evals` set fails broadly because the evals are incompatible with CogsGuard
mission variants or cogs > 4.

### Single diagnostic experiment

We ran a single diagnostic experiment as a smoke test:

```
uv run cogames diagnose -S diagnostic_evals \
  --experiments diagnostic_chest_deposit_near \
  -c 4 -e 1 -s 300 \
  ./outputs/beta-cvc-policy-bundles-redownload/<policy>.zip
```

Results:

- OK:
  - cogsguard-roster-mix:v1
  - daveey.pinky:v5/v6/v7/v8/v9
  - noah::coggernaut:v4/v9
  - relh.wombo-mix:v1/v4
- FAIL:
  - daveey.planky:v6/v7/v8
  - manvi_metcon:v3
  - relh.cogas:v6/v7/v8/v10
  - relh.wombo-mix:v3

Typical failure pattern for the diagnostic experiment:

- Action mismatch in diagnostics env (example: `KeyError: 'change_vibe_miner'`).
- `relh.wombo-mix:v3` still fails due to missing class.

Conclusion: `diagnose` is **not a reliable signal** for CogsGuard policies. The best local signal for beta-cvc is
`scrimmage`/`eval` on `cogsguard_machina_1.basic`.

## Beta-CVC Tournament State (As of 2026-01-29)

Leaderboard is empty because no competition matches have completed yet. Policies currently in beta-cvc:

- Qualifying completed (2 matches): daveey.pinky:v8, daveey.planky:v6, cogsguard-roster-mix:v1, noah::coggernaut:v9,
  noah::coggernaut:v10.
- Competition active but no matches completed: manvi_metcon:v3.

## Known Issues / Follow-ups

- `relh.wombo-mix:v3` bundle references a class that does not exist in the repository (`CogsguardWomboMixPolicy`), so it
  cannot run locally or in the tournament runner.
- If we need a single “diagnose”-style smoke check for CogsGuard, we should add a dedicated CogsGuard diagnostic mission
  set (or avoid `diagnose` entirely for this season).
