## Scripted AI audit logging and periodic summaries.

import ai_types
export ai_types

when defined(aiAudit):
  import
    std/[strformat, strutils],
    ../envconfig

  const
    AgentRoleCount = ord(high(AgentRole)) + 1
    AuditActionNames*: array[ActionVerbCount, string] = [
      "noop", "move", "attack", "use", "swap", "put",
      "plant_lantern", "plant_resource", "build", "orient", "set_rally_point"
    ]
    AuditRoleNames*: array[AgentRoleCount, string] = [
      "Gatherer", "Builder", "Fighter", "Scripted"
    ]
    AuditSummaryInterval* = 50

  type
    AuditDecisionBranch* = enum
      BranchInactive
      BranchDecisionDelay
      BranchStopped
      BranchGoblinRelic
      BranchGoblinAvoid
      BranchGoblinSearch
      BranchEscape
      BranchAttackOpportunity
      BranchPatrolChase
      BranchPatrolMove
      BranchRallyPoint
      BranchAttackMoveEngage
      BranchAttackMoveAdvance
      BranchSettlerMigrate
      BranchHearts
      BranchPopCapWood
      BranchPopCapBuild
      BranchRoleCatalog

    AuditRecord* = object
      agentId*: int
      teamId*: int
      role*: AgentRole
      verb*: int
      arg*: int
      branch*: AuditDecisionBranch

    AuditSummaryState* = object
      logLevel*: int
      stepDecisions*: seq[AuditRecord]
      verbCounts*: array[ActionVerbCount, int]
      roleCounts*: array[MapRoomObjectsTeams, array[AgentRoleCount, int]]
      branchCounts*: array[AuditDecisionBranch, int]
      stepsAccumulated*: int
      totalDecisions*: int

  var
    auditSummary*: AuditSummaryState
    auditCurrentBranch*: AuditDecisionBranch

  proc actionName(verb: int): string =
    ## Returns the display name for one action verb ID.
    if verb >= 0 and verb < ActionVerbCount:
      return AuditActionNames[verb]
    $verb

  proc roleName(role: AgentRole): string =
    ## Returns the display name for one scripted role.
    let roleId = ord(role)
    if roleId >= 0 and roleId < AuditRoleNames.len:
      return AuditRoleNames[roleId]
    $role

  proc resetStepDecisions() =
    ## Clears verbose per-step decision records.
    auditSummary.stepDecisions.setLen(0)

  proc resetSummaryCounts() =
    ## Clears summary counters after one reporting interval.
    for i in 0 ..< ActionVerbCount:
      auditSummary.verbCounts[i] = 0
    for teamId in 0 ..< MapRoomObjectsTeams:
      for roleId in 0 ..< AgentRoleCount:
        auditSummary.roleCounts[teamId][roleId] = 0
    for branch in AuditDecisionBranch:
      auditSummary.branchCounts[branch] = 0
    auditSummary.totalDecisions = 0

  proc initAuditLog*() =
    ## Initialize audit logging from environment configuration.
    auditSummary.logLevel = parseEnvInt("TV_AI_LOG", 0)
    auditSummary.stepDecisions = @[]
    auditSummary.stepsAccumulated = 0
    auditSummary.totalDecisions = 0
    auditCurrentBranch = BranchInactive

  proc setAuditBranch*(branch: AuditDecisionBranch) {.inline.} =
    ## Record the current decision branch for the next audit event.
    auditCurrentBranch = branch

  proc recordAuditDecision*(agentId: int, teamId: int, role: AgentRole,
                            action: uint16) =
    ## Record one agent decision in the audit summary.
    if auditSummary.logLevel <= 0:
      return
    let verb = action.int div ActionArgumentCount
    let arg = action.int mod ActionArgumentCount
    let branch = auditCurrentBranch

    if verb >= 0 and verb < ActionVerbCount:
      inc auditSummary.verbCounts[verb]
    if teamId >= 0 and teamId < MapRoomObjectsTeams:
      inc auditSummary.roleCounts[teamId][ord(role)]
    inc auditSummary.branchCounts[branch]
    inc auditSummary.totalDecisions

    if auditSummary.logLevel >= 2:
      auditSummary.stepDecisions.add(AuditRecord(
        agentId: agentId,
        teamId: teamId,
        role: role,
        verb: verb,
        arg: arg,
        branch: branch
      ))

  proc printVerboseDecisions*(step: int) =
    ## Print the current step's verbose audit records.
    if auditSummary.logLevel < 2 or auditSummary.stepDecisions.len == 0:
      return
    echo &"[AI_AUDIT step={step}] {auditSummary.stepDecisions.len} decisions:"
    for d in auditSummary.stepDecisions:
      echo(
        &"  agent={d.agentId} team={d.teamId} role={roleName(d.role)} " &
        &"action={actionName(d.verb)}:{d.arg} branch={d.branch}"
      )
    resetStepDecisions()

  proc printAuditSummary*(step: int) =
    ## Print verbose or summary audit output for the current step.
    if auditSummary.logLevel <= 0:
      return
    inc auditSummary.stepsAccumulated

    if auditSummary.logLevel >= 2:
      printVerboseDecisions(step)

    if auditSummary.stepsAccumulated mod AuditSummaryInterval != 0:
      return

    let total = auditSummary.totalDecisions
    if total == 0:
      return

    echo(
      &"\n[AI_AUDIT SUMMARY steps={step - AuditSummaryInterval + 1}.." &
      &"{step}] total_decisions={total}"
    )

    echo "  Action distribution:"
    for i in 0 ..< ActionVerbCount:
      let count = auditSummary.verbCounts[i]
      if count > 0:
        let pct = (count.float * 100.0) / total.float
        echo &"    {AuditActionNames[i]}: {count} ({pct:.1f}%)"

    echo "  Role distribution per team:"
    for teamId in 0 ..< MapRoomObjectsTeams:
      var teamTotal = 0
      for roleId in 0 ..< AgentRoleCount:
        teamTotal += auditSummary.roleCounts[teamId][roleId]
      if teamTotal > 0:
        var parts: seq[string] = @[]
        for roleId in 0 ..< AgentRoleCount:
          let c = auditSummary.roleCounts[teamId][roleId]
          if c > 0:
            let pct = (c.float * 100.0) / teamTotal.float
            parts.add(&"{AuditRoleNames[roleId]}={c}({pct:.0f}%)")
        echo &"    team {teamId}: {parts.join(\", \")}"

    echo "  Decision branches:"
    for branch in AuditDecisionBranch:
      let count = auditSummary.branchCounts[branch]
      if count > 0:
        let pct = (count.float * 100.0) / total.float
        echo &"    {branch}: {count} ({pct:.1f}%)"

    resetSummaryCounts()

else:
  template setAuditBranch*(branch: untyped) = discard
  template initAuditLog*() = discard
  template recordAuditDecision*(
    agentId,
    teamId: int,
    role: untyped,
    action: uint16
  ) = discard
  template printAuditSummary*(step: int) = discard
