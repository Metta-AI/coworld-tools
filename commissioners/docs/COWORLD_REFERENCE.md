# Coworld Reference

> Primary navigation guide for coding agents working in this `commissioners` project. This is not the authoritative coworld spec - it is an index. Treat the metta sources as the source of truth.

## 1. What this project is

`commissioners` is a scaffolded implementation repo for the coworld `commissioner` role. A coworld bundles one game container, one or more player containers, and a `coworld_manifest.json`. The manifest can also declare optional roles, including `commissioner`.

Commissioners are different from the other undefined optional roles: metta already has a commissioner protocol for tournament round orchestration.

## 2. TL;DR for a future agent

- Canonical coworld package: `~/coding/metta/packages/coworld/`.
- Manifest source of truth: `~/coding/metta/packages/coworld/src/coworld/types.py`.
- Commissioner protocol: `~/coding/metta/packages/coworld/src/coworld/commissioner/protocol.py`.
- Generated manifest schema: `~/coding/metta/packages/coworld/src/coworld/coworld_manifest_schema.json`.
- Game runtime contract: `~/coding/metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md`.
- Role list: `player`, `grader`, `reporter`, `commissioner`, `diagnoser`, `optimizer`.
- Shared runnable shape: image + optional `run` argv + optional public `env`.

## 3. Manifest role shape

All declared non-game roles use `CoworldDeclaredRoleSpec`:

```python
class CoworldDeclaredRoleSpec(CoworldDeclaredRunnableSpec):
    type: Literal["player", "grader", "reporter", "commissioner", "diagnoser", "optimizer"]
```

For commissioners, the top-level manifest field is:

```python
commissioner: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
```

Certification validates every declared role image is reachable. Tournament orchestration uses the commissioner protocol, not the episode runner's player/game loop.

## 4. Useful metta paths

| Question | Start here |
| --- | --- |
| What is a coworld? | `packages/coworld/src/coworld/COWORLD_README.md` |
| What is the commissioner protocol? | `packages/coworld/src/coworld/commissioner/protocol.py` |
| What is in the manifest? | `packages/coworld/src/coworld/types.py` |
| How are role images validated? | `packages/coworld/src/coworld/certifier.py` |
| How does tournament inspection work? | `packages/coworld/src/coworld/tournament_cli.py` |
| What does a simple example look like? | `packages/coworld/src/coworld/examples/paintarena/` |
| What does the runnable spec say? | `docs/specs/0043-user-container-management.md` |

## 5. Keep this file honest

Update this file when the metta repo changes the commissioner protocol, role fields, example coworlds, or tournament orchestration behavior.
