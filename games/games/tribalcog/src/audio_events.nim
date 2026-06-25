## Map game events to audio playback.
##
## Call these helpers from game logic where combat, deaths, building, and
## UI events occur.

import
  vmath,
  types

type
  VoiceCategory = enum
    VoiceSoldier
    VoiceVillager
    VoiceMonk
    VoiceCavalry
    VoiceArcher
    VoiceSiege
    VoiceNaval

proc voiceCategory(unitClass: AgentUnitClass): VoiceCategory =
  ## Map a unit class to its voice category.
  case unitClass
  of UnitVillager:
    VoiceVillager
  of UnitMonk:
    VoiceMonk
  of UnitKnight, UnitCataphract, UnitScout, UnitLightCavalry, UnitHussar,
      UnitMameluke:
    VoiceCavalry
  of UnitArcher, UnitCrossbowman, UnitArbalester, UnitLongbowman,
      UnitJanissary:
    VoiceArcher
  of UnitBatteringRam, UnitMangonel, UnitTrebuchet, UnitScorpion:
    VoiceSiege
  of UnitBoat, UnitTradeCog, UnitGalley, UnitFireShip:
    VoiceNaval
  else:
    VoiceSoldier

proc getUnitVoiceCategory*(unitClass: AgentUnitClass): string =
  ## Return the voice category name for a unit class.
  case voiceCategory(unitClass)
  of VoiceVillager:
    "villager"
  of VoiceMonk:
    "monk"
  of VoiceCavalry:
    "cavalry"
  of VoiceArcher:
    "archer"
  of VoiceSiege:
    "siege"
  of VoiceNaval:
    "naval"
  of VoiceSoldier:
    "soldier"

proc isRangedUnit*(unitClass: AgentUnitClass): bool =
  ## Return true when a unit class uses ranged attacks.
  unitClass in {
    UnitArcher,
    UnitCrossbowman,
    UnitArbalester,
    UnitLongbowman,
    UnitJanissary,
    UnitMangonel,
    UnitTrebuchet,
    UnitScorpion,
    UnitGalley
  }

proc isCavalryUnit*(unitClass: AgentUnitClass): bool =
  ## Return true when a unit class is cavalry.
  unitClass in {
    UnitKnight,
    UnitCataphract,
    UnitScout,
    UnitLightCavalry,
    UnitHussar,
    UnitMameluke
  }

proc isSiegeUnit*(unitClass: AgentUnitClass): bool =
  ## Return true when a unit class is siege.
  unitClass in {UnitBatteringRam, UnitMangonel, UnitTrebuchet, UnitScorpion}

when defined(audio):
  import
    audio

  proc audioOnAttack*(attackerClass: AgentUnitClass, pos: IVec2) =
    ## Play audio for a unit attack.
    if isRangedUnit(attackerClass):
      playCombatSound(SndArrowShoot, pos, 0.7)
    elif isSiegeUnit(attackerClass):
      playCombatSound(SndSiegeAttack, pos, 1.0)
    else:
      playCombatSound(SndSwordHit, pos, 0.8)

  proc audioOnHit*(targetClass: AgentUnitClass, pos: IVec2, damage: int) =
    ## Play audio for a unit taking damage.
    # Scale volume slightly by damage.
    let vol = clamp(0.5 + (damage.float32 / 50.0), 0.5, 1.0)
    if isRangedUnit(targetClass):
      playCombatSound(SndArrowHit, pos, vol * 0.8)
    else:
      playCombatSound(SndSwordHit, pos, vol)

  proc audioOnDeath*(unitClass: AgentUnitClass, pos: IVec2) =
    ## Play audio for a unit death.
    if isCavalryUnit(unitClass):
      playDeathSound(SndDeathHorse, pos)
    elif isSiegeUnit(unitClass):
      playDeathSound(SndDeathBuilding, pos)
    else:
      playDeathSound(SndDeathMale, pos)

  proc audioOnConversion*(pos: IVec2) =
    ## Play audio for a monk conversion.
    playCombatSound(SndMonkConvert, pos, 1.0)

  proc audioOnBuildingStart*(pos: IVec2) =
    ## Play audio for construction start.
    playBuildingSound(SndBuildStart, pos)

  proc audioOnBuildingProgress*(pos: IVec2) =
    ## Play audio during construction progress.
    playBuildingSound(SndBuildHammer, pos)

  proc audioOnBuildingComplete*(pos: IVec2) =
    ## Play audio for construction completion.
    playBuildingSound(SndBuildComplete, pos)

  proc audioOnBuildingDestroyed*(pos: IVec2) =
    ## Play audio for a destroyed building.
    playDeathSound(SndBuildDestroy, pos)

  proc audioOnGatherWood*(pos: IVec2) =
    ## Play audio for wood gathering.
    playResourceSound(SndChopWood, pos)

  proc audioOnGatherStone*(pos: IVec2) =
    ## Play audio for stone gathering.
    playResourceSound(SndMineStone, pos)

  proc audioOnGatherGold*(pos: IVec2) =
    ## Play audio for gold gathering.
    playResourceSound(SndMineGold, pos)

  proc audioOnGatherFood*(pos: IVec2, fromFarm: bool) =
    ## Play audio for food gathering.
    if fromFarm:
      playResourceSound(SndFarmHarvest, pos)
    else:
      playResourceSound(SndFishCatch, pos)

  proc audioOnUnitSelected*(unitClass: AgentUnitClass) =
    ## Play audio for unit selection.
    case voiceCategory(unitClass)
    of VoiceVillager:
      playUnitVoice(SndVillagerWhat)
    of VoiceMonk:
      playUnitVoice(SndMonkYes)
    else:
      playUnitVoice(SndSoldierWhat)

  proc audioOnUnitCommand*(unitClass: AgentUnitClass) =
    ## Play audio for a unit command.
    case voiceCategory(unitClass)
    of VoiceVillager:
      playUnitVoice(SndVillagerYes)
    of VoiceMonk:
      playUnitVoice(SndMonkYes)
    else:
      playUnitVoice(SndSoldierYes)

  proc audioOnResearchComplete*() =
    ## Play audio for completed research.
    playUISound(SndUIResearchComplete)

  proc audioOnUIClick*() =
    ## Play audio for a UI click.
    playUISound(SndUIClick)

  proc audioOnAlert*() =
    ## Play audio for an important alert.
    playUISound(SndUIAlert)

  proc updateAmbientForBiome*(biome: string) =
    ## Update the ambient sound for the current biome.
    setAmbientBiome(biome)

  proc updateAmbientForCombat*(inCombat: bool) =
    ## Enable combat ambience when nearby combat is active.
    if inCombat:
      setAmbientBiome("battle")

else:
  proc audioOnAttack*(attackerClass: AgentUnitClass, pos: IVec2) =
    ## Ignore attack audio when audio is disabled.
    discard attackerClass
    discard pos
    discard

  proc audioOnHit*(targetClass: AgentUnitClass, pos: IVec2, damage: int) =
    ## Ignore hit audio when audio is disabled.
    discard targetClass
    discard pos
    discard damage
    discard

  proc audioOnDeath*(unitClass: AgentUnitClass, pos: IVec2) =
    ## Ignore death audio when audio is disabled.
    discard unitClass
    discard pos
    discard

  proc audioOnConversion*(pos: IVec2) =
    ## Ignore conversion audio when audio is disabled.
    discard pos
    discard

  proc audioOnBuildingStart*(pos: IVec2) =
    ## Ignore build-start audio when audio is disabled.
    discard pos
    discard

  proc audioOnBuildingProgress*(pos: IVec2) =
    ## Ignore build-progress audio when audio is disabled.
    discard pos
    discard

  proc audioOnBuildingComplete*(pos: IVec2) =
    ## Ignore build-complete audio when audio is disabled.
    discard pos
    discard

  proc audioOnBuildingDestroyed*(pos: IVec2) =
    ## Ignore building-destroyed audio when audio is disabled.
    discard pos
    discard

  proc audioOnGatherWood*(pos: IVec2) =
    ## Ignore wood-gathering audio when audio is disabled.
    discard pos
    discard

  proc audioOnGatherStone*(pos: IVec2) =
    ## Ignore stone-gathering audio when audio is disabled.
    discard pos
    discard

  proc audioOnGatherGold*(pos: IVec2) =
    ## Ignore gold-gathering audio when audio is disabled.
    discard pos
    discard

  proc audioOnGatherFood*(pos: IVec2, fromFarm: bool) =
    ## Ignore food-gathering audio when audio is disabled.
    discard pos
    discard fromFarm
    discard

  proc audioOnUnitSelected*(unitClass: AgentUnitClass) =
    ## Ignore unit-selection audio when audio is disabled.
    discard unitClass
    discard

  proc audioOnUnitCommand*(unitClass: AgentUnitClass) =
    ## Ignore unit-command audio when audio is disabled.
    discard unitClass
    discard

  proc audioOnResearchComplete*() =
    ## Ignore research audio when audio is disabled.
    discard

  proc audioOnUIClick*() =
    ## Ignore UI-click audio when audio is disabled.
    discard

  proc audioOnAlert*() =
    ## Ignore alert audio when audio is disabled.
    discard

  proc updateAmbientForBiome*(biome: string) =
    ## Ignore biome ambience changes when audio is disabled.
    discard biome
    discard

  proc updateAmbientForCombat*(inCombat: bool) =
    ## Ignore combat ambience changes when audio is disabled.
    discard inCombat
    discard
