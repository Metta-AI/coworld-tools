# AdjacentOffsets8 is imported via environment.nim from common_types

const
  ConnectWallCost = 5
  ConnectTerrainCost = 6
  ConnectWaterCost = 50
  ConnectDiggableKinds = {Wall, Tree, Wheat, Stubble, Stone, Gold, Bush, Cactus, Stalagmite, Stump}

proc makeConnected*(env: Environment) =
  template inPlayableBounds(pos: IVec2): bool =
    pos.x >= MapBorder and pos.x < MapWidth - MapBorder and
      pos.y >= MapBorder and pos.y < MapHeight - MapBorder

  proc digCost(env: Environment, pos: IVec2): int =
    if not inPlayableBounds(pos):
      return int.high
    let terrain = env.terrain[pos.x][pos.y]
    if env.isEmpty(pos):
      if terrain == Water:
        return ConnectWaterCost
      if terrain in {Dune, Snow} or isBlockedTerrain(terrain):
        return ConnectTerrainCost
      return 1
    let thing = env.getThing(pos)
    if not thing.isNil and thing.kind in ConnectDiggableKinds:
      return ConnectWallCost
    int.high
  proc digCell(env: Environment, pos: IVec2) =
    if not inPlayableBounds(pos):
      return
    let thing = env.getThing(pos)
    if not thing.isNil:
      if thing.kind notin ConnectDiggableKinds:
        return  # Can't dig non-diggable things
      removeThing(env, thing)
    let terrain = env.terrain[pos.x][pos.y]
    if terrain in {Water, Dune, Snow, Mountain}:
      # Remove background things (e.g. Fish) that depend on water terrain
      let bg = env.getBackgroundThing(pos)
      if bg.isKind(Fish):
        removeThing(env, bg)
      env.terrain[pos.x][pos.y] = Empty
      env.resetTileColor(pos)

  proc labelComponents(env: Environment,
                       labels: var array[MapWidth, array[MapHeight, int16]],
                       counts: var seq[int]): int =
    labels = default(array[MapWidth, array[MapHeight, int16]])
    counts.setLen(0)
    var label = 0
    for x in MapBorder ..< MapWidth - MapBorder:
      for y in MapBorder ..< MapHeight - MapBorder:
        if labels[x][y] != 0 or digCost(env, ivec2(x, y)) != 1:
          continue
        inc label
        var queue: seq[IVec2] = @[ivec2(x, y)]
        var head = 0
        labels[x][y] = label.int16
        var count = 0
        while head < queue.len:
          let pos = queue[head]
          inc head
          inc count
          for d in AdjacentOffsets8:
            let nx = pos.x + d.x
            let ny = pos.y + d.y
            let npos = ivec2(nx.int32, ny.int32)
            if digCost(env, npos) != 1:
              continue
            if not env.canTraverseElevation(pos, npos):
              continue
            let ix = nx.int
            let iy = ny.int
            if labels[ix][iy] != 0:
              continue
            labels[ix][iy] = label.int16
            queue.add(npos)
        counts.add(count)
    label

  proc computeDistances(env: Environment,
                        labels: array[MapWidth, array[MapHeight, int16]],
                        sourceLabel: int16,
                        dist: var seq[int],
                        prev: var seq[int]) =
    let size = MapWidth * MapHeight
    dist.setLen(size)
    prev.setLen(size)
    for i in 0 ..< size:
      dist[i] = -1
      prev[i] = -1

    var queue: seq[int] = @[]
    var head = 0
    for x in MapBorder ..< MapWidth - MapBorder:
      for y in MapBorder ..< MapHeight - MapBorder:
        if labels[x][y] == sourceLabel:
          let cellIdx = y * MapWidth + x
          dist[cellIdx] = 0
          prev[cellIdx] = -2
          queue.add(cellIdx)

    while head < queue.len:
      let cellIdx = queue[head]
      inc head
      let x = cellIdx mod MapWidth
      let y = cellIdx div MapWidth
      let curPos = ivec2(x.int32, y.int32)
      for d in AdjacentOffsets8:
        let nx = x + d.x.int
        let ny = y + d.y.int
        let npos = ivec2(nx.int32, ny.int32)
        if not env.canTraverseElevation(curPos, npos):
          continue
        if digCost(env, npos) == int.high:
          continue
        let neighborIdx = ny * MapWidth + nx
        if dist[neighborIdx] < 0:
          dist[neighborIdx] = dist[cellIdx] + 1
          prev[neighborIdx] = cellIdx
          queue.add(neighborIdx)

  var labels: array[MapWidth, array[MapHeight, int16]]
  var counts: seq[int] = @[]
  while true:
    let componentCount = labelComponents(env, labels, counts)
    if componentCount <= 1:
      break
    var largest = 0
    var largestCount = -1
    for i, count in counts:
      if count > largestCount:
        largestCount = count
        largest = i + 1
    var dist: seq[int] = @[]
    var prev: seq[int] = @[]
    computeDistances(env, labels, largest.int16, dist, prev)
    let inf = MapWidth * MapHeight + 1
    var anyDig = false
    for label in 1 .. componentCount:
      if label == largest:
        continue
      var bestIdx = -1
      var bestDist = inf
      for x in MapBorder ..< MapWidth - MapBorder:
        for y in MapBorder ..< MapHeight - MapBorder:
          if labels[x][y] != label.int16:
            continue
          let cellIdx = y * MapWidth + x
          if dist[cellIdx] >= 0 and dist[cellIdx] < bestDist:
            bestDist = dist[cellIdx]
            bestIdx = cellIdx
      if bestIdx >= 0 and bestDist < inf:
        var currentIdx = bestIdx
        while currentIdx >= 0 and prev[currentIdx] >= 0:
          let x = currentIdx mod MapWidth
          let y = currentIdx div MapWidth
          digCell(env, ivec2(x.int32, y.int32))
          currentIdx = prev[currentIdx]
        anyDig = true
    if not anyDig:
      break
