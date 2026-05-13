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

import std/[json, strutils]
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
  of ModeReporting:        "reporting"
  of ModePretending:       "pretending"
  of ModeHunting:          "hunting"
  of ModeFleeing:          "fleeing"
  of ModeAlibiBuilding:    "alibi_building"
  of ModeMeeting:          "meeting"

proc sourceStr(source: DirectiveSource): string =
  case source
  of SourceDefault: "default"
  of SourceLlm:     "llm"
  of SourceReflex:  "reflex"

proc taskTargetToJson(target: TaskTarget): JsonNode =
  result = newJObject()
  case target.kind
  of TgtIndex:
    result["kind"] = newJString("index")
    result["task_index"] = newJInt(target.taskIndex)
  of TgtNearestMandatory:
    result["kind"] = newJString("nearest_mandatory")
  of TgtNearestAny:
    result["kind"] = newJString("nearest_any")
  of TgtSpecificRoom:
    result["kind"] = newJString("specific_room")
    result["room_id"] = newJInt(target.roomId)

proc paramsToJson(params: ModeParams): JsonNode =
  result = newJObject()
  case params.mode
  of ModeIdle:
    result["near_group"] = newJBool(params.idleNearGroup)
    if params.idleLingerValid:
      result["linger_at"] = %*[params.idleLingerAt.x, params.idleLingerAt.y]
  of ModeTaskCompleting:
    result["target"] = taskTargetToJson(params.tcTarget)
    result["abandon_on_nearby_body"] = newJBool(params.tcAbandonOnNearbyBody)
  of ModeReporting:
    result["body_location"] = %*[params.repBodyLocation.x,
                                  params.repBodyLocation.y]
  of ModePretending:
    result["target"] = taskTargetToJson(params.preTarget)
    result["loiter_ticks"] = newJInt(params.preLoiterTicks)
    result["may_swap_on_witness"] = newJBool(params.preMaySwapOnWitness)
  of ModeHunting:
    result["preferred_target"] = newJInt(params.huntPreferredTarget)
    result["max_witnesses"] = newJInt(params.huntMaxWitnesses)
    result["opportunistic"] = newJBool(params.huntOpportunistic)
    result["cover_mode"] = newJString(modeStr(params.huntCoverMode))
  of ModeFleeing:
    result["away_from"] = %*[params.fleeAwayFrom.x, params.fleeAwayFrom.y]
    result["min_distance"] = newJInt(params.fleeMinDistance)
    result["duration_ticks"] = newJInt(params.fleeDurationTicks)
  of ModeAlibiBuilding:
    result["companion_color"] = newJInt(params.aliCompanionColor)
    result["room_id"] = newJInt(params.aliRoomId)
    result["min_duration_ticks"] = newJInt(params.aliMinDurationTicks)
  of ModeMeeting:
    result["want_to_speak_first"] = newJBool(params.meetWantToSpeakFirst)

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

proc wakeReasonStr*(w: WakeReason): string =
  case w
  of WakePeriodic:              "periodic"
  of WakeBodySeen:              "body_seen"
  of WakeChatObserved:          "chat_observed"
  of WakeMeetingStarted:        "meeting_started"
  of WakeRoleRevealed:          "role_revealed"
  of WakeReflexFired:           "reflex_fired"
  of WakeDirectiveExpiringSoon: "directive_expiring_soon"

proc textNamesColor(text: string, color: int): bool =
  if color < 0 or color >= PlayerColorCount:
    return false
  let lower = text.toLowerAscii()
  let name = PlayerColorNames[color].toLowerAscii()
  name.len > 0 and lower.contains(name)

proc voteChoiceName(target: int): string =
  if target == -1:
    "skip"
  elif target == -2:
    "abstain"
  else:
    colorName(target)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

proc renderSnapshot*(belief: Belief, modeSummary: JsonNode = nil): string =
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
  # kill_ready reflects the lit kill button as seen by perception this
  # frame — the sole authority on whether the imposter can strike. The
  # bot does not track its own cooldown; only the live HUD state matters.
  selfObj["kill_ready"] = newJBool(belief.percep.killReady)
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
  modeObj["params"] = paramsToJson(belief.directive.params)
  if modeSummary != nil:
    modeObj["summary"] = modeSummary
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
      pSummary["near_body_evidence_score"] = newJInt(ps.nearBodyEvidenceScore)
      if ps.lastNearBodyTick > -1000000:
        pSummary["last_near_body_tick"] = newJInt(ps.lastNearBodyTick)
      if ps.lastNearBodyDistance >= 0:
        pSummary["last_near_body_distance"] = newJInt(ps.lastNearBodyDistance)
      if ps.closestNearBodyDistance >= 0:
        pSummary["closest_near_body_distance"] =
          newJInt(ps.closestNearBodyDistance)
      pSummary["times_witnessed_kill"] = newJInt(ps.timesWitnessedKill)
      pSummary["times_witnessed_vent"] = newJInt(ps.timesWitnessedVent)
      if ps.lastVentTick > -1000000:
        pSummary["last_vent_tick"] = newJInt(ps.lastVentTick)
        pSummary["last_vent_position"] = %*[ps.lastVentX, ps.lastVentY]
        if ps.lastVentLabel.len > 0:
          pSummary["last_vent_label"] = newJString(ps.lastVentLabel)
      pSummary["times_near_vent_appearance"] =
        newJInt(ps.timesNearVentAppearance)
      pSummary["near_vent_evidence_score"] =
        newJInt(ps.nearVentEvidenceScore)
      if ps.lastNearVentTick > -1000000:
        pSummary["last_near_vent_tick"] = newJInt(ps.lastNearVentTick)
        pSummary["last_near_vent_position"] =
          %*[ps.lastNearVentX, ps.lastNearVentY]
        pSummary["last_near_vent_distance"] =
          newJInt(ps.lastNearVentDistance)
        pSummary["last_near_vent_probability_pct"] =
          newJInt(ps.lastNearVentProbabilityPct)
        if ps.lastNearVentLabel.len > 0:
          pSummary["last_near_vent_label"] =
            newJString(ps.lastNearVentLabel)
      pSummary["solo_with_self_ticks"] = newJInt(ps.soloWithSelfTicks)
      pSummary["current_solo_with_self_ticks"] =
        newJInt(ps.currentSoloWithSelfTicks)
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
    var alivePlayers = newJArray()
    var deadPlayers = newJArray()
    for i in 0 ..< max(0, belief.percep.votingPlayerCount):
      if belief.memory.perPlayer[i].alive:
        alivePlayers.add newJString(colorName(i))
      else:
        deadPlayers.add newJString(colorName(i))
    meetingObj["alive_players"] = alivePlayers
    meetingObj["dead_players"] = deadPlayers
    meetingObj["self_can_vote"] = newJBool(
      belief.self.alive and not belief.self.isGhost and
      belief.percep.votingSelfSlot >= 0)
    var votesObj = newJObject()
    for voter in 0 ..< PlayerColorCount:
      let target = belief.social.votesCast[voter]
      if target == -1:
        votesObj[colorName(voter)] = newJString("skip")
      elif target >= 0 and target < PlayerColorCount:
        votesObj[colorName(voter)] = newJString(colorName(target))
    meetingObj["votes_observed"] = votesObj

    var ledgerObj = newJObject()
    var concreteMemoryEvidencePlayers = newJArray()
    var probabilisticMemoryEvidencePlayers = newJArray()
    for i in 0 ..< max(0, belief.percep.votingPlayerCount):
      let ps = belief.memory.perPlayer[i]
      var playerObj = newJObject()
      playerObj["vote_legal"] = newJBool(
        i != belief.percep.votingSelfSlot and
        ps.alive and
        not (belief.self.role == RoleImposter and
             i in belief.self.knownImposterColors))
      playerObj["current_vote"] = newJString(voteChoiceName(
        belief.social.votesCast[i]))

      var votesReceived = newJArray()
      for voter in 0 ..< PlayerColorCount:
        if belief.social.votesCast[voter] == i:
          votesReceived.add newJString(colorName(voter))
      playerObj["votes_received_from"] = votesReceived

      var incriminating = newJArray()
      var hasConcreteMemoryEvidence = false
      var hasProbabilisticMemoryEvidence = false
      if ps.role == RoleImposter:
        var ev = newJObject()
        ev["kind"] = newJString("known_imposter_role")
        ev["note"] = newJString(
          "Usually imposter-only teammate knowledge, not public crew proof.")
        incriminating.add ev
      if ps.timesWitnessedKill > 0:
        hasConcreteMemoryEvidence = true
        var ev = newJObject()
        ev["kind"] = newJString("witnessed_kill")
        ev["count"] = newJInt(ps.timesWitnessedKill)
        incriminating.add ev
      if ps.timesWitnessedVent > 0:
        hasConcreteMemoryEvidence = true
        var ev = newJObject()
        ev["kind"] = newJString("witnessed_vent")
        ev["count"] = newJInt(ps.timesWitnessedVent)
        ev["note"] = newJString(
          "Hard evidence: only imposters can appear from vents.")
        if ps.lastVentTick > -1000000:
          ev["last_tick"] = newJInt(ps.lastVentTick)
          ev["position"] = %*[ps.lastVentX, ps.lastVentY]
          if ps.lastVentLabel.len > 0:
            ev["vent_label"] = newJString(ps.lastVentLabel)
        incriminating.add ev
      if ps.timesNearVentAppearance > 0:
        hasProbabilisticMemoryEvidence = true
        var ev = newJObject()
        ev["kind"] = newJString("near_vent_appearance")
        ev["count"] = newJInt(ps.timesNearVentAppearance)
        ev["score"] = newJInt(ps.nearVentEvidenceScore)
        ev["ambiguous"] = newJBool(true)
        ev["note"] = newJString(
          "Probabilistic evidence: player newly appeared near a vent; closer is stronger, but this is not proof.")
        if ps.lastNearVentTick > -1000000:
          ev["last_tick"] = newJInt(ps.lastNearVentTick)
          ev["position"] = %*[ps.lastNearVentX, ps.lastNearVentY]
          ev["distance"] = newJInt(ps.lastNearVentDistance)
          ev["probability_pct"] = newJInt(ps.lastNearVentProbabilityPct)
          if ps.lastNearVentLabel.len > 0:
            ev["vent_label"] = newJString(ps.lastNearVentLabel)
        incriminating.add ev
      if ps.timesNearBody > 0:
        hasConcreteMemoryEvidence = true
        var ev = newJObject()
        ev["kind"] = newJString("near_body")
        ev["count"] = newJInt(ps.timesNearBody)
        ev["score"] = newJInt(ps.nearBodyEvidenceScore)
        ev["ambiguous"] = newJBool(true)
        ev["note"] = newJString(
          "Could be killer, reporter, or bystander; closer is stronger.")
        if ps.lastNearBodyTick > -1000000:
          ev["last_tick"] = newJInt(ps.lastNearBodyTick)
        if ps.lastNearBodyDistance >= 0:
          ev["last_distance"] = newJInt(ps.lastNearBodyDistance)
        if ps.closestNearBodyDistance >= 0:
          ev["closest_distance"] = newJInt(ps.closestNearBodyDistance)
        incriminating.add ev
      playerObj["has_concrete_memory_evidence"] =
        newJBool(hasConcreteMemoryEvidence)
      playerObj["has_probabilistic_memory_evidence"] =
        newJBool(hasProbabilisticMemoryEvidence)
      if hasConcreteMemoryEvidence:
        concreteMemoryEvidencePlayers.add newJString(colorName(i))
      if hasProbabilisticMemoryEvidence:
        probabilisticMemoryEvidencePlayers.add newJString(colorName(i))
      playerObj["incriminating"] = incriminating

      var exculpatory = newJArray()
      if ps.soloWithSelfTicks > 0:
        var ev = newJObject()
        ev["kind"] = newJString("solo_survival_trust")
        ev["total_ticks"] = newJInt(ps.soloWithSelfTicks)
        ev["current_streak_ticks"] = newJInt(ps.currentSoloWithSelfTicks)
        ev["note"] = newJString(
          "Direct trust: I spent time alone with this player and survived.")
        exculpatory.add ev
      playerObj["exculpatory"] = exculpatory

      var chatMentions = newJArray()
      for cl in belief.social.recentChat:
        if cl.text.textNamesColor(i):
          var ev = newJObject()
          ev["tick"] = newJInt(cl.tick)
          ev["speaker"] = newJString(colorName(cl.speakerColor))
          ev["text"] = newJString(cl.text)
          ev["interpretation"] = newJString(
            "LLM must classify as accusation, defense, alibi, or noise.")
          chatMentions.add ev
      playerObj["chat_mentions"] = chatMentions

      ledgerObj[colorName(i)] = playerObj
    meetingObj["evidence_ledger"] = ledgerObj
    meetingObj["players_with_concrete_memory_evidence"] =
      concreteMemoryEvidencePlayers
    meetingObj["players_with_probabilistic_memory_evidence"] =
      probabilisticMemoryEvidencePlayers

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
  var newChatArr = newJArray()
  for cl in belief.social.pendingChatObserved:
    var clObj = newJObject()
    clObj["tick"] = newJInt(cl.tick)
    clObj["speaker"] = newJString(colorName(cl.speakerColor))
    clObj["text"] = newJString(cl.text)
    newChatArr.add clObj
  root["new_chat"] = newChatArr

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
