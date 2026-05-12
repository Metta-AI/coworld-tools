# Leaderboard Submission Process

> Step-by-step guide to submitting policies to the Beta-CogsGuard leaderboard, including CLI commands, backend
> architecture, scoring methodology, and package requirements.

---

## 1. Prerequisites

### Authentication

```bash
cogames auth login
```

- Opens browser-based authentication flow against `https://softmax.com/api`
- Stores token in `cogames.yaml` under `login_tokens`
- One-time setup; token persists across sessions
- Use `--force` to re-authenticate if token expires

### Required Packages

The `cogames` CLI is provided by the `cogames` Python package. Install it from the metta workspace:

```bash
# From the metta repo root
uv sync
```

If submitting a custom Python policy class from `cogames-agents`, that package must also be installed:

```bash
pip install -e cogames-agents
```

---

## 2. Upload a Policy

Package your policy into a submission bundle, then upload that bundle to the tournament server.

### Command

```bash
cogames upload -p ./submission.zip -n <name> [options]
```

### Arguments

| Flag                  | Description                                                                     |
| --------------------- | ------------------------------------------------------------------------------- |
| `-p, --policy`        | Policy specification (required). Path to checkpoint dir, or Python class path   |
| `-n, --name`          | Policy name (required). Used to identify your policy on the leaderboard         |
| `-k, --init-kwarg`    | Policy init kwargs (repeatable). Format: `key=value`                            |
| `-f, --include-files` | Extra files/directories to include in the submission zip (repeatable)           |
| `--setup-script`      | Python setup script to run before policy initialization                         |
| `--season`            | Tournament season (default: `beta-cogsguard`)                                   |
| `--dry-run`           | Validate without uploading                                                      |
| `--skip-validation`   | Skip isolated environment validation                                            |
| `--login-server`      | Auth server URL (default: `https://softmax.com/api`)                            |
| `--server`            | Tournament server URL (default: `https://api.observatory.softmax-research.net`) |

### Examples

```bash
# 1. Create the submission bundle
cogames create-bundle -p <policy-or-checkpoint> -o ./submission.zip \
  [-f <extra-path> ...] [--setup-script <setup.py>]

# 2. Dry-run the bundle
cogames upload -p ./submission.zip -n my-policy --dry-run

# 3. Upload without submitting yet
cogames upload -p ./submission.zip -n my-policy --no-submit

# 4. Submit the uploaded policy to a season
cogames submit my-policy --season beta-cogsguard
```

If your policy needs extra runtime files or setup, include them in the bundle (more details in `agent/COGAMES_SUBMISSION.md`).

### What Happens During Upload

1. **Validation** (unless `--skip-validation`): Creates an isolated temp environment with the published `cogames`
   package, loads the policy, and runs it for 1 episode / 10 steps on the season's validation mission
   (`arena` for `beta-cogsguard`)
2. **Packaging**: Creates a zip containing `policy_spec.json` and any included files
3. **Presigned URL**: Requests an S3 upload URL from the backend (`POST /stats/policies/submit/presigned-url`)
4. **S3 Upload**: Uploads the zip to `s3://softmax-public/cogames/submissions/{user_id}/{upload_id}.zip`
5. **Registration**: Completes the upload (`POST /stats/policies/submit/complete`), which creates a policy version
   record and returns `{id, name, version}`

### Submission Zip Contents

The zip contains a `policy_spec.json` with:

```json
{
  "class_path": "path.to.PolicyClass",
  "data_path": "relative/path/to/checkpoint",
  "init_kwargs": { "key": "value" },
  "setup_script": "optional_setup.py"
}
```

Plus any checkpoint files and included extras.

### Versioning

Each upload to the same name increments the version number automatically (v1, v2, v3, ...). You can submit specific
versions later.

---

## 3. Submit to a Tournament

After uploading, submit your policy to a tournament season to enter it into matchmaking.

### Command

```bash
cogames submit <policy-name>[:<version>] --season <season>
```

### Examples

```bash
# Submit latest version
cogames submit my-policy --season beta-cogsguard

# Submit a specific version
cogames submit my-policy:v3 --season beta-cogsguard
```

### What Happens During Submission

1. Parses the policy identifier (name + optional version like `my-policy:v3`)
2. Looks up the policy version ID from the server
3. Calls `POST /tournament/seasons/{season}/submissions` with `{policy_version_id}`
4. The season's **commissioner** adds the policy to one or more **pools**
5. Returns the list of pool names the policy was added to
6. A duplicate submission to the same season returns a 409 conflict

### Tournament Structure

```
Season (e.g., "beta-cogsguard")
  └── Pool(s)
       └── PoolPlayer (your policy version)
            └── Matches (scheduled by referee)
                 └── MatchPlayer (per-policy scores)
```

---

## 4. Monitor Status

### View Your Submissions

```bash
# All uploads
cogames submissions

# Filter by policy name
cogames submissions --policy my-policy

# Filter by season
cogames submissions --season beta-cogsguard

# JSON output
cogames submissions --json
```

Shows: policy name:version, upload time, and which seasons each is entered in.

### View Leaderboard

```bash
cogames leaderboard --season beta-cogsguard

# JSON for scripting
cogames leaderboard --season beta-cogsguard --json
```

Returns: rank, policy name:version, score, and match count.

### View Available Seasons

```bash
cogames season list

# JSON
cogames season list --json
```

Returns: season name, description, and pool names.

---

## 5. Scoring Methodology

### Primary Objective: `aligned.junction.held`

The leaderboard score is derived from the `aligned.junction.held` metric, which measures how long your team (cogs) holds
junctions in an aligned state during each episode.

**Per-episode calculation:**

- Each tick where a junction is aligned to your team contributes `1.0 / max_steps` to the score
- The metric accumulates across all junctions over the episode duration
- Higher values mean your agents successfully scrambled enemy (clips) junctions and aligned them to cogs

**Reward configuration** (from `cogsguard_reward_variants.py`):

```python
_OBJECTIVE_STAT_KEY = "aligned.junction.held"

# Reward per tick per held junction:
"aligned.junction.held": 1.0 / max_steps
```

### Leaderboard Score Aggregation

Scores are aggregated across tournament matches using **weighted averaging**:

1. Each match runs one or more episodes with multiple policies
2. Per-match scoring computes each policy's performance
3. **Weight** = number of agents controlled by that policy / total agents in the match
4. Final score = weighted average across all matches

The scoring algorithm (`metta_alo/scoring.py`):

```python
# Per match, per policy:
weight = agent_count_for_policy / total_agents
weighted_score += match_score * weight
final_score = weighted_sum / total_weight
```

### Additional Scoring Concepts

**Value Over Replacement (VOR)**: The system can compute how much better a policy performs compared to a replacement
baseline:

```python
vor = candidate_score - replacement_score
```

### Supporting Metrics

While `aligned.junction.held` is the primary objective, these metrics indicate agent health:

| Metric                                      | What It Measures        | Target                                    |
| ------------------------------------------- | ----------------------- | ----------------------------------------- |
| `env_agent/heart.gained`                    | Hearts collected        | Higher is better (10-14 in top baselines) |
| `env_collective/cogs/aligned.junction.held` | Junction alignment time | Higher is better                          |
| `overview/reward`                           | Episode reward          | Increasing trend                          |
| `losses/approx_kl`                          | Training stability      | < 0.03                                    |

---

## 6. Validation Missions

The upload validation step runs your policy against a mission specific to the season:

| Season           | Validation Mission          |
| ---------------- | --------------------------- |
| `beta-cogsguard` | `arena`                     |
| `beta`           | `training_facility.harvest` |
| (default)        | `arena`                     |

Validation runs 1 episode for up to 10 steps. The policy must load and execute without errors.

---

## 7. Backend Architecture

For reference, the submission system uses these server components:

### Servers

| Server     | URL                                            | Purpose                     |
| ---------- | ---------------------------------------------- | --------------------------- |
| Auth       | `https://softmax.com/api`                      | Login and token management  |
| Tournament | `https://api.observatory.softmax-research.net` | Upload, submit, leaderboard |
| Storage    | S3 (`softmax-public` bucket)                   | Policy zip storage, replays |

### API Endpoints

| Endpoint                                 | Method | Description              |
| ---------------------------------------- | ------ | ------------------------ |
| `/stats/policies/submit/presigned-url`   | POST   | Get S3 upload URL        |
| `/stats/policies/submit/complete`        | POST   | Register uploaded policy |
| `/tournament/seasons/{name}/submissions` | POST   | Submit policy to season  |
| `/tournament/seasons/{name}/leaderboard` | GET    | Get ranked standings     |
| `/tournament/seasons/{name}/policies`    | GET    | List policies in season  |
| `/tournament/seasons`                    | GET    | List available seasons   |
| `/tournament/my-memberships`             | GET    | Your policy memberships  |

### Database Model

The tournament system tracks:

- **Season**: Named tournament (e.g., `beta-cogsguard`) with one or more pools
- **Pool**: A matchmaking group within a season
- **PoolPlayer**: A policy version entered in a pool (can be active or retired)
- **Match**: A game between pool players with status tracking (pending/scheduled/running/completed/failed)
- **MatchPlayer**: Per-policy results within a match, including `score`

### Match Lifecycle

1. **Referee** schedules matches based on pool players and existing match history
2. Matches are assigned to **jobs** for execution
3. Episodes run with policy assignments
4. Per-policy scores are recorded in `MatchPlayer.score`
5. **Commissioner** aggregates scores into leaderboard rankings

---

## 8. End-to-End Workflow

```bash
# 1. Authenticate (one-time)
cogames auth login

# 2. Train a policy (on mettabox or locally)
cogames tutorial train -m arena --steps 5000000000 --batch-size 2097152 -p lstm

# 3. Evaluate locally before uploading
cogames scrimmage -m arena -p ./train_dir/my-run -e 50

# 4. Build a submission bundle
# Include any extra runtime files or setup your policy needs. `agent/COGAMES_SUBMISSION.md` has a full repo example.
cogames create-bundle -p <policy-or-checkpoint> -o ./submission.zip [-f <extra-path> ...] [--setup-script <setup.py>]

# 5. Dry-run the bundle
cogames upload -p ./submission.zip -n my-policy --dry-run

# 6. Upload the bundle
cogames upload -p ./submission.zip -n my-policy --no-submit

# 7. Submit to the leaderboard
cogames submit my-policy --season beta-cogsguard

# 8. Check standings
cogames leaderboard --season beta-cogsguard

# 9. Iterate: upload new version, re-submit
cogames create-bundle -p <updated-policy-or-checkpoint> -o ./submission-v2.zip [-f <extra-path> ...] [--setup-script <setup.py>]
cogames upload -p ./submission-v2.zip -n my-policy --no-submit
cogames submit my-policy:v2 --season beta-cogsguard
```

---

## 9. Submitting a Custom Python Policy

Package the policy into `submission.zip`, then upload that bundle.

### Steps

1. Define your policy class in `cogames-agents` or a standalone module
2. Build the bundle:
   ```bash
   cogames create-bundle -p cogames_agents.policy.MyCustomPolicy -o ./submission.zip [-f <extra-path> ...] [--setup-script <setup.py>]
   ```
3. Upload the bundle:
   ```bash
   cogames upload -p ./submission.zip -n my-custom --no-submit
   cogames submit my-custom --season beta-cogsguard
   ```

### Package Requirements

The tournament server evaluates policies using the published versions of `cogames`, `cogames-agents`, and `mettagrid`
from PyPI. Your policy must be compatible with the installed versions of these packages.

---

## 10. Troubleshooting

### Upload Validation Fails

```
Error: Policy validation failed
```

- Ensure your policy loads without errors: `cogames play -m arena -p <your-policy> -s 10`
- Check that all dependencies are available in a clean environment
- Rebuild `submission.zip` with every runtime file and setup step your policy needs
- Include any extra runtime files or setup your policy needs (more details in `agent/COGAMES_SUBMISSION.md`)
- Use `--skip-validation` to bypass (not recommended; the tournament server will also fail)

### Duplicate Submission (409 Conflict)

```
Error: Policy already submitted to this season
```

Upload a new bundle version and submit that instead:

```bash
cogames create-bundle -p <updated-policy-or-checkpoint> -o ./submission-v2.zip [-f <extra-path> ...] [--setup-script <setup.py>]
cogames upload -p ./submission-v2.zip -n my-policy --no-submit
cogames submit my-policy:v2 --season beta-cogsguard
```

### Authentication Expired

```
Error: 401 Unauthorized
```

Re-authenticate:

```bash
cogames auth login --force
```

### No Matches Appearing

After submission, matches are scheduled by the tournament referee. There may be a delay depending on pool configuration
and the number of active players. Check:

```bash
cogames submissions --season beta-cogsguard
```

The `completed`, `pending`, and `failed` counts show match progress.
