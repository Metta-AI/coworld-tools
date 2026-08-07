"""Send-side arbitration for a rate-limited message channel.

Behaviors call `offer()` freely during a decision; `arbitrate()` picks at
most one winner per call, enforcing:

- a GLOBAL spacing between sends (engines that silently drop too-frequent
  sends make client-side spacing the only way to keep intent and effect
  aligned — a dropped urgent message is worse than a delayed routine one);
- per-KEY cooldowns, so one topic cannot monopolize the channel;
- PRIORITY ordering among eligible candidates (ties: first offered wins).

Offers are cleared on every arbitrate() — candidates describe THIS
decision, never a queue. If a behavior still wants to say something next
tick, it offers again; that keeps stale intel from being transmitted late.

The optional `max_len` truncates in the engine-common way (truncate first,
then strip), so what the arbiter reports as sent matches what a
length-limited channel actually delivered.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Offer:
    text: str
    prio: int
    key: str
    cooldown: int
    order: int


@dataclass
class TalkBudget:
    spacing: int = 26           # min ticks between our sends
    max_len: int | None = None  # channel payload limit (None = unlimited)
    last_send_tick: int = -(1 << 30)
    _last_by_key: dict[str, int] = field(default_factory=dict)
    _offers: list[_Offer] = field(default_factory=list)
    _order: int = 0

    def offer(self, text: str, prio: int, *, key: str, cooldown: int = 0) -> None:
        """Queue a candidate for this decision. Empty (post-truncation)
        candidates are dropped."""
        clean = text
        if self.max_len is not None:
            clean = clean[: self.max_len]
        clean = clean.strip()
        if clean:
            self._offers.append(_Offer(clean, prio, key, cooldown, self._order))
            self._order += 1

    def arbitrate(self, tick: int) -> str | None:
        """Pick this decision's winner, or None. Consumes all offers."""
        offers, self._offers = self._offers, []
        if tick - self.last_send_tick < self.spacing:
            return None
        best: _Offer | None = None
        for o in sorted(offers, key=lambda o: (-o.prio, o.order)):
            last = self._last_by_key.get(o.key, -(1 << 30))
            if tick - last < o.cooldown:
                continue
            best = o
            break
        if best is None:
            return None
        self.last_send_tick = tick
        self._last_by_key[best.key] = tick
        return best.text
