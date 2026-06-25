## Replay analysis helpers for scoring team strategies and replay batches.

import
  std/[algorithm, json, os, strutils, times],
  zippy,
  replay_common, scripted/roles

export roles

const
  ReplayAnalysisVersion* = 1
  MaxReplaysPerPass* = 8
  WinRewardThreshold* = 0.5
  ReplayFeedbackAlpha* = 0.1
  ReplayFileSuffix = ".json.z"

type
  ActionDistribution* = object
    ## Per-action-verb frequency counts for one team.
    counts*: array[ActionVerbCount, int]
    total*: int

  CombatStats* = object
    ## Aggregate combat activity for one team.
    attacks*: int
    hits*: int
    kills*: int  ## Inferred from agents going inactive.

  ResourceStats* = object
    ## Aggregate resource activity for one team.
    gatherActions*: int
    buildActions*: int
    totalInventoryGain*: int

  TeamStrategy* = object
    ## Summary of one team's behavior across one replay.
    teamId*: int
    agentCount*: int
    actionDist*: ActionDistribution
    combat*: CombatStats
    resources*: ResourceStats
    finalReward*: float32
    won*: bool

  ReplayAnalysis* = object
    ## Analysis results for one replay file.
    filePath*: string
    maxSteps*: int
    numAgents*: int
    teams*: seq[TeamStrategy]
    winningTeamId*: int

  ActionSequence* = object
    ## Extracted action pattern from one high-performing agent.
    verbs*: seq[int]
    teamReward*: float32

proc isTrackedTeam(teamId: int): bool {.inline.} =
  ## Returns true when the team ID is inside the tracked team range.
  teamId >= 0 and teamId < MapRoomObjectsTeams

proc isActionVerb(verb: int): bool {.inline.} =
  ## Returns true when the verb ID is inside the action verb range.
  verb >= 0 and verb < ActionVerbCount

proc averageReward(strategy: TeamStrategy): float32 =
  ## Returns the average reward per agent for one team strategy.
  if strategy.agentCount <= 0:
    return 0.0
  strategy.finalReward / float32(strategy.agentCount)

proc loadReplayJson*(path: string): JsonNode =
  ## Load one compressed replay file and parse the JSON payload.
  let
    compressed = readFile(path)
    decompressed = zippy.uncompress(compressed, dataFormat = dfZlib)
  parseJson(decompressed)

proc analyzeReplay*(replayJson: JsonNode): ReplayAnalysis =
  ## Extract per-team strategy summaries from parsed replay JSON.
  result.maxSteps = replayJson{"max_steps"}.getInt()
  result.numAgents = replayJson{"num_agents"}.getInt()
  result.winningTeamId = -1

  var teamStrategies: array[MapRoomObjectsTeams, TeamStrategy]
  for teamId in 0 ..< MapRoomObjectsTeams:
    teamStrategies[teamId].teamId = teamId

  let objects = replayJson{"objects"}
  if objects.isNil or objects.kind != JArray:
    return

  for obj in objects.items:
    if obj.kind != JObject:
      continue

    let agentIdNode = obj{"agent_id"}
    if agentIdNode.isNil:
      continue

    let groupIdNode = obj{"group_id"}
    if groupIdNode.isNil:
      continue

    let teamId = groupIdNode.getInt()
    if not isTrackedTeam(teamId):
      continue

    inc teamStrategies[teamId].agentCount

    let
      actionIdSeries = obj{"action_id"}
      actionSuccessSeries = obj{"action_success"}
    if not actionIdSeries.isNil:
      let
        actionChanges = parseChanges(actionIdSeries)
        successChanges =
          if not actionSuccessSeries.isNil:
            parseChanges(actionSuccessSeries)
          else:
            @[]
      var successIdx = 0

      for actionChange in actionChanges:
        let verb = actionChange.value.getInt()
        if not isActionVerb(verb):
          continue

        inc teamStrategies[teamId].actionDist.counts[verb]
        inc teamStrategies[teamId].actionDist.total

        if verb == ActionAttack:
          inc teamStrategies[teamId].combat.attacks
          while successIdx < successChanges.len and
            successChanges[successIdx].step < actionChange.step:
              inc successIdx
          if successIdx < successChanges.len and
            successChanges[successIdx].step == actionChange.step and
            successChanges[successIdx].value.getBool():
              inc teamStrategies[teamId].combat.hits
        elif verb == ActionUse:
          inc teamStrategies[teamId].resources.gatherActions
        elif verb == ActionBuild:
          inc teamStrategies[teamId].resources.buildActions

    let totalRewardSeries = obj{"total_reward"}
    if not totalRewardSeries.isNil:
      let lastReward = lastChangeValue(totalRewardSeries)
      if lastReward.kind == JFloat or lastReward.kind == JInt:
        teamStrategies[teamId].finalReward += lastReward.getFloat().float32

  var
    bestReward = float32.low
    bestTeam = -1
  for teamId in 0 ..< MapRoomObjectsTeams:
    if teamStrategies[teamId].agentCount > 0:
      let avgReward = averageReward(teamStrategies[teamId])
      teamStrategies[teamId].won = avgReward >= WinRewardThreshold
      if avgReward > bestReward:
        bestReward = avgReward
        bestTeam = teamId

  result.winningTeamId = bestTeam
  for teamId in 0 ..< MapRoomObjectsTeams:
    if teamStrategies[teamId].agentCount > 0:
      result.teams.add(teamStrategies[teamId])

proc analyzeReplayFile*(path: string): ReplayAnalysis =
  ## Load and analyze one replay file.
  let replayJson = loadReplayJson(path)
  result = analyzeReplay(replayJson)
  result.filePath = path

proc actionProfile*(strategy: TeamStrategy): array[ActionVerbCount, float32] =
  ## Normalize action counts to a frequency distribution.
  if strategy.actionDist.total <= 0:
    return
  for verb in 0 ..< ActionVerbCount:
    result[verb] =
      float32(strategy.actionDist.counts[verb]) /
      float32(strategy.actionDist.total)

proc combatEfficiency*(strategy: TeamStrategy): float32 =
  ## Return the hit rate for attack actions.
  if strategy.combat.attacks <= 0:
    return 0.0
  float32(strategy.combat.hits) / float32(strategy.combat.attacks)

proc economyScore*(strategy: TeamStrategy): float32 =
  ## Return the gather-to-total ratio for economy actions.
  let total = strategy.resources.gatherActions + strategy.resources.buildActions
  if total <= 0:
    return 0.0
  float32(strategy.resources.gatherActions) / float32(total)

proc strategyScore*(strategy: TeamStrategy): float32 =
  ## Return the composite strategy score clamped to `[0.0, 1.0]`.
  let rewardComponent =
    clamp(
      averageReward(strategy),
      0.0,
      1.0
    )
  let
    combatComponent = combatEfficiency(strategy) * 0.2
    winBonus =
      if strategy.won:
        0.15'f
      else:
        0.0
  clamp(rewardComponent * 0.65 + combatComponent + winBonus, 0.0, 1.0)

proc teamScore(analysis: ReplayAnalysis, teamId: int): float32 =
  ## Returns the composite score for one team inside one replay analysis.
  for team in analysis.teams:
    if team.teamId == teamId:
      return strategyScore(team)
  0.0

template blendFitness(
  fitness: var float32,
  target: float32,
  alpha: float32
) =
  ## Blend fitness toward a target using an exponential moving average.
  fitness = clamp(fitness * (1.0 - alpha) + target * alpha, 0.0, 1.0)

proc applyReplayFeedback*(catalog: var RoleCatalog, analysis: ReplayAnalysis) =
  ## Blend replay feedback into role and behavior fitness values.
  if analysis.teams.len == 0:
    return

  var scores = newSeqOfCap[float32](analysis.teams.len)
  for team in analysis.teams:
    scores.add(strategyScore(team))

  var avgScore: float32 = 0.0
  for score in scores:
    avgScore += score
  avgScore /= float32(scores.len)

  for role in catalog.roles.mitems:
    if role.games > 0:
      blendFitness(role.fitness, avgScore, ReplayFeedbackAlpha)

  for behavior in catalog.behaviors.mitems:
    if behavior.games > 0:
      blendFitness(behavior.fitness, avgScore, ReplayFeedbackAlpha)

proc applyWinnerBoost*(
  catalog: var RoleCatalog,
  analysis: ReplayAnalysis,
  boostAlpha: float32 = 0.15
) =
  ## Boost strong roles toward the winning team strategy score.
  if analysis.winningTeamId < 0:
    return

  let winnerScore = teamScore(analysis, analysis.winningTeamId)
  if winnerScore <= 0.0:
    return

  for role in catalog.roles.mitems:
    if role.fitness >= 0.5 and role.games > 0:
      blendFitness(role.fitness, winnerScore, boostAlpha)

proc dominantActionVerb*(seqData: ActionSequence): int =
  ## Return the most frequent action verb in one sequence.
  var counts: array[ActionVerbCount, int]
  for verb in seqData.verbs:
    if isActionVerb(verb):
      inc counts[verb]

  var bestCount = 0
  result = 0
  for verb in 0 ..< ActionVerbCount:
    if counts[verb] > bestCount:
      bestCount = counts[verb]
      result = verb

proc findReplayFiles*(dir: string): seq[string] =
  ## Return replay files in descending modification-time order.
  if not dirExists(dir):
    return @[]
  for entry in walkDir(dir):
    if entry.kind == pcFile and entry.path.endsWith(ReplayFileSuffix):
      result.add(entry.path)
  result.sort(proc(a, b: string): int =
    let
      aTime = getLastModificationTime(a)
      bTime = getLastModificationTime(b)
    cmp(bTime, aTime)
  )

proc analyzeReplayBatch*(
  dir: string,
  maxFiles: int = MaxReplaysPerPass
): seq[ReplayAnalysis] =
  ## Analyze up to `maxFiles` replay files from one directory.
  let
    files = findReplayFiles(dir)
    count = min(files.len, maxFiles)
  result = newSeqOfCap[ReplayAnalysis](count)
  for i in 0 ..< count:
    try:
      result.add(analyzeReplayFile(files[i]))
    except CatchableError as err:
      echo "Warning: Failed to analyze ", files[i], ": ", err.msg

proc applyBatchFeedback*(
  catalog: var RoleCatalog,
  analyses: seq[ReplayAnalysis]
) =
  ## Apply replay feedback for every analysis in one batch.
  for analysis in analyses:
    applyReplayFeedback(catalog, analysis)
    applyWinnerBoost(catalog, analysis)
