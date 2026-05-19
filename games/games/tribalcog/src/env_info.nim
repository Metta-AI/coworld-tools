import
  std/tables,
  common_types, types

export types, common_types

const
  ## Store the total action count derived from verbs and arguments.
  ActionCount* = ActionVerbCount * ActionArgumentCount
  ## Store the sentinel ID for features absent from the original mapping.
  UnknownFeatureId = 255

type
  ## Describe one observation feature.
  FeatureProps* = object
    id*: int
    name*: string
    normalization*: float

  ## Store runtime environment parameters passed to lazy components.
  EnvironmentInfo* = object
    mapWidth*: int
    mapHeight*: int
    obsWidth*: int
    obsHeight*: int
    obsLayers*: int
    numAgents*: int
    numTeams*: int
    agentsPerTeam*: int
    numActions*: int
    numActionVerbs*: int
    numActionArgs*: int
    obsFeatures*: seq[FeatureProps]
    featureNameToId*: Table[string, int]
    originalFeatureMapping*: Table[string, int]
    initialized*: bool

  ## Store the result of an environment initialization attempt.
  InitResult* = object
    success*: bool
    message*: string

  ## Describe a component that supports lazy environment initialization.
  InitializableComponent* = concept c
    c.initializeToEnvironment(EnvironmentInfo) is InitResult

proc addDefaultObservationFeatures(info: var EnvironmentInfo) =
  ## Populate observation feature metadata from ObservationName.
  for layer in ObservationName:
    let props = FeatureProps(
      id: ord(layer),
      name: $layer,
      normalization: 1.0,
    )
    info.obsFeatures.add(props)
    info.featureNameToId[$layer] = ord(layer)

proc newEnvironmentInfo*(): EnvironmentInfo =
  ## Create an uninitialized EnvironmentInfo.
  result = EnvironmentInfo(
    mapWidth: 0,
    mapHeight: 0,
    obsWidth: 0,
    obsHeight: 0,
    obsLayers: 0,
    numAgents: 0,
    numTeams: 0,
    agentsPerTeam: 0,
    numActions: 0,
    numActionVerbs: 0,
    numActionArgs: 0,
    obsFeatures: @[],
    featureNameToId: initTable[string, int](),
    originalFeatureMapping: initTable[string, int](),
    initialized: false,
  )

proc defaultEnvironmentInfo*(): EnvironmentInfo =
  ## Create EnvironmentInfo with compile-time default values.
  result = newEnvironmentInfo()
  result.mapWidth = MapWidth
  result.mapHeight = MapHeight
  result.obsWidth = ObservationWidth
  result.obsHeight = ObservationHeight
  result.obsLayers = ObservationLayers
  result.numAgents = MapAgents
  result.numTeams = MapRoomObjectsTeams
  result.agentsPerTeam = MapAgentsPerTeam
  result.numActions = ActionCount
  result.numActionVerbs = ActionVerbCount
  result.numActionArgs = ActionArgumentCount
  result.initialized = true
  result.addDefaultObservationFeatures()

proc isValid*(info: EnvironmentInfo): bool =
  ## Return whether the environment info has valid dimensions.
  info.initialized and
    info.mapWidth > 0 and
    info.mapHeight > 0 and
    info.numAgents > 0

proc obsRadius*(info: EnvironmentInfo): int =
  ## Return the observation radius derived from observation width.
  info.obsWidth div 2

proc getFeatureId*(info: EnvironmentInfo, name: string): int =
  ## Return a feature ID by name, or -1 when it is absent.
  if name in info.featureNameToId:
    return info.featureNameToId[name]
  -1

proc getFeatureNormalization*(info: EnvironmentInfo, featureId: int): float =
  ## Return the normalization factor for one feature ID.
  for feature in info.obsFeatures:
    if feature.id == featureId:
      return feature.normalization
  1.0

proc hasFeature*(info: EnvironmentInfo, name: string): bool =
  ## Return whether the named feature exists.
  name in info.featureNameToId

proc storeOriginalMapping*(info: var EnvironmentInfo) =
  ## Store the current feature mapping as the baseline mapping.
  info.originalFeatureMapping = info.featureNameToId

proc createFeatureRemapping*(
  info: EnvironmentInfo,
  currentFeatures: seq[FeatureProps]
): Table[int, int] =
  ## Create a remapping from current feature IDs to original IDs.
  result = initTable[int, int]()
  for feature in currentFeatures:
    if feature.name in info.originalFeatureMapping:
      let originalId = info.originalFeatureMapping[feature.name]
      if feature.id != originalId:
        result[feature.id] = originalId
    else:
      result[feature.id] = UnknownFeatureId
