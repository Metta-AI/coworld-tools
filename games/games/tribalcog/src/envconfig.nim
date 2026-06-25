## Parse environment configuration values with typed errors and fallbacks.

import
  std/[os, strutils, tables]

const
  EnvConfigDebug* = false
    ## Enables debug logging for environment parsing.
  EmptyEnvValue = ""

type
  EnvConfigError* = object of CatchableError
    ## Environment parsing failure.

proc displayEnvValue(raw: string): string =
  ## Returns a readable representation for one raw environment value.
  if raw.len == 0:
    "<empty>"
  else:
    raw

proc raiseEnvConfigError(
  envVar: string,
  raw: string,
  expected: string
) {.noreturn.} =
  ## Raises an `EnvConfigError` for an invalid environment value.
  let value = displayEnvValue(raw)
  raise newException(
    EnvConfigError,
    "Failed to parse " & envVar & "='" & value & "' as " & expected & ".",
  )

proc logEnvConfigFallback(
  envVar: string,
  raw: string,
  expected: string,
  fallback: string
) =
  ## Logs a fallback when debug output is enabled.
  when EnvConfigDebug:
    let value = displayEnvValue(raw)
    echo "[envconfig] Failed to parse ", envVar, "='", value, "' as ",
      expected, ", using fallback=", fallback

proc parseIntValue(envVar: string, raw: string): int =
  ## Parses one integer environment value or raises `EnvConfigError`.
  try:
    parseInt(raw)
  except ValueError:
    raiseEnvConfigError(envVar, raw, "int")

proc parseBoolValue(envVar: string, raw: string): bool =
  ## Parses one boolean environment value or raises `EnvConfigError`.
  let normalized = raw.toLowerAscii()
  case normalized
  of "1", "true", "yes", "on":
    true
  of "0", "false", "no", "off":
    false
  else:
    raiseEnvConfigError(envVar, raw, "bool")

proc parseFloatValue(envVar: string, raw: string): float =
  ## Parses one float environment value or raises `EnvConfigError`.
  try:
    parseFloat(raw)
  except ValueError:
    raiseEnvConfigError(envVar, raw, "float")

proc parseEnvInt*(envVar: string, fallback: int): int =
  ## Parses an integer environment variable with fallback behavior.
  let raw = getEnv(envVar, EmptyEnvValue)
  if raw.len == 0:
    return fallback
  try:
    parseIntValue(envVar, raw)
  except EnvConfigError:
    logEnvConfigFallback(envVar, raw, "int", $fallback)
    fallback

proc parseEnvBool*(envVar: string, fallback: bool): bool =
  ## Parses a boolean environment variable with fallback behavior.
  let raw = getEnv(envVar, EmptyEnvValue)
  if raw.len == 0:
    return fallback
  try:
    parseBoolValue(envVar, raw)
  except EnvConfigError:
    logEnvConfigFallback(envVar, raw, "bool", $fallback)
    fallback

proc parseEnvFloat*(envVar: string, fallback: float): float =
  ## Parses a float environment variable with fallback behavior.
  let raw = getEnv(envVar, EmptyEnvValue)
  if raw.len == 0:
    return fallback
  try:
    parseFloatValue(envVar, raw)
  except EnvConfigError:
    logEnvConfigFallback(envVar, raw, "float", $fallback)
    fallback

proc parseEnvString*(envVar: string, fallback: string): string =
  ## Parses a string environment variable with fallback behavior.
  let raw = getEnv(envVar, EmptyEnvValue)
  if raw.len == 0:
    return fallback
  raw

proc initStringIntTable*(capacity: int = 16): Table[string, int] =
  ## Initializes a string-to-int table with the requested capacity.
  initTable[string, int](capacity)
