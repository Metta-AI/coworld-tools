## audio.nim - Game audio system
##
## Provides ambient background sounds, battle audio cues, and unit acknowledgment voices.
## Gated behind -d:audio compile flag. Zero-cost when disabled.
##
## Audio categories:
## - Ambient: Background nature sounds based on biome (forest birds, desert wind, etc.)
## - Combat: Attack sounds, hits, deaths
## - Building: Construction, completion, destruction
## - Unit: Acknowledgment voices when selected/commanded
## - Resource: Gathering sounds (chopping, mining, farming)
##
## Usage:
##   When -d:audio is enabled, call initAudio() at startup and
##   updateAudio() each frame. Sound events are queued via the
##   playSound/playAmbient procs.
##
## The audio system uses a priority-based queue to prevent sound spam
## and maintains ambient loops based on camera position.

when defined(audio):
  import std/[tables, sets, random, math, os, options]
  import vmath

  type
    SoundCategory* = enum
      scAmbient     ## Background ambient loops (biome-based)
      scCombat      ## Combat sounds (attacks, hits)
      scDeath       ## Death sounds
      scBuilding    ## Building construction/completion
      scResource    ## Resource gathering sounds
      scUnit        ## Unit acknowledgment voices
      scUI          ## UI feedback sounds

    SoundPriority* = enum
      spLow         ## Background sounds, can be skipped if too many
      spNormal      ## Standard game sounds
      spHigh        ## Important events (deaths, building complete)
      spCritical    ## Always plays (alerts, unit selection)

    SoundEvent* = object
      category*: SoundCategory
      soundId*: string        ## Identifier for the sound asset
      priority*: SoundPriority
      volume*: float32        ## 0.0 to 1.0
      worldPos*: Option[IVec2] ## For spatial audio (None = UI/global sound)
      pitch*: float32         ## Pitch variation (1.0 = normal)

    AmbientState* = object
      currentBiome*: string   ## Current biome for ambient selection
      ambientVolume*: float32 ## Master ambient volume
      isPlaying*: bool        ## Whether ambient loop is active

    AudioManager* = object
      initialized*: bool
      enabled*: bool
      masterVolume*: float32
      soundQueue*: seq[SoundEvent]
      ambientState*: AmbientState
      recentSounds*: Table[string, int]  ## Prevent spam: soundId -> frame last played
      currentFrame*: int
      rand*: Rand
      # Cooldowns for sound categories (frames between sounds)
      categoryCooldowns*: array[SoundCategory, int]
      lastCategoryFrame*: array[SoundCategory, int]
      # Debug mode
      debugLog*: bool

  var audioManager*: AudioManager

  const
    # Minimum frames between same sound
    SoundSpamCooldown = 3
    # Category-specific cooldowns (frames)
    DefaultCategoryCooldowns: array[SoundCategory, int] = [
      30,  # scAmbient - ambient sounds transition slowly
      2,   # scCombat - rapid combat sounds OK
      5,   # scDeath - death sounds spaced out
      10,  # scBuilding - building sounds not too frequent
      3,   # scResource - gathering can be frequent
      10,  # scUnit - unit voices not too spammy
      5    # scUI - UI sounds moderate
    ]
    # Max queued sounds per frame to prevent overwhelming
    MaxSoundsPerFrame = 8

  proc initAudio*() =
    ## Initialize the audio system. Call once at startup.
    let debugEnv = getEnv("TV_AUDIO_DEBUG", "")
    audioManager = AudioManager(
      initialized: true,
      enabled: true,
      masterVolume: 1.0,
      soundQueue: @[],
      ambientState: AmbientState(
        currentBiome: "forest",
        ambientVolume: 0.5,
        isPlaying: false
      ),
      recentSounds: initTable[string, int](),
      currentFrame: 0,
      rand: initRand(42),
      categoryCooldowns: DefaultCategoryCooldowns,
      debugLog: debugEnv notin ["", "0", "false"]
    )
    if audioManager.debugLog:
      echo "[Audio] Initialized audio system"

  proc setAudioEnabled*(enabled: bool) =
    ## Enable or disable audio playback
    audioManager.enabled = enabled
    if audioManager.debugLog:
      echo "[Audio] Audio ", (if enabled: "enabled" else: "disabled")

  proc setMasterVolume*(volume: float32) =
    ## Set master volume (0.0 to 1.0)
    audioManager.masterVolume = clamp(volume, 0.0, 1.0)

  proc setAmbientVolume*(volume: float32) =
    ## Set ambient sound volume (0.0 to 1.0)
    audioManager.ambientState.ambientVolume = clamp(volume, 0.0, 1.0)

  proc canPlaySound(soundId: string, category: SoundCategory): bool =
    ## Check if a sound can be played (cooldown and spam prevention)
    if not audioManager.enabled:
      return false

    # Check category cooldown
    let lastFrame = audioManager.lastCategoryFrame[category]
    let cooldown = audioManager.categoryCooldowns[category]
    if audioManager.currentFrame - lastFrame < cooldown:
      return false

    # Check spam prevention for specific sound
    if soundId in audioManager.recentSounds:
      let lastPlayed = audioManager.recentSounds[soundId]
      if audioManager.currentFrame - lastPlayed < SoundSpamCooldown:
        return false

    true

  proc queueSound*(category: SoundCategory, soundId: string,
                   priority: SoundPriority = spNormal,
                   volume: float32 = 1.0,
                   worldPos: Option[IVec2] = none(IVec2),
                   pitchVariation: float32 = 0.0) =
    ## Queue a sound to be played. Sounds are processed in updateAudio.
    if not audioManager.initialized or not audioManager.enabled:
      return

    # Skip if on cooldown (unless critical priority)
    if priority != spCritical and not canPlaySound(soundId, category):
      return

    # Apply random pitch variation if specified
    var pitch = 1.0'f32
    if pitchVariation > 0:
      pitch = 1.0 + audioManager.rand.rand(-pitchVariation..pitchVariation)

    let event = SoundEvent(
      category: category,
      soundId: soundId,
      priority: priority,
      volume: volume * audioManager.masterVolume,
      worldPos: worldPos,
      pitch: pitch
    )

    audioManager.soundQueue.add(event)
    audioManager.recentSounds[soundId] = audioManager.currentFrame
    audioManager.lastCategoryFrame[category] = audioManager.currentFrame

  # Convenience procs for common sound types

  proc playCombatSound*(soundId: string, pos: IVec2, volume: float32 = 0.8) =
    ## Play a combat sound (attack, hit)
    queueSound(scCombat, soundId, spNormal, volume, some(pos), 0.1)

  proc playDeathSound*(soundId: string, pos: IVec2) =
    ## Play a death sound
    queueSound(scDeath, soundId, spHigh, 1.0, some(pos), 0.05)

  proc playBuildingSound*(soundId: string, pos: IVec2) =
    ## Play a building-related sound
    queueSound(scBuilding, soundId, spNormal, 0.7, some(pos))

  proc playResourceSound*(soundId: string, pos: IVec2, volume: float32 = 0.6) =
    ## Play a resource gathering sound
    queueSound(scResource, soundId, spLow, volume, some(pos), 0.15)

  proc playUnitVoice*(soundId: string, volume: float32 = 1.0) =
    ## Play a unit acknowledgment voice (no position - plays at full volume)
    queueSound(scUnit, soundId, spCritical, volume, none(IVec2), 0.05)

  proc playUISound*(soundId: string) =
    ## Play a UI feedback sound
    queueSound(scUI, soundId, spCritical, 0.8, none(IVec2))

  proc setAmbientBiome*(biome: string) =
    ## Set the current biome for ambient sound selection
    if audioManager.ambientState.currentBiome != biome:
      audioManager.ambientState.currentBiome = biome
      if audioManager.debugLog:
        echo "[Audio] Ambient biome changed to: ", biome

  proc updateAudio*() =
    ## Process queued sounds and update ambient state. Call once per frame.
    if not audioManager.initialized:
      return

    inc audioManager.currentFrame

    # Sort by priority (higher priority first)
    if audioManager.soundQueue.len > 0:
      # Simple priority sort
      var sorted = audioManager.soundQueue
      for i in 0 ..< sorted.len:
        for j in i + 1 ..< sorted.len:
          if sorted[j].priority > sorted[i].priority:
            swap(sorted[i], sorted[j])

      # Process up to MaxSoundsPerFrame sounds
      let toProcess = min(sorted.len, MaxSoundsPerFrame)
      for i in 0 ..< toProcess:
        let event = sorted[i]
        # Actually play the sound (placeholder - would call audio backend)
        if audioManager.debugLog:
          var posStr = "global"
          if event.worldPos.isSome:
            let p = event.worldPos.get
            posStr = "(" & $p.x & "," & $p.y & ")"
          echo "[Audio] Play: ", event.soundId, " cat=", event.category,
               " pri=", event.priority, " vol=", $event.volume,
               " pos=", posStr

      audioManager.soundQueue.setLen(0)

    # Clean up old entries from recentSounds table (every 100 frames)
    if audioManager.currentFrame mod 100 == 0:
      var toRemove: seq[string] = @[]
      for soundId, frame in audioManager.recentSounds:
        if audioManager.currentFrame - frame > 60:  # 1 second at 60fps
          toRemove.add(soundId)
      for soundId in toRemove:
        audioManager.recentSounds.del(soundId)

  proc shutdownAudio*() =
    ## Shutdown the audio system. Call at program exit.
    if audioManager.debugLog:
      echo "[Audio] Shutting down audio system"
    audioManager.initialized = false
    audioManager.soundQueue.setLen(0)

  # Sound ID constants for consistent naming
  const
    # Combat sounds
    SndSwordHit* = "combat/sword_hit"
    SndArrowShoot* = "combat/arrow_shoot"
    SndArrowHit* = "combat/arrow_hit"
    SndSiegeAttack* = "combat/siege_attack"
    SndMonkConvert* = "combat/monk_convert"

    # Death sounds
    SndDeathMale* = "death/male"
    SndDeathFemale* = "death/female"
    SndDeathHorse* = "death/horse"
    SndDeathBuilding* = "death/building"

    # Building sounds
    SndBuildStart* = "building/start"
    SndBuildHammer* = "building/hammer"
    SndBuildComplete* = "building/complete"
    SndBuildDestroy* = "building/destroy"

    # Resource sounds
    SndChopWood* = "resource/chop_wood"
    SndMineStone* = "resource/mine_stone"
    SndMineGold* = "resource/mine_gold"
    SndFarmHarvest* = "resource/farm_harvest"
    SndFishCatch* = "resource/fish_catch"

    # Unit voices (acknowledgments)
    SndVillagerYes* = "voice/villager_yes"
    SndVillagerWhat* = "voice/villager_what"
    SndSoldierYes* = "voice/soldier_yes"
    SndSoldierWhat* = "voice/soldier_what"
    SndMonkYes* = "voice/monk_yes"

    # Ambient sounds
    SndAmbientForest* = "ambient/forest"
    SndAmbientDesert* = "ambient/desert"
    SndAmbientSnow* = "ambient/snow"
    SndAmbientSwamp* = "ambient/swamp"
    SndAmbientBattle* = "ambient/battle"

    # UI sounds
    SndUIClick* = "ui/click"
    SndUIAlert* = "ui/alert"
    SndUIResearchComplete* = "ui/research_complete"

# Stub implementations when audio is disabled
else:
  # No-op stubs when -d:audio is not defined
  proc initAudio*() = discard
  proc shutdownAudio*() = discard
  proc updateAudio*() = discard
  proc setAudioEnabled*(enabled: bool) = discard
  proc setMasterVolume*(volume: float32) = discard
  proc setAmbientVolume*(volume: float32) = discard
  proc setAmbientBiome*(biome: string) = discard
  proc playCombatSound*(soundId: string, pos: IVec2, volume: float32 = 0.8) = discard
  proc playDeathSound*(soundId: string, pos: IVec2) = discard
  proc playBuildingSound*(soundId: string, pos: IVec2) = discard
  proc playResourceSound*(soundId: string, pos: IVec2, volume: float32 = 0.6) = discard
  proc playUnitVoice*(soundId: string, volume: float32 = 1.0) = discard
  proc playUISound*(soundId: string) = discard

  const
    SndSwordHit* = ""
    SndArrowShoot* = ""
    SndArrowHit* = ""
    SndSiegeAttack* = ""
    SndMonkConvert* = ""
    SndDeathMale* = ""
    SndDeathFemale* = ""
    SndDeathHorse* = ""
    SndDeathBuilding* = ""
    SndBuildStart* = ""
    SndBuildHammer* = ""
    SndBuildComplete* = ""
    SndBuildDestroy* = ""
    SndChopWood* = ""
    SndMineStone* = ""
    SndMineGold* = ""
    SndFarmHarvest* = ""
    SndFishCatch* = ""
    SndVillagerYes* = ""
    SndVillagerWhat* = ""
    SndSoldierYes* = ""
    SndSoldierWhat* = ""
    SndMonkYes* = ""
    SndAmbientForest* = ""
    SndAmbientDesert* = ""
    SndAmbientSnow* = ""
    SndAmbientSwamp* = ""
    SndAmbientBattle* = ""
    SndUIClick* = ""
    SndUIAlert* = ""
    SndUIResearchComplete* = ""
