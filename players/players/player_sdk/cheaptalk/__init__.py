"""Channel discipline for rate-limited short-text ("cheap talk") channels.

Many arenas give agents a constrained broadcast primitive: short messages,
a per-agent rate limit, delivery to everyone in range (opponents included),
and persistent display objects that outlive the send. Using such a channel
well is two disciplines, each its own module:

- `budget`: the SEND side. Behaviors offer candidate messages during a
  decision; one arbiter enforces the rate budget, per-topic cooldowns, and
  priority ordering, and emits at most one message. Without this, the
  behavior that happens to run last wins the slot and urgent traffic loses
  to chatter.
- `receiver`: the RECEIVE side. A message rendered for many frames must be
  ingested once. The latch keys on (speaker, text) and re-admits only when
  the text changes or a display lifetime passes.

Both are engine-agnostic: limits, lifetimes, and priorities are constructor
parameters; nothing here knows what the messages mean.
"""

from players.player_sdk.cheaptalk.budget import TalkBudget
from players.player_sdk.cheaptalk.receiver import PersistenceLatch

__all__ = ["TalkBudget", "PersistenceLatch"]
