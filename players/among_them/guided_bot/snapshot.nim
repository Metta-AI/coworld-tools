## Snapshot rendering — produces the JSON snapshot the LLM sees.
##
## DESIGN.md §8.3 defines the snapshot format. This module takes a
## `Belief` and renders a curated JSON string suitable for injection
## into an LLM prompt. The output is structured, not prose.
##
## Screen→world coordinate conversion uses `geometry.visibleCrewmate
## WorldX/Y` and `geometry.roomNameAt` for room names. Fields that
## are absent or unknown are omitted (the LLM tolerates missing
## keys better than null sentinels).
##
## The snapshot is rendered synchronously on the main thread before
## being submitted to the guidance worker. Rendering is O(belief
## fields), not O(map tile count) — no map-pixel iteration.

import std/json
import types
import perception/data
import perception/geometry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

proc phaseStr(phase: GamePhase): string =
  case phase
  of PhaseGameplay:      "gameplay"
  of PhaseVoting:        "voting"
  of PhaseInterstitial:  "interstitial"
  of PhaseGameOver:      "game_over"
  of PhaseLobby:         "lobby"
  of PhaseUnknown:       "unknown"

proc roleStr(role: BotRole): string =
  case role
  of RoleCrewmate: "crewmate"
  of RoleImposter: "imposter"
  of RoleUnknown:  "unknown"

proc modeStr(mode: ModeName): string =
  case mode
  of ModeIdle:             "idle"
  of ModeTaskCompleting:   "task_completing"
  of ModeFear:             "fear"
  of ModeInvestigating:    "investigating"
  of ModeReporting:        "reporting"
  of ModePretending:       "pretending"
  of ModeHunting:          "hunting"
  of ModeFleeing:          "fleeing"
  of ModeAlibiBuilding:    "alibi_building"
  of ModeSabotageWatching: "sabotage_watching"
  of ModeMeeting:          "meeting"

proc sourceStr(source: DirectiveSource): string =
  case source
  of SourceDefault: "default"
  of SourceLlm:     "llm"
  of SourceReflex:  "reflex"

proc colorName(idx: int): string =
  ## Safe colour-name lookup; returns "unknown" for out-of-range indices.
  if idx >= 0 and idx < PaletteColorTableSize:
    PlayerColorNames[idx]
  else:
    "unknown"

proc taskStateStr(state: TaskSlotState): string =
  case state
  of TaskNotDoing:  "not_doing"
  of TaskCheckout:  "checkout"
  of TaskConfirmed: "confirmed"
  of TaskCompleted: "completed"

proc wakeReasonStr(w: WakeReason): string =
  case w
  of WakePeriodic:              "periodic"
  of WakeBodySeen:              "body_seen"
  of WakeKillCooldownReady:     "kill_cooldown_ready"
  of WakeChatObserved:          "chat_observed"
  of WakeMeetingStarted:        "meeting_started"
  of WakeRoleRevealed:          "role_revealed"
  of WakeReflexFired:           "reflex_fired"
  of WakeDirectiveExpiringSoon: "directive_expiring_soon"

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

proc renderSnapshot*(belief: Belief): string =
  ## Render the curated belief snapshot as JSON per DESIGN.md §8.3.
  ## Returns a compact JSON string.
  var root = newJObject()

  root["tick"] = newJInt(belief.tick)

  # --- self ---
  var selfObj = newJObject()
  selfObj["role"] = newJString(roleStr(belief.self.role))
  selfObj["color"] = newJString(colorName(belief.self.colorIndex))
  selfObj["is_ghost"] = newJBool(belief.self.isGhost)
  selfObj["alive"] = newJBool(belief.self.alive)
  if belief.percep.localized:
    selfObj["position"] = %*[belief.percep.selfX, belief.percep.selfY]
    let room = roomNameAt(referenceData.map, belief.percep.selfX, belief.percep.selfY)
    if room != "unknown":
      selfObj["room"] = newJString(room)
  selfObj["kill_cooldown_remaining"] = newJInt(belief.self.killCooldownRemaining)
  var impColors = newJArray()
  for c in belief.self.knownImposterColors:
    impColors.add newJString(colorName(c))
  selfObj["known_imposters"] = impColors
  root["self"] = selfObj

  # --- phase ---
  root["phase"] = newJString(phaseStr(belief.self.phase))

  # --- current_mode ---
  var modeObj = newJObject()
  modeObj["name"] = newJString(modeStr(belief.directive.mode))
  modeObj["source"] = newJString(sourceStr(belief.directive.source))
  modeObj["ticks_active"] = newJInt(
    if belief.directive.issuedAtTick > 0:
      belief.tick - belief.directive.issuedAtTick
    else:
      0
  )
  root["current_mode"] = modeObj

  # --- visible_now ---
  var visObj = newJObject()

  # Players (visible crewmates).
  var playersArr = newJArray()
  for cm in belief.percep.visibleCrewmates:
    var pObj = newJObject()
    pObj["color"] = newJString(colorName(cm.colorIndex))
    if belief.percep.localized:
      let wx = visibleCrewmateWorldX(belief.percep.cameraX, cm.x)
      let wy = visibleCrewmateWorldY(belief.percep.cameraY, cm.y)
      pObj["position"] = %*[wx, wy]
      let room = roomNameAt(referenceData.map, wx, wy)
      if room != "unknown":
        pObj["room"] = newJString(room)
    playersArr.add pObj
  visObj["players"] = playersArr

  # Bodies.
  var bodiesArr = newJArray()
  for bm in belief.percep.visibleBodies:
    var bObj = newJObject()
    if belief.percep.localized:
      let wx = visibleCrewmateWorldX(belief.percep.cameraX, bm.x)
      let wy = visibleCrewmateWorldY(belief.percep.cameraY, bm.y)
      bObj["position"] = %*[wx, wy]
      let room = roomNameAt(referenceData.map, wx, wy)
      if room != "unknown":
        bObj["room"] = newJString(room)
    bodiesArr.add bObj
  visObj["bodies"] = bodiesArr

  # Task icons on screen (just the indices we know about).
  var taskIconsArr = newJArray()
  for ti in belief.percep.visibleTaskIcons:
    # The IconMatch has screen coords; we could map to task index
    # but the current pipeline doesn't carry the task index on
    # IconMatch. Just report count for now.
    discard ti
  visObj["task_icons_on_screen"] = taskIconsArr
  root["visible_now"] = visObj

  # --- memory ---
  var memObj = newJObject()

  # Per-player summaries. During meetings include all voting slots so the
  # LLM can reason about alive/dead and no-evidence cases explicitly.
  var ppObj = newJObject()
  for i in 0 ..< PlayerColorCount:
    let ps = belief.memory.perPlayer[i]
    let includePlayer =
      ps.lastSeenTick > 0 or belief.self.phase == PhaseVoting or
      ps.role != RoleUnknown or not ps.alive
    if includePlayer:
      var pSummary = newJObject()
      pSummary["color"] = newJString(colorName(i))
      pSummary["alive"] = newJBool(ps.alive)
      pSummary["role"] = newJString(roleStr(ps.role))
      if ps.lastSeenTick > 0:
        pSummary["last_seen_tick"] = newJInt(ps.lastSeenTick)
      if ps.lastSeenX != 0 or ps.lastSeenY != 0:
        let room = roomNameAt(referenceData.map, ps.lastSeenX, ps.lastSeenY)
        if room != "unknown":
          pSummary["last_seen_room"] = newJString(room)
      pSummary["times_near_body"] = newJInt(ps.timesNearBody)
      pSummary["times_witnessed_kill"] = newJInt(ps.timesWitnessedKill)
      pSummary["ejected"] = newJBool(ps.ejected)
      ppObj[colorName(i)] = pSummary
  memObj["per_player"] = ppObj
  root["memory"] = memObj

  # --- task_state ---
  var taskObj = newJObject()
  var stationsArr = newJArray()
  for i, slot in belief.tasks.slots:
    var sObj = newJObject()
    sObj["index"] = newJInt(i)
    sObj["state"] = newJString(taskStateStr(slot.state))
    sObj["checkout"] = newJBool(slot.checkout)
    sObj["resolved_not_mine"] = newJBool(slot.resolvedNotMine)
    stationsArr.add sObj
  taskObj["stations"] = stationsArr
  if belief.tasks.inProgressIndex >= 0:
    taskObj["in_progress_index"] = newJInt(belief.tasks.inProgressIndex)
  root["task_state"] = taskObj

  # --- wake_up_reasons ---
  var wakeArr = newJArray()
  for w in belief.flags.wakeReasons:
    wakeArr.add newJString(wakeReasonStr(w))
  root["wake_up_reasons"] = wakeArr

  # --- meeting context ---
  if belief.self.phase == PhaseVoting:
    var meetingObj = newJObject()
    meetingObj["player_count"] = newJInt(belief.percep.votingPlayerCount)
    meetingObj["self_slot"] = newJInt(belief.percep.votingSelfSlot)
    meetingObj["cursor"] = newJInt(belief.percep.votingCursor)
    var selectable = newJArray()
    for i in 0 ..< max(0, belief.percep.votingPlayerCount):
      if i != belief.percep.votingSelfSlot and belief.memory.perPlayer[i].alive:
        selectable.add newJString(colorName(i))
    meetingObj["selectable_players"] = selectable
    var votesObj = newJObject()
    for voter in 0 ..< PlayerColorCount:
      let target = belief.social.votesCast[voter]
      if target == -1:
        votesObj[colorName(voter)] = newJString("skip")
      elif target >= 0 and target < PlayerColorCount:
        votesObj[colorName(voter)] = newJString(colorName(target))
    meetingObj["votes_observed"] = votesObj

    var alibiArr = newJArray()
    for i in 0 ..< PlayerColorCount:
      let ps = belief.memory.perPlayer[i]
      if i != belief.self.colorIndex and ps.alive and ps.lastSeenTick > 0 and
         belief.tick - ps.lastSeenTick <= 480:
        var aObj = newJObject()
        aObj["color"] = newJString(colorName(i))
        aObj["last_seen_tick"] = newJInt(ps.lastSeenTick)
        let room = roomNameAt(referenceData.map, ps.lastSeenX, ps.lastSeenY)
        if room != "unknown":
          aObj["last_seen_room"] = newJString(room)
        alibiArr.add aObj
    meetingObj["recent_alibi_witnesses"] = alibiArr
    root["meeting"] = meetingObj

  # --- chat ---
  var visibleChatArr = newJArray()
  for cl in belief.social.currentMeetingChat:
    var clObj = newJObject()
    clObj["tick"] = newJInt(cl.tick)
    clObj["speaker"] = newJString(colorName(cl.speakerColor))
    clObj["text"] = newJString(cl.text)
    visibleChatArr.add clObj
  root["visible_chat"] = visibleChatArr

  var recentChatArr = newJArray()
  for cl in belief.social.recentChat:
    var clObj = newJObject()
    clObj["tick"] = newJInt(cl.tick)
    clObj["speaker"] = newJString(colorName(cl.speakerColor))
    clObj["text"] = newJString(cl.text)
    recentChatArr.add clObj
  root["recent_chat"] = recentChatArr

  $root
