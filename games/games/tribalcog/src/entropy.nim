## Minimal deterministic RNG used across the project.
## Avoids std/random so wasm builds do not depend on sysrand.

const
  DefaultSeed* = 0x9E3779B97F4A7C15'u64
  RandFloatFactor = 1.0 / float64(1'u64 shl 53)

type
  Rand* = object
    state: uint64

proc initRand*(seed: int): Rand =
  ## Initialize a deterministic RNG from the supplied seed.
  let seedValue = if seed == 0: DefaultSeed else: uint64(seed)
  result.state = seedValue

proc next*(r: var Rand): uint64 =
  ## Advance the RNG and return the next raw value.
  var x = r.state
  x = x xor (x shl 13)
  x = x xor (x shr 7)
  x = x xor (x shl 17)
  r.state = x
  r.state

proc randIntInclusive*(r: var Rand, a, b: int): int =
  ## Return a random integer in the inclusive range [`a`, `b`].
  if a >= b:
    return a
  let range = uint64(b - a + 1)
  a + int(next(r) mod range)

proc randIntExclusive*(r: var Rand, a, b: int): int =
  ## Return a random integer in the half-open range [`a`, `b`).
  if a >= b:
    return a
  let range = uint64(b - a)
  a + int(next(r) mod range)

proc randFloat*(r: var Rand): float64 =
  ## Return a random float in the range [0.0, 1.0).
  float64(next(r) shr 11) * RandFloatFactor

proc randChance*(r: var Rand, probability: float): bool =
  ## Return true when a probability check succeeds.
  if probability <= 0:
    return false
  if probability >= 1:
    return true
  randFloat(r) < probability

proc sample*[T](
  r: var Rand,
  items: openArray[T]
): T {.raises: [ValueError].} =
  ## Return one random item from a non-empty collection.
  if items.len == 0:
    raise newException(ValueError, "Cannot sample from empty sequence")
  items[randIntExclusive(r, 0, items.len)]

proc shuffle*[T](r: var Rand, items: var openArray[T]) =
  ## Fisher-Yates shuffle: randomizes array order in-place.
  if items.len < 2:
    return
  var i = items.high
  while i > 0:
    let j = randIntInclusive(r, 0, i)
    swap(items[i], items[j])
    dec i
