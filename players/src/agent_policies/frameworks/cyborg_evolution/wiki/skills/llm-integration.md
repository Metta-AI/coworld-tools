# LLM Integration Patterns

How to effectively use LLM strategic advisors in real-time game agents.

## The Consultation Model

The LLM is NOT the decision-maker — the scripted brain is. The LLM is a strategic
advisor that issues high-level **directives** when significant game events occur.

```
Brain (every tick):  observe → decide → act    ← fast, deterministic
LLM (every ~200 ticks):  evaluate → advise    ← slow, strategic
```

**Why not just let the LLM decide every tick?**
- LLM latency (500-2000ms) makes per-tick calls impossible in real-time games
- LLM tokens are expensive at scale (thousands of games)
- Strategic decisions don't change every tick — every 100-300 ticks is sufficient
- A scripted brain provides reliable baseline behavior between consultations

## When to Consult

The trigger system fires LLM consultations based on events, not timers:

| Trigger Type | Priority | Example |
|---|---|---|
| Critical event | High | Agent died, lost territory, opponent detected |
| State change | Medium | Phase changed, new area discovered, resource threshold hit |
| Periodic | Low | Every N ticks as a baseline check-in |
| Idle | Medium | Agent stuck doing the same thing for 30+ ticks |
| Operator | Highest | Human injects a message via console |

**Trigger priorities** ensure the most important events get LLM attention first.
Debouncing prevents the same event type from firing multiple times in quick succession.

## Directive Structure

The LLM responds with a JSON directive:

```json
{
  "role": "gatherer",
  "command": "explore",
  "target": [50, 30],
  "reasoning": "No gold found yet, exploring northwest quadrant",
  "hold": false,
  "until": "gold_found"
}
```

The brain's `apply_directive()` method interprets this. Common patterns:
- **Role switch**: change the brain's high-level strategy
- **Target override**: send the agent to a specific location
- **Hold**: maintain current strategy regardless of scripted triggers
- **Until condition**: directive expires when a named condition is met

## System Prompt Design

The system prompt is the LLM's persistent context. Structure it as:

```
1. Identity: "You are a strategic advisor for a {game_name} agent"
2. Game rules: Compact summary of mechanics relevant to strategy
3. Available actions: What roles/commands the LLM can issue
4. Response format: Strict JSON schema with examples
5. Cross-game learnings: Patterns from prior games (injected automatically)
6. Wiki knowledge: Game-specific strategy docs (loaded from wiki/)
```

**Tips**:
- Keep the system prompt under 4000 tokens — the LLM needs room for game state
- Put the JSON format at the end, closest to where the LLM generates its response
- Include negative examples: "Do NOT suggest X because..."
- Update the wiki files, not the system prompt, for evolving knowledge

## Context Building (Narrator)

Each consultation sends the LLM a context string built from memory. Structure:

```
[TRIGGER: phase_change]
[CURRENT STATE]
  Position, HP, resources, inventory, score...
[RECENT EVENTS]
  Last 10-15 episodic events
[STRATEGIC FACTS]
  Relevant active facts from strategic memory
[ACTIVE DIRECTIVE]
  Current directive and how long it's been active
[PERFORMANCE]
  Rates and trends from perf windows
```

**Tips**:
- Front-load the most important information (LLMs attend more to the start)
- Truncate long lists (last 15 events, not all 500)
- Include delta information: "resources +20 since last consult"
- Format for scannability: labels, brackets, short lines

## Conversation Management

The harness maintains a sliding conversation window:
- User messages = game state contexts (one per consultation)
- Assistant messages = LLM directive responses
- Window: last 30 messages (15 exchanges)
- Older messages are dropped, not summarized

**Why not summarize?** At 200-tick intervals in a 2500-tick game, you get ~12
consultations. A 30-message window covers the entire game. Summarization adds latency
and loses detail.

## Token Budget

| Component | Typical Budget |
|---|---|
| System prompt | 2000-4000 tokens |
| Game state context (user) | 500-1500 tokens |
| LLM response (directive) | 200-500 tokens |
| Conversation history (15 exchanges) | 5000-10000 tokens |
| **Total per call** | **8000-16000 tokens** |

At 10-15 calls per game and $3/M input tokens (Sonnet-class), that's ~$0.50-1.00/game.
Opus-class analysis adds ~$0.10-0.30/game.

## Surrender Detection

The framework detects when the LLM declares the game lost (phrases like "game lost",
"surrender", "game over" in the reasoning field). This saves tokens by ending hopeless
games early, but guards against premature surrender:

- **Never surrender before tick 200** (if movement is broken)
- **Never surrender before tick 1000** (if the agent has been mobile)
- Games can override these thresholds

## Error Handling

LLM calls fail. The harness handles:
- **Parse failure**: Try regex extraction of JSON from the response
- **Invalid directive**: Fall back to default role + explore
- **API error**: Log the error, append `[error]` to conversation, skip this consultation
- **Timeout**: Same as API error — the brain continues on autopilot

Never let an LLM failure crash the game loop.
