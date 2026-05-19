import std/[unittest, strformat]
import environment
import terrain

const
  HubCenterSeamSeeds = [42, 123, 9999, 77777, 314159]
  HubCenterRoadRunMax = 20

proc longestRoadishRunAtRow(env: Environment, y: int): int =
  var current = 0
  for x in 0 ..< MapWidth:
    if env.terrain[x][y] in {Road, Bridge}:
      inc current
      if current > result:
        result = current
    else:
      current = 0

suite "Trading Hub: Road Layout":
  test "hub does not create a long river-parallel seam at map center":
    let centerY = MapHeight div 2
    for seed in HubCenterSeamSeeds:
      let env = newEnvironment(defaultEnvironmentConfig(), seed)
      let longest = longestRoadishRunAtRow(env, centerY)
      check longest <= HubCenterRoadRunMax
      echo &"  Seed {seed}: center-row road/bridge seam length = {longest}"
