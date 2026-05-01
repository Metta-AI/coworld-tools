"""Tunable constants for modulabot.

Grouped by concern, with commentary on what each knob controls and which
module reads it. Tuning knobs worth A/B-testing live here; one-off magic
numbers stay local to their module.

Mirrors modulabot's ``tuning.nim`` in spirit, adapted for the cogames action
cadence (which is different from the WebSocket bot's 24 Hz frame rate).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Screen geometry
# ---------------------------------------------------------------------------

SCREEN_WIDTH = 128
SCREEN_HEIGHT = 128
CENTER_X = SCREEN_WIDTH // 2
CENTER_Y = SCREEN_HEIGHT // 2

# ---------------------------------------------------------------------------
# Movement / navigation
# ---------------------------------------------------------------------------

#: Manhattan deadband around the screen centre below which we stop steering
#: and start pressing A (we're on top of the target). Used by tight
#: "am I interacting with this?" checks — the arrive-and-hold decision,
#: the kill-in-range test, etc. Movement arrival uses the looser
#: :data:`ARRIVAL_DEADBAND` instead so momentum overshoot doesn't cause
#: orbit-around-target behaviour.
CLOSE_DISTANCE = 12

#: Manhattan deadband for "close enough, stop steering" during
#: navigation. Looser than :data:`CLOSE_DISTANCE` so the BitWorld
#: sim's per-tick momentum (bots carry ~2 px/tick after releasing a
#: direction) doesn't push us back outside the tight interaction
#: deadband every frame. Small value → oscillation; large value →
#: sloppy arrival. Tune between 14 and 22.
ARRIVAL_DEADBAND = 18

#: Frame-to-frame world-position delta above which the motion tracker
#: treats the sample as a teleport (post-interstitial respawn,
#: localizer re-lock, sim rubber-band). Samples above this threshold
#: reseed the previous-position record instead of updating velocity
#: — keeps the stuck detector from thinking we sprinted 400 pixels
#: in one tick.
TELEPORT_VELOCITY_THRESHOLD = 16

#: Minimum ticks between A\* re-plans when the goal hasn't changed.
#: Re-planning every tick is correct but burns 1-30 ms per call in
#: Python; at 24 Hz that's too much CPU for a rarely-needed refresh.
#: A path's lookahead is 18 pixels, and the bot moves ~2 px/tick, so
#: a path stays usable for ~9 ticks before the waypoint drifts far
#: behind us — re-plan comfortably within that window.
PATH_REPLAN_INTERVAL = 6

#: Manhattan distance (world pixels) the bot has to travel since the
#: last plan before we force a re-plan regardless of
#: ``PATH_REPLAN_INTERVAL``. Protects against the case where the bot
#: got teleported (post-interstitial respawn) and the cached path
#: is suddenly pointing the wrong way.
PATH_REPLAN_MOVE_THRESHOLD = 24

#: Manhattan deadband for "on top of a body, report it".
BODY_REPORT_DISTANCE = 18

#: Manhattan deadband for "adjacent to a kill target, press A to kill".
KILL_RANGE = 18

#: Manhattan deadband beyond which radar-tracked offscreen targets stop
#: being interesting — stop spinning to face them and fall through to patrol.
RADAR_DEADBAND = 4

#: Consecutive ticks of zero-velocity-while-holding-direction before we
#: trigger the anti-stuck jiggle.
STUCK_TICKS = 20

#: Duration in ticks of the perpendicular jiggle when we decide we're stuck.
JIGGLE_TICKS = 8

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

#: Ticks we hold A on a task before declaring it done. The BitWorld sim's
#: task completion window is 72 ticks; we pad a bit so we don't lift A a
#: frame too early.
TASK_HOLD_TICKS = 84

#: Minimum ticks the crewmate policy commits to a chosen task before
#: reconsidering the target. Without this, :func:`best_actionable_task`
#: re-scores the task list every tick, and tiny perception flickers
#: (sprite match missing for one frame, off-screen→on-screen transition,
#: crossing an ``active`` rect boundary) flip the goal and invalidate
#: the A\* path. The imposter has an equivalent
#: :data:`IMPOSTER_FOLLOW_SWAP_MIN_TICKS` for followee hysteresis;
#: this is the crewmate analogue. Overridden by higher-priority events:
#: task completion (``hold_ticks > 0``), body sighting, or an ``active``
#: task appearing underfoot.
TASK_COMMIT_TICKS = 48

#: Ticks between on-the-move A presses when approaching a task. Helps
#: pick up incidental-icon tasks while pathing through a room.
ACTION_PERIOD = 24

#: Window within ACTION_PERIOD during which we press A. Keep small — we
#: don't want A stuck down during normal navigation.
ACTION_WINDOW = 3

# ---------------------------------------------------------------------------
# Imposter
# ---------------------------------------------------------------------------

#: Ticks we stick with a followee before considering swapping, even with
#: two crewmates visible. Prevents whiplash steering.
IMPOSTER_FOLLOW_SWAP_MIN_TICKS = 240

#: Ticks inside the fake-task "precise approach" before pressing A.
IMPOSTER_FAKE_TASK_APPROACH_RADIUS = 12

#: Minimum and maximum ticks to stay on a fake task once the die lands.
IMPOSTER_FAKE_TASK_MIN_TICKS = 90
IMPOSTER_FAKE_TASK_MAX_TICKS = 180

#: Cooldown between fake-task bouts so we don't stand on the same station
#: forever.
IMPOSTER_FAKE_TASK_COOLDOWN_TICKS = 240

#: Probability (numerator / denominator) of starting a fake task when we
#: pass by an eligible task station. The Nim default is 1/12.
IMPOSTER_FAKE_TASK_CHANCE = 1
IMPOSTER_FAKE_TASK_CHANCE_DENOM = 12

#: Screen-space "near an eligible task" radius for the fake-task die roll.
IMPOSTER_FAKE_TASK_NEAR_RADIUS = 32

#: Window in ticks after a kill-A-press during which a freshly-seen body
#: close to the kill site is treated as "our" body for self-report logic.
IMPOSTER_SELF_REPORT_RECENT_TICKS = 30

#: Manhattan radius around the last-kill point within which a body still
#: counts as "our" kill.
IMPOSTER_SELF_REPORT_RADIUS = KILL_RANGE + 8

# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------

#: Ticks we wait on the voting screen before pressing A to commit our vote.
#: The Nim bot uses 100; cogames vote timers are 600 ticks (the default
#: BitWorld config), so a shorter listen window is fine — we need to leave
#: room to drive the cursor to the correct slot.
VOTE_LISTEN_TICKS = 36

#: Ticks between cursor nudges on the voting screen. Holding a direction
#: doesn't advance the cursor in BitWorld — it edge-triggers, so we alternate
#: direction + noop every N ticks.
VOTE_CURSOR_STEP_TICKS = 2

#: Hard cap on how many cursor-step attempts we make before giving up and
#: pressing A wherever we are. Keeps us from missing the vote window if our
#: target isn't where we think it is.
VOTE_CURSOR_MAX_STEPS = 16

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

#: Minimum gap between chat messages from the same agent in ticks. The sim
#: only accepts chat during voting; this cooldown just prevents us from
#: sending two messages in rapid succession within the same meeting.
CHAT_COOLDOWN_TICKS = 72

#: Hard cap on chat length in characters. Both the sim and the cogames
#: BitWorld shim enforce 75; we trim more aggressively so truncation never
#: cuts off a colour name mid-word.
CHAT_MAX_CHARS = 72

# ---------------------------------------------------------------------------
# Perception thresholds (pixel-observation fallback only)
# ---------------------------------------------------------------------------

#: Percent of pixels that must be black for us to believe the frame is an
#: interstitial (voting / role reveal / game over).
INTERSTITIAL_BLACK_PERCENT = 30

#: Palette index of the "task radar dot" on the screen edge.
TASK_RADAR_COLOR = 8  # PICO-8 red

#: Pixel margin (from each edge) to sample when looking for radar dots.
RADAR_MARGIN = 2

#: Screen-space rectangle for the kill icon in the lower-left HUD.
#: Matches the cyborg reference policy.
KILL_ICON_X = 1
KILL_ICON_Y = SCREEN_HEIGHT - 13
KILL_ICON_SIZE = 12

# ---------------------------------------------------------------------------
# Debugging / tracing
# ---------------------------------------------------------------------------

#: When true, :meth:`Bot.fired` warnings are raised as errors in tests.
#: Off by default in production play.
STRICT_BRANCH_ID = False


__all__ = [name for name in globals() if name.isupper()]
