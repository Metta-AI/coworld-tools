# Role vs Role-Nim Parity Findings (February 22, 2026)

This note captures live findings from `metta3` after fetching `origin/main` and running CogsGuard training/perf checks.

## Scope

- Compare teacher-led SPS across candidate scripted teachers.
- Check whether `metta://policy/role_nim` and `metta://policy/role` are behaviorally close enough to swap aliases.

## Environment

- Host: `metta3`
- Date: February 22, 2026
- Repo state on host: `main` at `origin/main`
- Recipe: `recipes.experiment.cogsguard.train`

## Teacher SPS Results

First-epoch SPS from tmux progress blocks:

- `teacher.policy_uri=metta://policy/role`
  - Run: `relh-cogsguard-teacher-led-20260222-124149-r6`
  - SPS: `2,377`
- no teacher (default `cogsguard.train()` teacher settings, i.e. none)
  - Run: `relh-cogsguard-noteacher-20260222-130534`
  - SPS: `63,867`
- `teacher.policy_uri=metta://policy/nlanky?miner=4&aligner=2&disable_role_switching=1`
  - Run: `relh-cogsguard-nlanky-teacher-20260222-130802`
  - SPS by epoch: `44,784`, `46,779`, `50,313`

Interpretation:

- The severe slowdown is specific to the `role` teacher configuration used in that test.
- `nlanky` is substantially faster than `role` as teacher, but still slower than no-teacher.

## Role vs Role-Nim Parity Checks

Command:

```bash
uv run cogames-agents/scripts/run_cogsguard_parity.py \
  --agents 8 --steps <N> --seed <S> \
  --policy-a metta://policy/role_nim \
  --policy-b metta://policy/role
```

Results:

### Seed 42, Steps 2000

- `role_nim` move success rate: `0.153` (`1967/12858`)
- `role` move success rate: `0.403` (`5527/13707`)
- Large action distribution gap: `noop` delta `+3584` for `role_nim` (A-B)

### Seed 43, Steps 1000

- `role_nim` move success rate: `0.189`
- `role` move success rate: `0.489`
- `noop` delta: `+1780` for `role_nim`

### Seed 44, Steps 1000

- `role_nim` move success rate: `0.110`
- `role` move success rate: `0.523`
- `noop` delta: `+2107` for `role_nim`

Interpretation:

- `role_nim` and `role` are not at behavioral parity in current `main`.
- Alias swap (`role` -> Nim, Python `role` -> `role_py`) is not safe yet.

## Relevant Implementation Notes

- Python `role` implementation uses `CogsguardPolicy` (`short_names = ["role"]`) and has explicit vibe/role assignment
  logic.
- Nim `role_nim` implementation uses `CogsguardAgentsMultiPolicy` (`short_names = ["role_nim"]`) and currently ignores
  extra kwargs in `__init__(..., **_)`.

## Recommendation

Before any alias/default switch:

1. Add parity regression tests for `role_nim` vs `role` on fixed seeds.
2. Close the action/move-success gap.
3. Re-run parity + SPS checks and only switch aliases once parity criteria are met.
