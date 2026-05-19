import std/[unittest, os]
import scripted/memoization
import common_types
import vmath

# =============================================================================
# TimedMemoCache Basic Operations
# =============================================================================

suite "TimedMemoCache - Initialization":
  test "creates empty cache":
    var cache = initTimedMemoCache[int, string]()
    check cache.len == 0

  test "respects custom maxAge":
    var cache = initTimedMemoCache[int, string](maxAge = 2.0)
    # Should work without error
    check cache.len == 0

  test "respects custom cleanupInterval":
    var cache = initTimedMemoCache[int, string](cleanupInterval = 10.0)
    check cache.len == 0

suite "TimedMemoCache - Get Operations":
  test "computes value on first access":
    var cache = initTimedMemoCache[int, int]()
    var computeCount = 0

    let result = cache.get(1, proc(): int =
      computeCount += 1
      42
    )

    check result == 42
    check computeCount == 1
    check cache.len == 1

  test "returns cached value on second access":
    var cache = initTimedMemoCache[int, int](maxAge = 10.0)  # Long maxAge
    var computeCount = 0

    discard cache.get(1, proc(): int =
      computeCount += 1
      42
    )

    let result = cache.get(1, proc(): int =
      computeCount += 1
      99
    )

    check result == 42  # Returns cached, not recomputed
    check computeCount == 1

  test "different keys compute independently":
    var cache = initTimedMemoCache[int, int]()

    let r1 = cache.get(1, proc(): int = 10)
    let r2 = cache.get(2, proc(): int = 20)
    let r3 = cache.get(3, proc(): int = 30)

    check r1 == 10
    check r2 == 20
    check r3 == 30
    check cache.len == 3

  test "recomputes after expiry":
    var cache = initTimedMemoCache[int, int](maxAge = 0.01)  # 10ms
    var computeCount = 0

    discard cache.get(1, proc(): int =
      computeCount += 1
      42
    )

    # Wait for expiry
    sleep(20)  # 20ms > 10ms maxAge

    let result = cache.get(1, proc(): int =
      computeCount += 1
      99
    )

    check result == 99  # Recomputed because expired
    check computeCount == 2

suite "TimedMemoCache - getWithArg":
  test "passes argument to compute function":
    var cache = initTimedMemoCache[int, int]()

    let result = cache.getWithArg(1, 5, proc(x: int): int = x * 2)
    check result == 10

  test "caches result keyed by first arg":
    var cache = initTimedMemoCache[int, int](maxAge = 10.0)
    var computeCount = 0

    discard cache.getWithArg(1, 5, proc(x: int): int =
      computeCount += 1
      x * 2
    )

    # Same key should use cached value
    let result = cache.getWithArg(1, 99, proc(x: int): int =
      computeCount += 1
      x * 3
    )

    check result == 10  # Cached value, not recomputed
    check computeCount == 1

suite "TimedMemoCache - getWith2Args":
  test "passes both arguments to compute function":
    var cache = initTimedMemoCache[int, int]()

    let result = cache.getWith2Args(1, 3, 4, proc(a, b: int): int = a + b)
    check result == 7

  test "caches result keyed by first arg":
    var cache = initTimedMemoCache[int, int](maxAge = 10.0)
    var computeCount = 0

    discard cache.getWith2Args(1, 3, 4, proc(a, b: int): int =
      computeCount += 1
      a + b
    )

    let result = cache.getWith2Args(1, 99, 99, proc(a, b: int): int =
      computeCount += 1
      a * b
    )

    check result == 7  # Cached
    check computeCount == 1

suite "TimedMemoCache - Manual Operations":
  test "invalidate removes specific entry":
    var cache = initTimedMemoCache[int, int](maxAge = 10.0)

    discard cache.get(1, proc(): int = 10)
    discard cache.get(2, proc(): int = 20)
    check cache.len == 2

    cache.invalidate(1)
    check cache.len == 1

    var computeCount = 0
    let result = cache.get(1, proc(): int =
      computeCount += 1
      99
    )

    check result == 99  # Recomputed after invalidation
    check computeCount == 1

  test "clear removes all entries":
    var cache = initTimedMemoCache[int, int]()

    discard cache.get(1, proc(): int = 10)
    discard cache.get(2, proc(): int = 20)
    discard cache.get(3, proc(): int = 30)
    check cache.len == 3

    cache.clear()
    check cache.len == 0

  test "setMaxAge changes expiry threshold":
    var cache = initTimedMemoCache[int, int](maxAge = 10.0)

    discard cache.get(1, proc(): int = 42)

    cache.setMaxAge(0.001)  # 1ms

    sleep(10)

    var computeCount = 0
    let result = cache.get(1, proc(): int =
      computeCount += 1
      99
    )

    check result == 99  # Recomputed due to new short maxAge
    check computeCount == 1

suite "TimedMemoCache - Cleanup":
  test "cleanup removes expired entries":
    var cache = initTimedMemoCache[int, int](maxAge = 0.01, cleanupInterval = 0.001)

    discard cache.get(1, proc(): int = 10)
    discard cache.get(2, proc(): int = 20)
    check cache.len == 2

    sleep(20)

    cache.cleanup()
    check cache.len == 0

  test "cleanup keeps fresh entries":
    var cache = initTimedMemoCache[int, int](maxAge = 10.0, cleanupInterval = 0.001)

    discard cache.get(1, proc(): int = 10)
    discard cache.get(2, proc(): int = 20)

    cache.cleanup()
    check cache.len == 2  # Both still fresh

# =============================================================================
# Frame Cache
# =============================================================================

suite "Frame Cache":
  test "initFrameCache creates cache with short maxAge":
    var cache = initFrameCache[int, int]()
    check cache.len == 0

  test "frame cache expires quickly":
    var cache = initFrameCache[int, int]()
    var computeCount = 0

    discard cache.get(1, proc(): int =
      computeCount += 1
      42
    )

    sleep(30)  # 30ms > FrameCacheMaxAge (20ms)

    let result = cache.get(1, proc(): int =
      computeCount += 1
      99
    )

    check result == 99
    check computeCount == 2

# =============================================================================
# Position Key Helpers
# =============================================================================

suite "Position Key Helpers":
  test "posKey from coordinates":
    let key1 = posKey(10'i32, 20'i32)
    let key2 = posKey(10'i32, 20'i32)
    let key3 = posKey(11'i32, 20'i32)

    check key1 == key2
    check key1 != key3

  test "posKey from IVec2":
    let pos = ivec2(15, 25)
    let key = posKey(pos)
    check key == posKey(15'i32, 25'i32)

  test "agentPosKey combines agent and position":
    let key1 = agentPosKey(5, 10'i32, 20'i32)
    let key2 = agentPosKey(5, 10'i32, 20'i32)
    let key3 = agentPosKey(6, 10'i32, 20'i32)  # Different agent

    check key1 == key2
    check key1 != key3

  test "agentPosKey from IVec2":
    let pos = ivec2(10, 20)
    let key = agentPosKey(5, pos)
    check key == agentPosKey(5, 10'i32, 20'i32)

# =============================================================================
# Composite Cache Keys
# =============================================================================

suite "Composite Cache Keys":
  test "CacheKey2 equality":
    let k1 = cacheKey(1, "hello")
    let k2 = cacheKey(1, "hello")
    let k3 = cacheKey(2, "hello")
    let k4 = cacheKey(1, "world")

    check k1 == k2
    check k1 != k3
    check k1 != k4

  test "CacheKey2 as table key":
    var cache = initTimedMemoCache[CacheKey2[int, int], string]()

    let result = cache.get(cacheKey(1, 2), proc(): string = "value")
    check result == "value"

    let cached = cache.get(cacheKey(1, 2), proc(): string = "other")
    check cached == "value"  # Still cached

  test "CacheKey3 equality":
    let k1 = cacheKey(1, 2, 3)
    let k2 = cacheKey(1, 2, 3)
    let k3 = cacheKey(1, 2, 4)

    check k1 == k2
    check k1 != k3

  test "CacheKey3 as table key":
    var cache = initTimedMemoCache[CacheKey3[int, int, int], float]()

    let result = cache.get(cacheKey(1, 2, 3), proc(): float = 3.14)
    check result == 3.14

# =============================================================================
# Type Variety
# =============================================================================

suite "TimedMemoCache - Various Types":
  test "string keys and values":
    var cache = initTimedMemoCache[string, string]()
    let result = cache.get("hello", proc(): string = "world")
    check result == "world"

  test "float values":
    var cache = initTimedMemoCache[int, float]()
    let result = cache.get(1, proc(): float = 3.14159)
    check abs(result - 3.14159) < 0.0001

  test "seq values":
    var cache = initTimedMemoCache[int, seq[int]]()
    let result = cache.get(1, proc(): seq[int] = @[1, 2, 3, 4, 5])
    check result == @[1, 2, 3, 4, 5]

  test "tuple keys":
    var cache = initTimedMemoCache[(int, int), int]()
    let result = cache.get((5, 10), proc(): int = 50)
    check result == 50

# =============================================================================
# Edge Cases
# =============================================================================

suite "TimedMemoCache - Edge Cases":
  test "zero maxAge always recomputes":
    var cache = initTimedMemoCache[int, int](maxAge = 0.0)
    var computeCount = 0

    discard cache.get(1, proc(): int =
      computeCount += 1
      42
    )

    let result = cache.get(1, proc(): int =
      computeCount += 1
      99
    )

    # With 0 maxAge, should always recompute
    check result == 99
    check computeCount == 2

  test "negative key works":
    var cache = initTimedMemoCache[int, int]()
    let result = cache.get(-100, proc(): int = 42)
    check result == 42

  test "large number of entries":
    var cache = initTimedMemoCache[int, int](maxAge = 10.0)

    for i in 0 ..< 1000:
      discard cache.get(i, proc(): int = i * 2)

    check cache.len == 1000

    # Verify some cached values
    var computeCount = 0
    let r500 = cache.get(500, proc(): int =
      computeCount += 1
      0
    )
    check r500 == 1000  # 500 * 2
    check computeCount == 0  # Used cache
