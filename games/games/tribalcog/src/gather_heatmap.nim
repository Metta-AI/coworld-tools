## gather_heatmap.nim - ANSI console heatmap of resource gathering activity
##
## Shows where gathering is happening on the map using spatial cells.
## Each cell is colored by dominant resource type, with brightness indicating
## activity intensity. Agent positions are overlaid as team-colored dots.
## Resource depletion shown via full vs depleted node counts.
##
## Gated behind -d:gatherHeatmap compile flag.
## Interval controlled by TV_HEATMAP_INTERVAL env var (default 50 steps).
##
## Included by environment.nim — types, items, spatial_index, strutils, os are in scope.

when defined(gatherHeatmap):

  type
    GatherResourceKind* = enum
      grNone, grFood, grWood, grGold, grStone

  const
    HeatCellsX* = SpatialCellsX  # Reuse spatial grid dimensions
    HeatCellsY* = SpatialCellsY

  var
    heatmapInterval*: int = 50
    heatmapCounts*: array[HeatCellsX, array[HeatCellsY, array[GatherResourceKind, int]]]
    heatmapStepsSinceReset*: int = 0

  heatmapInterval = max(1, parseEnvInt("TV_HEATMAP_INTERVAL", 50))

  proc resetHeatmap*() =
    for cx in 0 ..< HeatCellsX:
      for cy in 0 ..< HeatCellsY:
        for rk in GatherResourceKind:
          heatmapCounts[cx][cy][rk] = 0
    heatmapStepsSinceReset = 0

  proc recordGatherEvent*(pos: IVec2, resKind: GatherResourceKind) =
    ## Call this from step.nim when a gather action succeeds.
    let cx = pos.x.int div SpatialCellSize
    let cy = pos.y.int div SpatialCellSize
    if cx >= 0 and cx < HeatCellsX and cy >= 0 and cy < HeatCellsY:
      inc heatmapCounts[cx][cy][resKind]

  proc thingToGatherKind(kind: ThingKind): GatherResourceKind =
    case kind
    of Wheat, Stubble, Fish, Bush, Cactus, Cow: grFood
    of Tree, Stump: grWood
    of Gold: grGold
    of Stone, Stalagmite: grStone
    else: grNone

  proc printGatherHeatmap*(env: Environment) =
    ## Print an ANSI-colored grid showing gathering hotspots.
    ## dark=no activity, green=food, brown=wood, yellow=gold, gray=stone.
    ## Agent positions as team-colored dots. Resource depletion shown.
    const
      Esc = "\e["
      Reset = Esc & "0m"
      Bold = Esc & "1m"

    proc heatFg(r, g, b: int): string = Esc & "38;2;" & $r & ";" & $g & ";" & $b & "m"
    proc heatBg(r, g, b: int): string = Esc & "48;2;" & $r & ";" & $g & ";" & $b & "m"

    # Team colors for agent overlay
    const TeamColors: array[8, array[3, int]] = [
      [232, 107, 107],  # 0: red
      [240, 166, 107],  # 1: orange
      [240, 209, 107],  # 2: yellow
      [153, 214, 128],  # 3: olive-lime
      [199, 97, 224],   # 4: magenta
      [107, 184, 240],  # 5: sky
      [222, 222, 222],  # 6: gray
      [237, 143, 209],  # 7: pink
    ]

    # Resource kind colors (base RGB at full intensity)
    proc resourceColor(rk: GatherResourceKind, intensity: float): (int, int, int) =
      # intensity 0.0 .. 1.0
      let t = min(1.0, intensity)
      case rk
      of grFood:  ((int)(30 + 90 * t), (int)(80 + 120 * t), (int)(20 + 30 * t))  # green
      of grWood:  ((int)(80 + 80 * t), (int)(50 + 50 * t), (int)(20 + 20 * t))    # brown
      of grGold:  ((int)(120 + 135 * t), (int)(100 + 115 * t), (int)(0))           # yellow
      of grStone: ((int)(60 + 100 * t), (int)(60 + 100 * t), (int)(60 + 100 * t))  # gray
      of grNone:  (20, 20, 20)

    # Build agent presence map: which cells have agents, by team
    var agentCells: array[HeatCellsX, array[HeatCellsY, int]]  # -1 = none, 0..7 = teamId
    for cx in 0 ..< HeatCellsX:
      for cy in 0 ..< HeatCellsY:
        agentCells[cx][cy] = -1

    for agent in env.liveAgents:
      if not isAgentAlive(env, agent): continue
      let cx = agent.pos.x.int div SpatialCellSize
      let cy = agent.pos.y.int div SpatialCellSize
      if cx >= 0 and cx < HeatCellsX and cy >= 0 and cy < HeatCellsY:
        agentCells[cx][cy] = getTeamId(agent) mod 8

    # Count resource nodes per cell: full vs depleted
    var fullNodes: array[HeatCellsX, array[HeatCellsY, int]]
    var depletedNodes: array[HeatCellsX, array[HeatCellsY, int]]
    for kind in [Wheat, Stubble, Tree, Stump, Stone, Gold, Fish, Bush, Cactus, Stalagmite, Cow]:
      for thing in env.thingsByKind[kind]:
        if thing.isNil: continue
        let cx = thing.pos.x.int div SpatialCellSize
        let cy = thing.pos.y.int div SpatialCellSize
        if cx < 0 or cx >= HeatCellsX or cy < 0 or cy >= HeatCellsY: continue
        # Depleted = stumps/stubble; full = everything else
        if kind in {Stump, Stubble}:
          inc depletedNodes[cx][cy]
        else:
          inc fullNodes[cx][cy]

    # Find max gather count for normalization
    var maxCount = 1
    for cx in 0 ..< HeatCellsX:
      for cy in 0 ..< HeatCellsY:
        var total = 0
        for rk in GatherResourceKind:
          total += heatmapCounts[cx][cy][rk]
        if total > maxCount:
          maxCount = total

    # Build output
    var buf = newStringOfCap(HeatCellsX * HeatCellsY * 40)
    buf.add(Bold & "=== gather heatmap step " & $env.currentStep &
            " (last " & $heatmapStepsSinceReset & " steps) ===" & Reset & "\n")

    # Column headers (tens digit)
    buf.add("   ")
    for cx in 0 ..< HeatCellsX:
      if cx mod 5 == 0:
        buf.add($((cx div 10) mod 10))
      else:
        buf.add(" ")
    buf.add("\n")
    # Column headers (ones digit)
    buf.add("   ")
    for cx in 0 ..< HeatCellsX:
      if cx mod 5 == 0:
        buf.add($(cx mod 10))
      else:
        buf.add(" ")
    buf.add("\n")

    for cy in 0 ..< HeatCellsY:
      # Row label
      if cy < 10:
        buf.add(" " & $cy & " ")
      else:
        buf.add($cy & " ")

      for cx in 0 ..< HeatCellsX:
        # Determine dominant resource and total activity
        var dominant = grNone
        var dominantCount = 0
        var totalCount = 0
        for rk in grFood .. grStone:
          let c = heatmapCounts[cx][cy][rk]
          totalCount += c
          if c > dominantCount:
            dominantCount = c
            dominant = rk

        let intensity = if totalCount > 0: totalCount.float / maxCount.float else: 0.0
        let (br, bg2, bb) = resourceColor(dominant, intensity)

        # Agent overlay takes priority for foreground
        if agentCells[cx][cy] >= 0:
          let teamId = agentCells[cx][cy]
          let tc = TeamColors[teamId]
          buf.add(heatBg(br, bg2, bb) & heatFg(tc[0], tc[1], tc[2]) & Bold & "@" & Reset)
        elif totalCount > 0:
          # Show resource symbol with intensity
          let ch = case dominant
            of grFood: "F"
            of grWood: "W"
            of grGold: "G"
            of grStone: "S"
            of grNone: "."
          buf.add(heatBg(br, bg2, bb) & heatFg(min(255, br + 80), min(255, bg2 + 80), min(255, bb + 80)) & ch & Reset)
        else:
          # No activity - show resource density if any
          let full = fullNodes[cx][cy]
          let depleted = depletedNodes[cx][cy]
          if full > 0:
            # Dim resource indicator
            buf.add(heatBg(20, 20, 20) & heatFg(60, 60, 60) & "+" & Reset)
          elif depleted > 0:
            buf.add(heatBg(20, 20, 20) & heatFg(40, 30, 30) & "-" & Reset)
          else:
            buf.add(heatBg(15, 15, 15) & " " & Reset)
      buf.add("\n")

    # Legend
    buf.add("\n")
    buf.add(heatBg(30, 80, 20) & heatFg(120, 200, 50) & " F " & Reset & "=food  ")
    buf.add(heatBg(80, 50, 20) & heatFg(160, 100, 40) & " W " & Reset & "=wood  ")
    buf.add(heatBg(120, 100, 0) & heatFg(255, 215, 0) & " G " & Reset & "=gold  ")
    buf.add(heatBg(60, 60, 60) & heatFg(160, 160, 160) & " S " & Reset & "=stone  ")
    buf.add(heatFg(200, 200, 200) & "@" & Reset & "=agent  ")
    buf.add(heatFg(60, 60, 60) & "+" & Reset & "=resource  ")
    buf.add(heatFg(40, 30, 30) & "-" & Reset & "=depleted")
    buf.add("\n")

    # Per-team resource summary
    buf.add(Bold & "--- team resources ---" & Reset & "\n")
    for teamId in 0 ..< MapRoomObjectsTeams:
      let tc = TeamColors[teamId]
      let stockpile = env.teamStockpiles[teamId]
      buf.add(heatFg(tc[0], tc[1], tc[2]) & Bold & "T" & $teamId & Reset & " ")
      buf.add("F:" & $stockpile.counts[ResourceFood])
      buf.add(" W:" & $stockpile.counts[ResourceWood])
      buf.add(" G:" & $stockpile.counts[ResourceGold])
      buf.add(" S:" & $stockpile.counts[ResourceStone])
      buf.add("\n")

    stdout.write(buf)
    stdout.flushFile()

  proc maybeRenderGatherHeatmap*(env: Environment) =
    ## Called from step(). Renders heatmap if interval matches.
    inc heatmapStepsSinceReset
    if env.currentStep mod heatmapInterval != 0:
      return
    env.printGatherHeatmap()
    resetHeatmap()
