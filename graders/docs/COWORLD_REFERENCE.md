# Coworld Reference

> Primary navigation guide for coding agents working in this `graders` project. This is not the authoritative coworld spec - it is an index. Treat the metta sources as the source of truth.

## 1. What this project is

`graders` is a scaffolded implementation repo for the coworld `grader` role. A coworld bundles one game container, one or more player containers, and a `coworld_manifest.json`. The manifest can also declare optional roles, including `grader`.

The grader role exists in the schema today, but it does not have a documented runtime contract and is not launched by the runner.

## 2. TL;DR for a future agent

- Canonical coworld package: `~/coding/metta/packages/coworld/`.
- Manifest source of truth: `~/coding/metta/packages/coworld/src/coworld/types.py`.
- Generated manifest schema: `~/coding/metta/packages/coworld/src/coworld/coworld_manifest_schema.json`.
- Game runtime contract: `~/coding/metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md`.
- Role list: `player`, `grader`, `reporter`, `commissioner`, `diagnoser`, `optimizer`.
- Shared runnable shape: image + optional `run` argv + optional public `env`.
- `commissioner` has a documented protocol in metta; `grader`, `diagnoser`, and `optimizer` are still undefined stubs.

## 3. Manifest role shape

All declared non-game roles use `CoworldDeclaredRoleSpec`:

```python
class CoworldDeclaredRoleSpec(CoworldDeclaredRunnableSpec):
    type: Literal["player", "grader", "reporter", "commissioner", "diagnoser", "optimizer"]
```

For graders, the top-level manifest field is:

```python
grader: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
```

Certification validates every declared role image is reachable, but the smoke-test episode currently launches only the game and certification players.

## 4. Useful metta paths

| Question | Start here |
| --- | --- |
| What is a coworld? | `packages/coworld/src/coworld/COWORLD_README.md` |
| What must a game container do? | `packages/coworld/src/coworld/GAME_RUNTIME_README.md` |
| What is in the manifest? | `packages/coworld/src/coworld/types.py` |
| How are role images validated? | `packages/coworld/src/coworld/certifier.py` |
| How does a local episode run? | `packages/coworld/src/coworld/runner/runner.py` |
| What does a simple example look like? | `packages/coworld/src/coworld/examples/paintarena/` |
| What does the runnable spec say? | `docs/specs/0043-user-container-management.md` |

## 5. Keep this file honest

Update this file when the metta repo gains a real grader runtime contract, new role fields, new example coworlds, or runner/certifier behavior that changes how graders are launched or validated.
