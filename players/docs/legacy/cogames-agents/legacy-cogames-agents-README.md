# agent-policies

> Legacy note: this is the README from the first seed commit, when the repo
> still preserved `cogames-agents` as one root package. The current workspace
> layout is documented in the root `README.md`, `docs/policy-catalog.md`, and
> `docs/source-provenance.md`.

Policy experimentation workspace for Metta-AI projects.

This repo contains the externalized `cogames-agents` package plus the workspace
structure for symbolic, cyborg, neural, and contributor-owned policy projects.
The `cogames-agents` distribution name and `cogames_agents` import path are
preserved so existing class paths and `metta://policy/...` URIs continue to
work.

## Workspace layout

- `src/cogames_agents/`: externalized package source from the Metta monorepo.
- `policies/`: curated shared policy library, grouped by symbolic, cyborg, and
  neural behavior.
- `users/`: contributor-owned policy repos mounted as submodules.
- `tools/`: shared eval, upload, benchmark, compare, and research tools.
- `docs/`: policy catalog, migration notes, and experiment records.

## cogames-agents package

Optional scripted policies for CoGames. Use them for quick baselines, play/eval smoke tests, or as teacher policies.

## Scripted policy registry

The registry at `cogames_agents.policy.scripted_registry` maps policy `short_names` to `metta://policy/...` URIs.
Scripted agents and teachers share these identifiers, so the same name works for evaluation, play, and
`TeacherConfig.policy_uri`.

To list the current names:

```
python -c "from cogames_agents.policy.scripted_registry import list_scripted_agent_names; print(list_scripted_agent_names())"
```

Common scripted policy names include:

- Baselines: `baseline`, `tiny_baseline`, `ladybug_py`
- Nim baselines: `thinky`, `race_car`, `ladybug`, `nim_random`
- CogsGuard core: `role`, `role_nim`, `wombo`
- CogsGuard variants: `alignall`, `cogsguard_control`, `cogsguard_targeted`, `cogsguard_v2`
- Teacher: `teacher`

For the full registry snapshot, see `docs/scripted-agent-registry.md`.

Tutorial role specialists (`miner`, `scout`, `aligner`, `scrambler`) are canonical in `cogames`, not this package. For
the teacher policy, you can pass `role_vibes` as a comma-separated list:

```
metta://policy/teacher?role_vibes=miner,scout
```

Fixed-role mixes and explicit orderings are configured via `role` parameters:

Examples:

```
metta://policy/role?role_cycle=aligner,miner,scrambler,scout
metta://policy/role?role_order=aligner,miner,aligner,miner,scout
```

## Recipe usage

The `recipes.experiment.scripted_agents` recipe accepts the same scripted policy names:

```
./tools/run.py recipes.experiment.scripted_agents.play agent=thinky suite=cvc_arena
./tools/run.py recipes.experiment.scripted_agents.play agent=role suite=cogsguard
```

## Included policies

- Short names map to the fastest implementation (Nim when available, otherwise Python).
- `_nim` aliases exist when there is a Nim implementation alongside Python.
- See `docs/scripted-agent-registry.md` for the canonical short-name list.
- Teacher wrapper: `teacher` (`teacher_nim`) forces an initial role/vibe, then delegates to the Nim policy.

## Supervisor action contract

When used as supervisors, `cogames-agents` policies emit split-action labels in one canonical space:

- Primary actions: `[0, len(action_names))`
- Vibe actions: `[len(action_names), len(action_names) + len(vibe_action_names))`

This matches `PolicyEnvInterface` action ordering (`[*action_names, *vibe_action_names]`) and the `MettaGridPufferEnv`
split-action supervisor path.

## Docs

- `docs/mettaboxes.md` (mettabox usage guide)
- `docs/aws-sso-on-mettabox.md` (AWS SSO login from inside mettabox containers)
