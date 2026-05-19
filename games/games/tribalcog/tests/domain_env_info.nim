## domain_env_info.nim - Tests for environment-aware lazy initialization pattern
##
## Tests the initializeToEnvironment() pattern implementation that enables
## components to adapt to runtime environment parameters.

import std/[unittest, strutils]
import ../src/env_info
import ../src/scripted/ai_types

suite "EnvironmentInfo":
  test "default environment info has valid dimensions":
    let info = defaultEnvironmentInfo()
    check info.initialized
    check info.mapWidth == MapWidth
    check info.mapHeight == MapHeight
    check info.numAgents == MapAgents
    check info.numTeams == MapRoomObjectsTeams
    check info.obsWidth == ObservationWidth
    check info.obsHeight == ObservationHeight
    check info.obsLayers == ObservationLayers

  test "new environment info is uninitialized":
    let info = newEnvironmentInfo()
    check not info.initialized
    check info.mapWidth == 0
    check info.mapHeight == 0
    check info.numAgents == 0

  test "isValid returns false for uninitialized info":
    let info = newEnvironmentInfo()
    check not info.isValid()

  test "isValid returns true for default info":
    let info = defaultEnvironmentInfo()
    check info.isValid()

  test "observation radius calculated correctly":
    let info = defaultEnvironmentInfo()
    check info.obsRadius() == ObservationWidth div 2

  test "default environment info populates observation features":
    let info = defaultEnvironmentInfo()
    check info.obsFeatures.len == ObservationLayers
    # First feature should be TerrainEmptyLayer
    check info.obsFeatures[0].id == 0
    check info.obsFeatures[0].name == "TerrainEmptyLayer"

  test "feature lookup by name works":
    let info = defaultEnvironmentInfo()
    check info.hasFeature("TerrainEmptyLayer")
    check info.getFeatureId("TerrainEmptyLayer") == 0
    check not info.hasFeature("NonexistentFeature")
    check info.getFeatureId("NonexistentFeature") == -1

  test "feature normalization defaults to 1.0":
    let info = defaultEnvironmentInfo()
    check info.getFeatureNormalization(0) == 1.0
    # Non-existent feature ID also returns 1.0
    check info.getFeatureNormalization(9999) == 1.0

  test "original mapping can be stored":
    var info = defaultEnvironmentInfo()
    info.storeOriginalMapping()
    check info.originalFeatureMapping.len > 0
    check "TerrainEmptyLayer" in info.originalFeatureMapping
    check info.originalFeatureMapping["TerrainEmptyLayer"] == 0

suite "Controller initializeToEnvironment":
  test "controller initializes with default params":
    let controller = newController(seed = 42)
    let result = controller.initializeToEnvironmentDefault()
    check result.success
    check result.numAgents == MapAgents
    check result.numTeams == MapRoomObjectsTeams
    check result.mapWidth == MapWidth
    check result.mapHeight == MapHeight

  test "controller initialization validates agent count":
    let controller = newController(seed = 42)
    let result = controller.initializeToEnvironment(
      numAgents = 999,  # Wrong count
      numTeams = MapRoomObjectsTeams,
      mapWidth = MapWidth,
      mapHeight = MapHeight
    )
    check not result.success
    check "Agent count mismatch" in result.message

  test "controller initialization validates team count":
    let controller = newController(seed = 42)
    let result = controller.initializeToEnvironment(
      numAgents = MapAgents,
      numTeams = 999,  # Wrong count
      mapWidth = MapWidth,
      mapHeight = MapHeight
    )
    check not result.success
    check "Team count mismatch" in result.message

  test "controller initialization validates map width":
    let controller = newController(seed = 42)
    let result = controller.initializeToEnvironment(
      numAgents = MapAgents,
      numTeams = MapRoomObjectsTeams,
      mapWidth = 999,  # Wrong width
      mapHeight = MapHeight
    )
    check not result.success
    check "Map width mismatch" in result.message

  test "controller initialization validates map height":
    let controller = newController(seed = 42)
    let result = controller.initializeToEnvironment(
      numAgents = MapAgents,
      numTeams = MapRoomObjectsTeams,
      mapWidth = MapWidth,
      mapHeight = 999  # Wrong height
    )
    check not result.success
    check "Map height mismatch" in result.message

  test "successful initialization includes descriptive message":
    let controller = newController(seed = 42)
    let result = controller.initializeToEnvironmentDefault()
    check result.success
    check "agents" in result.message
    check "teams" in result.message
    check "map" in result.message

suite "Feature remapping":
  test "create feature remapping for identical features":
    var info = defaultEnvironmentInfo()
    info.storeOriginalMapping()

    # Create remapping with same features
    let currentFeatures = info.obsFeatures
    let remapping = info.createFeatureRemapping(currentFeatures)

    # No remapping should be needed when features are identical
    check remapping.len == 0

  test "create feature remapping detects new features":
    var info = defaultEnvironmentInfo()
    info.storeOriginalMapping()

    # Create a new feature that wasn't in original
    var newFeatures: seq[FeatureProps] = @[]
    newFeatures.add(FeatureProps(id: 0, name: "TerrainEmptyLayer", normalization: 1.0))
    newFeatures.add(FeatureProps(id: 1, name: "NewFeature", normalization: 1.0))

    let remapping = info.createFeatureRemapping(newFeatures)

    # New feature should be mapped to unknown ID (255)
    check 1 in remapping
    check remapping[1] == 255

suite "InitResult helpers":
  test "InitResult creates success result":
    let result = InitResult(success: true, message: "Test message")
    check result.success
    check result.message == "Test message"

  test "InitResult creates failure result":
    let result = InitResult(success: false, message: "Error message")
    check not result.success
    check result.message == "Error message"

  test "InitResult creates custom results directly":
    let success = InitResult(success: true, message: "Custom success")
    check success.success
    check success.message == "Custom success"

    let failure = InitResult(success: false, message: "Custom failure")
    check not failure.success
    check failure.message == "Custom failure"
