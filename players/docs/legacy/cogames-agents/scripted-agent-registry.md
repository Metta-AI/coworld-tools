# Scripted Agent Registry

This snapshot mirrors the short-name registry in `cogames_agents.policy.scripted_registry`. Each entry maps to
`metta://policy/<short_name>`.

Regenerate the list with:

```bash
python -c "from cogames_agents.policy.scripted_registry import list_scripted_agent_names; print(list_scripted_agent_names())"
```

## Baselines and demos (Python)

- `baseline` - BaselinePolicy (exploration + gathering)
- `tiny_baseline` - DemoPolicy (minimal baseline)
- `ladybug_py` - UnclippingPolicy (handles clipped extractors)

## Nim multi-agent baselines

- `thinky` - Nim Thinky policy
- `race_car` - Nim RaceCar policy
- `ladybug` - Nim Ladybug policy
- `nim_random` - Nim random policy

## CogsGuard (Nim)

- `role_nim` - Nim multi-role policy
- `alignall` - Nim align-all policy

## CogsGuard (Python)

- `role` - Python multi-role policy
- `wombo` - Generalist multi-role policy
- `cogsguard_control` - Control variant
- `cogsguard_targeted` - Targeted variant
- `cogsguard_v2` - V2 variant
- `teacher` - Teacher wrapper over Nim multi-role

## Canonical Tutorial Roles (cogames)

- `miner`, `scout`, `aligner`, `scrambler` are registered in `cogames.policy.role_policies`.
