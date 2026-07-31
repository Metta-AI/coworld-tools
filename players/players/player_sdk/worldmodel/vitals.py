"""vitals.py — Retreat / rest decisions from HP, energy, distance.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack; original module name ``swgy_vitals.py``).

Owns the threshold math that every role re-derives in its own
``_decide_action`` head. Anchor selection (which friendly cell is
"home") stays in the caller — this module only takes a precomputed
``anchor_distance`` and decides whether to retreat or whether the
agent is rested enough to leave again.

Sources of the patterns being consolidated:

* ``policy_scrambler.py:215-280`` — ``hp < walk_home + RETREAT_BUFFER``
  *or* ``hp < HP_FLOOR``. Retreat buffer 15, floor 30.
* ``policy_aligner.py``, ``policy_miner.py`` — distance-aware buffers
  with the same shape.
* ``scripted/scripted_miner.py:111-133`` — RESTING / SURVIVING /
  MINING mode machine. Its HP "topped up" ceiling (≤80) is dropped
  here because friendly territory restores HP at +100/tick (saturates
  immediately; see ``docs/answers.md:354-360``), so an HP-based
  topped-up check is meaningless. Energy refills more slowly, so
  energy keeps a ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VitalsConfig:
    """Knobs for retreat and rest detection."""

    # Walk-home margin. Retreat triggers when ``hp < anchor_distance +
    # retreat_buffer``: enough HP to walk back plus this many ticks
    # of overshoot.
    retreat_buffer: int = 15

    # Absolute HP retreat trigger. Always retreats below this even if
    # close to anchor.
    hp_floor: int = 30

    # Absolute energy retreat trigger. Same rationale: even at the
    # anchor, if energy is this low we can't afford the next move.
    energy_floor: int = 8

    # Energy ceiling for "topped up" detection. Caller leaves None to
    # opt out (e.g., scrambler doesn't sit and rest).
    rest_energy_ceiling: int | None = None


def should_retreat(
    hp: int,
    energy: int,
    anchor_distance: int,
    cfg: VitalsConfig,
) -> bool:
    """True if any retreat trigger fires.

    Triggers (any one is sufficient):
      * ``hp < cfg.hp_floor``           — absolute HP collapse.
      * ``hp < anchor_distance + cfg.retreat_buffer``  — not enough HP
        to walk back to anchor with margin.
      * ``energy < cfg.energy_floor``   — absolute energy collapse.
    """
    if hp < cfg.hp_floor:
        return True
    if energy < cfg.energy_floor:
        return True
    if hp < anchor_distance + cfg.retreat_buffer:
        return True
    return False


def is_topped_up(energy: int, cfg: VitalsConfig) -> bool:
    """True when energy has reached ``cfg.rest_energy_ceiling``.

    Returns False if the ceiling is None — the caller hasn't opted
    into rest detection. HP has no ceiling: friendly territory
    saturates HP in one tick, so an HP-based "topped up" check is
    always trivially true when in territory and otherwise meaningless.
    """
    if cfg.rest_energy_ceiling is None:
        return False
    return energy >= cfg.rest_energy_ceiling


def hp_deficit(hp: int, anchor_distance: int, cfg: VitalsConfig) -> int:
    """How many HP we have above the walk-home threshold.

    Positive: HP overhead beyond the retreat trigger.
    Zero or negative: we should be retreating (negative magnitude is
    how badly we're under).

    Useful for callers that want to score "how aggressive can I be?"
    without flipping into a full retreat.
    """
    threshold = anchor_distance + cfg.retreat_buffer
    return hp - threshold
