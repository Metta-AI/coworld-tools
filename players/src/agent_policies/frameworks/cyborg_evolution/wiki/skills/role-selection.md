# Role Selection & Transitions

Universal patterns for agents that can switch between strategic roles.

## The Role Abstraction

Most strategy games require the agent to fill different roles at different times:

| Game Type | Example Roles |
|---|---|
| Resource/territory | gatherer, builder, defender, attacker, scout |
| Social deduction | investigator, deceiver, coordinator, protector |
| Card/board | aggressor, controller, combo-builder, defender |
| Survival | forager, crafter, explorer, fighter |

The brain maintains a `current_role` that determines which decision method runs each tick.

## When to Switch Roles

Role transitions should be triggered by **game state**, not timers:

1. **Resource thresholds** — "I have enough materials, switch from gatherer to builder"
2. **Phase changes** — "Early game ended, switch from explorer to attacker"
3. **Event triggers** — "Enemy spotted nearby, switch to defender"
4. **LLM directive** — "Strategic advisor says switch to gatherer"
5. **Goal completion** — "Built the structure, switch back to gatherer"

## Transition Anti-Patterns

- **Oscillation**: Switching back and forth every few ticks. Fix: add hysteresis
  (minimum ticks in a role before allowing a switch).
- **Late transitions**: Staying in an opening role too long. Fix: set tick-based
  deadlines as fallback triggers.
- **Ignoring urgency**: Not switching to a defensive role when under attack. Fix:
  high-priority interrupt triggers.
- **Role amnesia**: Forgetting what you were doing after a brief interrupt. Fix:
  stack-based role management (push/pop).

## The Scripted Role Check

Before consulting the LLM, the brain should run a `scripted_role_check()` that handles
obvious role transitions. This covers cases where the LLM would be too slow:

```python
def scripted_role_check(self, snapshot):
    if snapshot["hp"] < 20:
        return "retreat"      # Survival override — no LLM needed
    if snapshot["enemy_nearby"] and self.role != "defender":
        return "defender"     # Reactive switch — time-critical
    if snapshot["resources"] >= BUILD_THRESHOLD and self.role == "gatherer":
        return "builder"      # State-driven transition
    return self.role          # No change
```

The LLM handles nuanced transitions the scripted check can't:
- "Should I keep gathering or is it time to attack?"
- "The opponent is ahead — change strategy entirely"
- "This opening isn't working — try a different approach"
