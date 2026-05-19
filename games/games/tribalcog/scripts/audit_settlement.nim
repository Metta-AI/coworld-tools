## Settlement audit script: profiles settler distribution, altar usage,
## and town expansion metrics over a long simulation run.
##
## Usage:
##   nim r -d:release --path:src scripts/audit_settlement.nim
##   TV_AUDIT_STEPS=3000 TV_AUDIT_SEED=42 nim r -d:release --path:src scripts/audit_settlement.nim
##   nim r -d:release --path:src scripts/audit_settlement.nim -- --json
##
## Environment variables:
##   TV_AUDIT_STEPS    - Number of simulation steps (default: 2000)
##   TV_AUDIT_SEED     - Random seed for reproducibility (default: 42)
##   TV_AUDIT_INTERVAL - Snapshot interval in steps (default: 100)

import std/[os, strutils, strformat, tables, json, math]
import environment
import agent_control
import types
import envconfig

# ---------------------------------------------------------------------------
# Metric types
# ---------------------------------------------------------------------------

type
  AltarSnapshot = object
    pos: IVec2
    teamId: int
    hearts: int
    villagerCount: int  # villagers with this as homeAltar

  TeamSnapshot = object
    teamId: int
    townCenterCount: int
    altarCount: int
    totalVillagers: int
    aliveVillagers: int
    altars: seq[AltarSnapshot]
    activeAgents: int  # non-terminated agents for this team

  StepSnapshot = object
    step: int
    teams: seq[TeamSnapshot]

  SplitEvent = object
    step: int
    teamId: int
    description: string

  AuditReport = object
    seed: int
    totalSteps: int
    snapshotInterval: int
    snapshots: seq[StepSnapshot]
    events: seq[SplitEvent]

# ---------------------------------------------------------------------------
# Snapshot collection
# ---------------------------------------------------------------------------

proc collectSnapshot(env: Environment, step: int): StepSnapshot =
  result.step = step

  for teamId in 0 ..< MapRoomObjectsTeams:
    var ts = TeamSnapshot(teamId: teamId)

    # Count town centers
    for tc in env.thingsByKind[TownCenter]:
      if tc.teamId == teamId:
        inc ts.townCenterCount

    # Gather altar info and count villagers per altar
    var altarVillagers = initTable[IVec2, int]()
    for altar in env.thingsByKind[Altar]:
      if altar.teamId == teamId:
        inc ts.altarCount
        altarVillagers[altar.pos] = 0
        ts.altars.add AltarSnapshot(
          pos: altar.pos,
          teamId: teamId,
          hearts: altar.hearts,
          villagerCount: 0
        )

    # Count villagers per homeAltar and alive status
    let startIdx = teamId * MapAgentsPerTeam
    let endIdx = min(startIdx + MapAgentsPerTeam, env.agents.len)
    for i in startIdx ..< endIdx:
      let agent = env.agents[i]
      if isNil(agent) or agent.kind != Agent:
        continue
      if agent.unitClass == UnitVillager:
        inc ts.totalVillagers
        if env.terminated[i] == 0.0:
          inc ts.aliveVillagers
        if agent.homeAltar.x >= 0 and agent.homeAltar in altarVillagers:
          altarVillagers[agent.homeAltar] += 1
      if env.terminated[i] == 0.0:
        inc ts.activeAgents

    # Write villager counts back into altar snapshots
    for idx in 0 ..< ts.altars.len:
      if ts.altars[idx].pos in altarVillagers:
        ts.altars[idx].villagerCount = altarVillagers[ts.altars[idx].pos]

    result.teams.add ts

# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

proc printTextReport(report: AuditReport) =
  echo "=" .repeat(72)
  echo "SETTLEMENT AUDIT REPORT"
  echo "=" .repeat(72)
  echo fmt"Seed: {report.seed}"
  echo fmt"Steps: {report.totalSteps}  |  Snapshot interval: {report.snapshotInterval}"
  echo ""

  # Timeline table
  echo "-" .repeat(72)
  echo "  Step  Team   TCs  Altars  Villagers  Alive  MaxClust  MinClust"
  echo "-" .repeat(72)
  for snap in report.snapshots:
    for ts in snap.teams:
      if ts.altarCount > 0 or ts.townCenterCount > 0:
        var maxCluster = 0
        var minCluster = high(int)
        for a in ts.altars:
          if a.villagerCount > maxCluster:
            maxCluster = a.villagerCount
          if a.villagerCount < minCluster:
            minCluster = a.villagerCount
        if ts.altars.len == 0:
          minCluster = 0
        echo fmt"{snap.step:>6}  {ts.teamId:>4}  {ts.townCenterCount:>4}  {ts.altarCount:>6}  {ts.totalVillagers:>9}  {ts.aliveVillagers:>6}  {maxCluster:>8}  {minCluster:>8}"

  # Final state detail
  let final = report.snapshots[^1]
  echo ""
  echo "-" .repeat(72)
  echo "FINAL STATE"
  echo "-" .repeat(72)
  for ts in final.teams:
    if ts.altarCount > 0:
      echo fmt"  Team {ts.teamId}: {ts.altarCount} altar(s), {ts.townCenterCount} TC(s), {ts.totalVillagers} villagers ({ts.aliveVillagers} alive)"
      for a in ts.altars:
        echo fmt"    Altar ({a.pos.x},{a.pos.y}): {a.hearts} hearts, {a.villagerCount} villagers"

  # Inter-altar distances (per team)
  echo ""
  echo "-" .repeat(72)
  echo "ALTAR DISTANCES"
  echo "-" .repeat(72)
  for ts in final.teams:
    if ts.altars.len >= 2:
      echo fmt"  Team {ts.teamId}:"
      for i in 0 ..< ts.altars.len:
        for j in i+1 ..< ts.altars.len:
          let dx = abs(ts.altars[i].pos.x - ts.altars[j].pos.x).float
          let dy = abs(ts.altars[i].pos.y - ts.altars[j].pos.y).float
          let dist = sqrt(dx*dx + dy*dy)
          echo fmt"    ({ts.altars[i].pos.x},{ts.altars[i].pos.y}) <-> ({ts.altars[j].pos.x},{ts.altars[j].pos.y}): {dist:.1f}"

  # Cluster distribution analysis
  echo ""
  echo "-" .repeat(72)
  echo "CLUSTER DISTRIBUTION (final step)"
  echo "-" .repeat(72)
  for ts in final.teams:
    if ts.altars.len > 0 and ts.totalVillagers > 0:
      var maxPct = 0.0
      for a in ts.altars:
        let pct = a.villagerCount.float / max(1, ts.totalVillagers).float * 100.0
        if pct > maxPct:
          maxPct = pct
      echo fmt"  Team {ts.teamId}: largest cluster = {maxPct:.1f}% of villagers"

  # Event timeline
  if report.events.len > 0:
    echo ""
    echo "-" .repeat(72)
    echo "SPLIT EVENTS"
    echo "-" .repeat(72)
    for ev in report.events:
      echo fmt"  Step {ev.step}: Team {ev.teamId} - {ev.description}"

  echo ""
  echo "=" .repeat(72)

# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

proc toJson(report: AuditReport): JsonNode =
  result = %*{
    "seed": report.seed,
    "totalSteps": report.totalSteps,
    "snapshotInterval": report.snapshotInterval,
    "snapshots": [],
    "events": [],
    "finalState": {}
  }

  for snap in report.snapshots:
    var snapNode = %*{"step": snap.step, "teams": []}
    for ts in snap.teams:
      if ts.altarCount > 0 or ts.townCenterCount > 0:
        var altarsNode = newJArray()
        for a in ts.altars:
          altarsNode.add %*{
            "pos": [a.pos.x.int, a.pos.y.int],
            "hearts": a.hearts,
            "villagerCount": a.villagerCount
          }
        var maxCluster = 0
        var minCluster = if ts.altars.len > 0: high(int) else: 0
        for a in ts.altars:
          if a.villagerCount > maxCluster: maxCluster = a.villagerCount
          if a.villagerCount < minCluster: minCluster = a.villagerCount
        snapNode["teams"].add %*{
          "teamId": ts.teamId,
          "townCenterCount": ts.townCenterCount,
          "altarCount": ts.altarCount,
          "totalVillagers": ts.totalVillagers,
          "aliveVillagers": ts.aliveVillagers,
          "activeAgents": ts.activeAgents,
          "maxCluster": maxCluster,
          "minCluster": minCluster,
          "altars": altarsNode
        }
    result["snapshots"].add snapNode

  for ev in report.events:
    result["events"].add %*{
      "step": ev.step,
      "teamId": ev.teamId,
      "description": ev.description
    }

  # Final state summary
  let final = report.snapshots[^1]
  var finalNode = newJObject()
  for ts in final.teams:
    if ts.altarCount > 0:
      finalNode[$ts.teamId] = %*{
        "altarCount": ts.altarCount,
        "townCenterCount": ts.townCenterCount,
        "totalVillagers": ts.totalVillagers,
        "aliveVillagers": ts.aliveVillagers
      }
  result["finalState"] = finalNode

# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

type AssertionResult = object
  name: string
  passed: bool
  detail: string

proc runAssertions(report: AuditReport): seq[AssertionResult] =
  let final = report.snapshots[^1]

  # Assertion 1: At least one team should have 2+ town centers by end
  block:
    var anyMultiTC = false
    var maxTCs = 0
    for ts in final.teams:
      if ts.townCenterCount > maxTCs:
        maxTCs = ts.townCenterCount
      if ts.townCenterCount >= 2:
        anyMultiTC = true
        break
    result.add AssertionResult(
      name: "multi_town_center",
      passed: anyMultiTC,
      detail: if anyMultiTC: "At least one team has 2+ town centers"
              else: fmt"No team has 2+ TCs (max: {maxTCs})"
    )

  # Assertion 2: Villager clusters should be distributed (no single cluster >80%)
  block:
    var worstPct = 0.0
    var worstTeam = -1
    for ts in final.teams:
      if ts.altars.len >= 2 and ts.totalVillagers > 0:
        for a in ts.altars:
          let pct = a.villagerCount.float / ts.totalVillagers.float * 100.0
          if pct > worstPct:
            worstPct = pct
            worstTeam = ts.teamId
    let distributed = worstTeam < 0 or worstPct <= 80.0
    result.add AssertionResult(
      name: "cluster_distribution",
      passed: distributed,
      detail: if worstTeam < 0: "No team has multiple altars yet (distribution N/A)"
              elif distributed: fmt"Largest cluster: {worstPct:.1f}% (team {worstTeam}) <= 80%"
              else: fmt"Team {worstTeam} has {worstPct:.1f}% in one cluster (>80%)"
    )

  # Assertion 3: All altars should have at least some villagers
  block:
    var emptyAltars = 0
    var totalAltars = 0
    for ts in final.teams:
      for a in ts.altars:
        inc totalAltars
        if a.villagerCount == 0:
          inc emptyAltars
    result.add AssertionResult(
      name: "no_empty_altars",
      passed: emptyAltars == 0,
      detail: if emptyAltars == 0: fmt"All {totalAltars} altars have villagers"
              else: fmt"{emptyAltars}/{totalAltars} altars have 0 villagers"
    )

  # Assertion 4: No villagers should be lost (total preserved across snapshots)
  # Compare first and last snapshot per team - total villager count should not decrease
  # (villagers can only be created, not permanently destroyed in normal gameplay)
  block:
    let first = report.snapshots[0]
    var villagersPreserved = true
    var detail = "Villager counts stable"
    for teamIdx in 0 ..< min(first.teams.len, final.teams.len):
      let ft = first.teams[teamIdx]
      let lt = final.teams[teamIdx]
      # Total villagers should grow or stay the same (new villagers are trained)
      # We check that alive count hasn't dropped to zero for teams that started with villagers
      if ft.aliveVillagers > 0 and lt.totalVillagers == 0:
        villagersPreserved = false
        detail = fmt"Team {ft.teamId}: lost all villagers ({ft.totalVillagers} -> {lt.totalVillagers})"
        break
    result.add AssertionResult(
      name: "villagers_preserved",
      passed: villagersPreserved,
      detail: detail
    )

# ---------------------------------------------------------------------------
# Detect split events by comparing consecutive snapshots
# ---------------------------------------------------------------------------

proc detectEvents(report: var AuditReport) =
  for i in 1 ..< report.snapshots.len:
    let prev = report.snapshots[i-1]
    let curr = report.snapshots[i]
    for teamIdx in 0 ..< min(prev.teams.len, curr.teams.len):
      let pt = prev.teams[teamIdx]
      let ct = curr.teams[teamIdx]
      if ct.altarCount > pt.altarCount:
        report.events.add SplitEvent(
          step: curr.step,
          teamId: ct.teamId,
          description: fmt"New altar built (altars: {pt.altarCount} -> {ct.altarCount})"
        )
      if ct.townCenterCount > pt.townCenterCount:
        report.events.add SplitEvent(
          step: curr.step,
          teamId: ct.teamId,
          description: fmt"New town center built (TCs: {pt.townCenterCount} -> {ct.townCenterCount})"
        )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

when isMainModule:
  let steps = max(1, parseEnvInt("TV_AUDIT_STEPS", 2000))
  let seed = parseEnvInt("TV_AUDIT_SEED", 42)
  let interval = max(1, parseEnvInt("TV_AUDIT_INTERVAL", 100))
  let jsonMode = "--json" in commandLineParams()

  if not jsonMode:
    echo fmt"Settlement audit: {steps} steps, seed={seed}, interval={interval}"

  var env = newEnvironment()
  initGlobalController(BuiltinAI, seed)

  var report = AuditReport(
    seed: seed,
    totalSteps: steps,
    snapshotInterval: interval
  )

  # Initial snapshot
  report.snapshots.add collectSnapshot(env, 0)

  # Run simulation
  var actions: array[MapAgents, uint16]
  for stepIdx in 1 .. steps:
    actions = getActions(env)
    env.step(addr actions)

    if stepIdx mod interval == 0 or stepIdx == steps:
      report.snapshots.add collectSnapshot(env, stepIdx)

    if not jsonMode and stepIdx mod 500 == 0:
      echo fmt"  step {stepIdx}/{steps}..."

  # Detect events from snapshot differences
  report.detectEvents()

  # Run assertions
  let assertions = runAssertions(report)

  if jsonMode:
    var j = report.toJson()
    var assertionsNode = newJArray()
    for a in assertions:
      assertionsNode.add %*{
        "name": a.name,
        "passed": a.passed,
        "detail": a.detail
      }
    j["assertions"] = assertionsNode
    echo $j
  else:
    printTextReport(report)

    # Print assertion results
    echo ""
    echo "-" .repeat(72)
    echo "ASSERTIONS"
    echo "-" .repeat(72)
    var allPassed = true
    for a in assertions:
      let status = if a.passed: "PASS" else: "FAIL"
      let marker = if a.passed: "+" else: "X"
      echo fmt"  [{marker}] {status}: {a.name} - {a.detail}"
      if not a.passed:
        allPassed = false

    echo ""
    if allPassed:
      echo "All assertions passed."
    else:
      echo "SOME ASSERTIONS FAILED."
    echo "=" .repeat(72)

  # Exit with non-zero if any assertion failed
  var failCount = 0
  for a in assertions:
    if not a.passed:
      inc failCount
  if failCount > 0:
    quit(1)
