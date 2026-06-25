## Combat audit logging for damage, kills, healing, and siege events.

when defined(combatAudit):
  import
    std/[algorithm, strutils, tables],
    envconfig

  const
    ReportDivider = "═══════════════════════════════════════════════════════"
    TeamSlotCount = 9

  type
    CombatEventKind* = enum
      ceDamage             ## Damage dealt to an agent.
      ceKill               ## Agent killed.
      ceHeal               ## Agent healed.
      ceConversion         ## Monk conversion.
      ceSiegeDamage        ## Siege or structure damage.
      ceBuildingDestroyed  ## Building destroyed.

    CombatEvent* = object
      step*: int
      kind*: CombatEventKind
      attackerTeam*: int
      targetTeam*: int
      attackerUnit*: string
      targetUnit*: string
      attackerId*: int
      targetId*: int
      amount*: int
      damageType*: string

    TeamCombatStats* = object
      totalDamageDealt*: int
      totalDamageTaken*: int
      kills*: int
      deaths*: int
      healsGiven*: int
      healAmount*: int
      conversions*: int
      buildingsDestroyed*: int
      siegeDamageDealt*: int
      damageByType*: Table[string, int]
      killsByUnit*: Table[string, int]

    CombatAuditState* = object
      events*: seq[CombatEvent]
      teamStats*: array[TeamSlotCount, TeamCombatStats]
      reportInterval*: int
      verbose*: bool
      lastReportStep*: int

  var
    auditState*: CombatAuditState
    auditInitialized = false

  proc initCombatAudit*() =
    ## Initialize combat audit state from environment settings.
    auditState = CombatAuditState(
      events: @[],
      reportInterval: max(1, parseEnvInt("TV_COMBAT_REPORT_INTERVAL", 100)),
      verbose: parseEnvBool("TV_COMBAT_VERBOSE", false),
      lastReportStep: 0
    )
    for teamId in 0 ..< auditState.teamStats.len:
      auditState.teamStats[teamId].damageByType = initStringIntTable()
      auditState.teamStats[teamId].killsByUnit = initStringIntTable(32)
    auditInitialized = true

  proc ensureCombatAuditInit*() =
    ## Initialize combat audit state on first use.
    if not auditInitialized:
      initCombatAudit()

  proc isTrackedTeam(teamId: int): bool =
    ## Returns true when the team ID has combat audit stats.
    teamId >= 0 and teamId < auditState.teamStats.len

  proc clearDetailedEvents() =
    ## Drops verbose combat events after printing one report.
    auditState.events.setLen(0)

  proc recordDamage*(
    step,
    attackerTeam,
    targetTeam,
    attackerId,
    targetId,
    amount: int,
    attackerUnit,
    targetUnit,
    damageType: string
  ) =
    ## Record one combat damage event.
    let event = CombatEvent(
      step: step,
      kind: ceDamage,
      attackerTeam: attackerTeam,
      targetTeam: targetTeam,
      attackerUnit: attackerUnit,
      targetUnit: targetUnit,
      attackerId: attackerId,
      targetId: targetId,
      amount: amount,
      damageType: damageType
    )
    if auditState.verbose:
      auditState.events.add(event)
    if isTrackedTeam(attackerTeam):
      auditState.teamStats[attackerTeam].totalDamageDealt += amount
      let currentAmount =
        auditState.teamStats[attackerTeam].damageByType.getOrDefault(
          damageType,
          0
        )
      auditState.teamStats[attackerTeam].damageByType[damageType] =
        currentAmount + amount
    if isTrackedTeam(targetTeam):
      auditState.teamStats[targetTeam].totalDamageTaken += amount

  proc recordKill*(
    step,
    killerTeam,
    victimTeam,
    killerId,
    victimId: int,
    killerUnit,
    victimUnit: string
  ) =
    ## Record one kill event.
    let event = CombatEvent(
      step: step,
      kind: ceKill,
      attackerTeam: killerTeam,
      targetTeam: victimTeam,
      attackerUnit: killerUnit,
      targetUnit: victimUnit,
      attackerId: killerId,
      targetId: victimId
    )
    if auditState.verbose:
      auditState.events.add(event)
    if isTrackedTeam(killerTeam):
      auditState.teamStats[killerTeam].kills += 1
      let currentCount =
        auditState.teamStats[killerTeam].killsByUnit.getOrDefault(
          killerUnit,
          0
        )
      auditState.teamStats[killerTeam].killsByUnit[killerUnit] =
        currentCount + 1
    if isTrackedTeam(victimTeam):
      auditState.teamStats[victimTeam].deaths += 1

  proc recordHeal*(
    step,
    healerTeam,
    targetTeam,
    healerId,
    targetId,
    amount: int,
    healerUnit,
    targetUnit: string
  ) =
    ## Record one healing event.
    let event = CombatEvent(
      step: step,
      kind: ceHeal,
      attackerTeam: healerTeam,
      targetTeam: targetTeam,
      attackerUnit: healerUnit,
      targetUnit: targetUnit,
      attackerId: healerId,
      targetId: targetId,
      amount: amount
    )
    if auditState.verbose:
      auditState.events.add(event)
    if isTrackedTeam(healerTeam):
      auditState.teamStats[healerTeam].healsGiven += 1
      auditState.teamStats[healerTeam].healAmount += amount

  proc recordConversion*(
    step,
    monkTeam,
    targetTeam,
    monkId,
    targetId: int,
    targetUnit: string
  ) =
    ## Record one monk conversion event.
    let event = CombatEvent(
      step: step,
      kind: ceConversion,
      attackerTeam: monkTeam,
      targetTeam: targetTeam,
      attackerUnit: "Monk",
      targetUnit: targetUnit,
      attackerId: monkId,
      targetId: targetId
    )
    if auditState.verbose:
      auditState.events.add(event)
    if isTrackedTeam(monkTeam):
      auditState.teamStats[monkTeam].conversions += 1

  proc recordSiegeDamage*(
    step,
    attackerTeam: int,
    buildingKind: string,
    targetTeam,
    amount: int,
    attackerUnit: string,
    destroyed: bool
  ) =
    ## Record one siege damage or building destruction event.
    if auditState.verbose:
      auditState.events.add(CombatEvent(
        step: step,
        kind:
          if destroyed:
            ceBuildingDestroyed
          else:
            ceSiegeDamage,
        attackerTeam: attackerTeam,
        targetTeam: targetTeam,
        attackerUnit: attackerUnit,
        targetUnit: buildingKind,
        amount: amount,
        damageType: "siege"
      ))
    if isTrackedTeam(attackerTeam):
      auditState.teamStats[attackerTeam].siegeDamageDealt += amount
      if destroyed:
        auditState.teamStats[attackerTeam].buildingsDestroyed += 1

  proc formatRatio(a, b: int): string =
    ## Format one ratio with two decimal places.
    if b == 0:
      if a == 0:
        return "0.00"
      return $a & ".00"
    formatFloat(a.float / b.float, ffDecimal, 2)

  proc printCombatReport*(currentStep: int) =
    ## Print the combat report when the reporting interval elapses.
    if currentStep - auditState.lastReportStep < auditState.reportInterval:
      return
    auditState.lastReportStep = currentStep

    echo ReportDivider
    echo "  COMBAT REPORT — Step ", currentStep
    echo ReportDivider

    for teamId in 0 ..< TeamSlotCount:
      let teamStats = auditState.teamStats[teamId]
      if teamStats.totalDamageDealt == 0 and
        teamStats.totalDamageTaken == 0 and
        teamStats.kills == 0 and
        teamStats.deaths == 0:
          continue

      let teamLabel =
        if teamId < 8:
          "Team " & $teamId
        else:
          "Goblins"
      echo "  ", teamLabel, ":"
      echo(
        "    Damage: dealt=",
        teamStats.totalDamageDealt,
        " taken=",
        teamStats.totalDamageTaken
      )
      echo(
        "    Kills=",
        teamStats.kills,
        " Deaths=",
        teamStats.deaths,
        " K/D=",
        formatRatio(teamStats.kills, teamStats.deaths)
      )
      if teamStats.healsGiven > 0:
        echo(
          "    Heals: count=",
          teamStats.healsGiven,
          " amount=",
          teamStats.healAmount
        )
      if teamStats.conversions > 0:
        echo "    Conversions: ", teamStats.conversions
      if teamStats.siegeDamageDealt > 0:
        echo(
          "    Siege damage: ",
          teamStats.siegeDamageDealt,
          " buildings destroyed=",
          teamStats.buildingsDestroyed
        )

      if teamStats.damageByType.len > 0:
        var damageParts: seq[string] = @[]
        for damageType, amount in teamStats.damageByType:
          damageParts.add(damageType & "=" & $amount)
        damageParts.sort()
        echo "    Damage by type: ", damageParts.join(", ")

      if teamStats.killsByUnit.len > 0:
        var killPairs: seq[(string, int)] = @[]
        for unitName, killCount in teamStats.killsByUnit:
          killPairs.add((unitName, killCount))
        killPairs.sort(proc(a, b: (string, int)): int = cmp(b[1], a[1]))
        var killParts: seq[string] = @[]
        for (unitName, killCount) in killPairs:
          killParts.add(unitName & "=" & $killCount)
        echo "    Kills by unit: ", killParts.join(", ")

    echo ReportDivider

    if auditState.verbose and auditState.events.len > 0:
      echo "  DETAILED EVENTS (last interval):"
      for event in auditState.events:
        case event.kind
        of ceDamage:
          echo(
            "    [",
            event.step,
            "] T",
            event.attackerTeam,
            " ",
            event.attackerUnit,
            "(",
            event.attackerId,
            ") -> T",
            event.targetTeam,
            " ",
            event.targetUnit,
            "(",
            event.targetId,
            ") dmg=",
            event.amount,
            " (",
            event.damageType,
            ")"
          )
        of ceKill:
          echo(
            "    [",
            event.step,
            "] KILL T",
            event.attackerTeam,
            " ",
            event.attackerUnit,
            "(",
            event.attackerId,
            ") killed T",
            event.targetTeam,
            " ",
            event.targetUnit,
            "(",
            event.targetId,
            ")"
          )
        of ceHeal:
          echo(
            "    [",
            event.step,
            "] HEAL T",
            event.attackerTeam,
            " ",
            event.attackerUnit,
            "(",
            event.attackerId,
            ") -> T",
            event.targetTeam,
            " ",
            event.targetUnit,
            "(",
            event.targetId,
            ") hp=+",
            event.amount
          )
        of ceConversion:
          echo(
            "    [",
            event.step,
            "] CONVERT T",
            event.attackerTeam,
            " Monk(",
            event.attackerId,
            ") converted T",
            event.targetTeam,
            " ",
            event.targetUnit,
            "(",
            event.targetId,
            ")"
          )
        of ceSiegeDamage:
          echo(
            "    [",
            event.step,
            "] SIEGE T",
            event.attackerTeam,
            " ",
            event.attackerUnit,
            "(",
            event.attackerId,
            ") -> ",
            event.targetUnit,
            " dmg=",
            event.amount
          )
        of ceBuildingDestroyed:
          echo(
            "    [",
            event.step,
            "] DESTROYED T",
            event.attackerTeam,
            " ",
            event.attackerUnit,
            "(",
            event.attackerId,
            ") destroyed ",
            event.targetUnit
          )
      echo ReportDivider
      clearDetailedEvents()
