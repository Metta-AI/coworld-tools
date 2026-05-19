## Time-bound memoization for evaluation caching
##
## Provides temporal memoization with timestamp-based cache invalidation.
## Unlike step-based caching (PerAgentCache in ai_core.nim), this uses wall
## clock time which is ideal for:
## - Game tree evaluations that become stale over real time
## - Preventing unbounded memory growth in long sessions
## - Caching expensive computations within frame boundaries
##
## Pattern adopted from metta common/src/metta/common/util/memoization.py

import std/[tables, hashes]
import ../common_types  # for nowSeconds

type
  MemoEntry[V] = object
    value: V
    timestamp: float64

  TimedMemoCache*[K, V] = object
    ## Generic time-bound memoization cache.
    ## Entries expire after maxAge seconds.
    cache: Table[K, MemoEntry[V]]
    maxAge: float64
    lastCleanup: float64
    cleanupInterval: float64  # How often to run cleanup (in seconds)

const
  DefaultMaxAge* = 1.0  ## Default max age for cache entries (1 second)
  DefaultCleanupInterval* = 5.0  ## How often to purge expired entries

proc initTimedMemoCache*[K, V](maxAge: float64 = DefaultMaxAge,
                                cleanupInterval: float64 = DefaultCleanupInterval): TimedMemoCache[K, V] =
  ## Initialize a new time-bound memo cache.
  ## maxAge: entries older than this (in seconds) are considered stale
  ## cleanupInterval: how often to purge expired entries
  result.cache = initTable[K, MemoEntry[V]]()
  result.maxAge = maxAge
  result.lastCleanup = nowSeconds()
  result.cleanupInterval = cleanupInterval

proc cleanup*[K, V](cache: var TimedMemoCache[K, V]) =
  ## Remove all expired entries from the cache.
  ## Called automatically during get() based on cleanupInterval.
  let now = nowSeconds()
  var keysToRemove: seq[K]
  for key, entry in cache.cache.pairs:
    if now - entry.timestamp >= cache.maxAge:
      keysToRemove.add(key)
  for key in keysToRemove:
    cache.cache.del(key)
  cache.lastCleanup = now

proc maybeCleanup[K, V](cache: var TimedMemoCache[K, V], now: float64) {.inline.} =
  ## Run cleanup if enough time has passed since last cleanup.
  if now - cache.lastCleanup >= cache.cleanupInterval:
    cache.cleanup()

proc get*[K, V](cache: var TimedMemoCache[K, V], key: K,
                compute: proc(): V): V =
  ## Get cached value or compute and cache if stale/missing.
  ## The compute proc takes no arguments and returns the result.
  let now = nowSeconds()
  cache.maybeCleanup(now)

  if key in cache.cache:
    let entry = cache.cache[key]
    if now - entry.timestamp < cache.maxAge:
      return entry.value

  # Compute and cache
  result = compute()
  cache.cache[key] = MemoEntry[V](value: result, timestamp: now)

proc getWithArg*[K, V, A](cache: var TimedMemoCache[K, V], key: K, arg: A,
                           compute: proc(a: A): V): V =
  ## Get cached value or compute and cache if stale/missing.
  ## The compute proc takes one argument and returns the result.
  let now = nowSeconds()
  cache.maybeCleanup(now)

  if key in cache.cache:
    let entry = cache.cache[key]
    if now - entry.timestamp < cache.maxAge:
      return entry.value

  # Compute and cache
  result = compute(arg)
  cache.cache[key] = MemoEntry[V](value: result, timestamp: now)

proc getWith2Args*[K, V, A, B](cache: var TimedMemoCache[K, V], key: K, arg1: A, arg2: B,
                               compute: proc(a: A, b: B): V): V =
  ## Get cached value or compute and cache if stale/missing.
  ## The compute proc takes two arguments and returns the result.
  let now = nowSeconds()
  cache.maybeCleanup(now)

  if key in cache.cache:
    let entry = cache.cache[key]
    if now - entry.timestamp < cache.maxAge:
      return entry.value

  # Compute and cache
  result = compute(arg1, arg2)
  cache.cache[key] = MemoEntry[V](value: result, timestamp: now)

proc invalidate*[K, V](cache: var TimedMemoCache[K, V], key: K) =
  ## Manually invalidate a specific cache entry.
  cache.cache.del(key)

proc clear*[K, V](cache: var TimedMemoCache[K, V]) =
  ## Clear all entries from the cache.
  cache.cache.clear()

proc len*[K, V](cache: TimedMemoCache[K, V]): int =
  ## Return the number of entries in the cache (including potentially expired ones).
  cache.cache.len

proc setMaxAge*[K, V](cache: var TimedMemoCache[K, V], maxAge: float64) =
  ## Change the max age for cache entries.
  cache.maxAge = maxAge

# ---------------------------------------------------------------------------
# Convenience: Frame-scoped memoization
# ---------------------------------------------------------------------------
# For computations that should be cached within a single frame but refreshed
# each frame. Uses a very short maxAge (e.g., 0.02 seconds = 50 FPS frame time).

const
  FrameCacheMaxAge* = 0.02  ## ~50 FPS frame time

proc initFrameCache*[K, V](): TimedMemoCache[K, V] =
  ## Initialize a frame-scoped cache (very short max age).
  ## Use for expensive evaluations that don't change within a frame.
  initTimedMemoCache[K, V](maxAge = FrameCacheMaxAge, cleanupInterval = 1.0)

# ---------------------------------------------------------------------------
# Convenience: Position-based cache key helpers
# ---------------------------------------------------------------------------

import vmath

proc posKey*(x, y: int32): int64 {.inline.} =
  ## Create a cache key from a position.
  (int64(x) shl 32) or int64(y)

proc posKey*(pos: IVec2): int64 {.inline.} =
  ## Create a cache key from an IVec2 position.
  posKey(pos.x, pos.y)

proc agentPosKey*(agentId: int, x, y: int32): int64 {.inline.} =
  ## Create a cache key combining agent ID and position.
  ## Uses high bits for agentId, low bits for position hash.
  (int64(agentId) shl 48) or (int64(x) shl 24) or int64(y)

proc agentPosKey*(agentId: int, pos: IVec2): int64 {.inline.} =
  ## Create a cache key combining agent ID and position.
  agentPosKey(agentId, pos.x, pos.y)

# ---------------------------------------------------------------------------
# Convenience: Typed cache key for composite keys
# ---------------------------------------------------------------------------

type
  CacheKey2*[A, B] = object
    ## Composite cache key for two values.
    a*: A
    b*: B

  CacheKey3*[A, B, C] = object
    ## Composite cache key for three values.
    a*: A
    b*: B
    c*: C

proc cacheKey*[A, B](a: A, b: B): CacheKey2[A, B] {.inline.} =
  CacheKey2[A, B](a: a, b: b)

proc cacheKey*[A, B, C](a: A, b: B, c: C): CacheKey3[A, B, C] {.inline.} =
  CacheKey3[A, B, C](a: a, b: b, c: c)

proc hash*[A, B](k: CacheKey2[A, B]): Hash =
  var h: Hash = 0
  h = h !& hash(k.a)
  h = h !& hash(k.b)
  result = !$h

proc hash*[A, B, C](k: CacheKey3[A, B, C]): Hash =
  var h: Hash = 0
  h = h !& hash(k.a)
  h = h !& hash(k.b)
  h = h !& hash(k.c)
  result = !$h
