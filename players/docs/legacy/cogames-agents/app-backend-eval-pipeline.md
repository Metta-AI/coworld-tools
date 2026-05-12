# App Backend Eval Pipeline (Policy Evaluator)

This doc explains how the tournament/leaderboard evaluation stack runs `cogames-agents` and where its code is sourced.
It is focused on the app backend + worker pipeline, not on end-user `pip install` flows.

## High-level flow

1. **Orchestrator service** (app backend) polls the backend for eval tasks.
2. It spawns **eval worker pods** in Kubernetes.
3. Each worker runs the eval command in a versioned checkout of `metta`.

Key entry points:

- Orchestrator loop: `app_backend/src/metta/app_backend/eval_task_orchestrator.py`
- Worker runtime: `app_backend/src/metta/app_backend/eval_task_worker.py`
- K8s pod spec: `app_backend/src/metta/app_backend/container_managers/k8s.py`

## Which image runs eval tasks

The orchestrator and workers use the **backend** image:

- Image name: `metta-app-backend`
- Built from: `devops/docker/Dockerfile.backend`
- Built + pushed by: `.github/workflows/deploy-observatory.yml`
- Deployed via: `devops/charts/orchestrator`

## Where `cogames-agents` comes from

Inside the backend image, dependencies are installed from the monorepo:

- `devops/docker/Dockerfile.backend` runs `install.sh` and `uv sync --frozen`.
- The root `pyproject.toml` lists `cogames-agents` as a dependency.
- `tool.uv.sources` in the root `pyproject.toml` maps `cogames-agents` to the workspace.

Result: **the worker image installs `cogames-agents` from the repo workspace**, not from PyPI.

Additionally, each worker **checks out the requested git ref** for the task and runs:

- `uv run metta configure --profile=softmax-docker`

That means evals use the `cogames-agents` version **from the task's git ref**.

## Implications for PyPI

Publishing `cogames-agents` to PyPI does **not** affect the tournament evaluator as long as the backend image and worker
checkouts keep using the workspace.

PyPI only matters for external installs. We no longer publish `cogames-agents` to PyPI.

## Quick sanity checks

- **Image build includes cogames-agents**: `.github/workflows/deploy-observatory.yml`
- **Worker uses workspace checkout**: `app_backend/src/metta/app_backend/eval_task_worker.py`
- **Orchestrator uses backend image**: `devops/charts/orchestrator/values.yaml`
- **Worker pods run eval worker**: `app_backend/src/metta/app_backend/container_managers/k8s.py`

## Related notes

- A single image (`Dockerfile.backend`) serves both the API server and orchestrator/workers.
- The scripted registry is dynamic: `cogames_agents.policy.scripted_registry` scans for classes with literal
  `short_names = [...]` declarations under `cogames_agents/policy/`.
