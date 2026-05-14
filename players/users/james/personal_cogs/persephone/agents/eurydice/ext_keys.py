"""Central registry of belief_state.ext keys used by Eurydice."""
from __future__ import annotations

# Game-lifetime state
EURYDICE_ACCUMULATORS = "eurydice_accumulators"
PLAYER_KNOWLEDGE = "player_knowledge"

# Per-meta_decide rebuild
STRATEGIC_STATE = "strategic_state"

# Whisper-lifetime state
WHISPER_EXCHANGE_STATE = "whisper_exchange_state"

# Mode-lifetime state
SCOUT_STATE = "scout_state"
HOLD_POSITION_STATE = "hold_position_state"
WHISPER_MODE_STATE = "whisper_mode_state"
PROBE_STATE = "probe_state"
PROBE_FAILURES = "probe_failures"

# Post-whisper reconciliation
INFO_SCREEN_RECONCILE_PENDING = "info_screen_reconcile_pending"

# Per-tick flags (cleared after read)
MODE_COMPLETE = "mode_complete"
FOUND_TARGET = "found_target"
WHISPER_EXIT_REASON = "whisper_exit_reason"

# Persistent hysteresis (survives across ticks)
LAST_DIRECTIVE = "last_directive"
LAST_NON_WHISPER_DIRECTIVE = "last_non_whisper_directive"
LAST_DIRECTIVE_MODE = "last_directive_mode"
LAST_DIRECTIVE_TICK = "last_directive_tick"

# Stored in inferences dict (replaced each iteration)
LAST_PHASE = "_last_phase"
LAST_EXCHANGE_STATUS = "_last_exchange_status"
LAST_PARTNER_FOUND = "_last_partner_found"
