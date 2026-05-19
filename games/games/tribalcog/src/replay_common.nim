## Shared replay serialization helpers.
## These helpers are used by replay writing and replay analysis.

import
  std/[json]

const
  ReplayVersion* = 3
    ## Current replay file format version.

type
  ChangeSeries* = seq[tuple[step: int, value: JsonNode]]

proc serializeChanges*(changes: ChangeSeries): JsonNode =
  ## Serializes a change list to `[[step, value], ...]` JSON.
  result = newJArray()
  for change in changes:
    var pair = newJArray()
    pair.add(newJInt(change.step))
    pair.add(change.value)
    result.add(pair)

proc parseChanges*(series: JsonNode): ChangeSeries =
  ## Parses `[[step, value], ...]` JSON into a change list.
  if series.isNil or series.kind != JArray:
    return @[]
  result = newSeqOfCap[(int, JsonNode)](series.len)
  for entry in series.items:
    if entry.kind == JArray and entry.len >= 2:
      let step = entry[0].getInt()
      result.add((step: step, value: entry[1]))

proc lastChangeValue*(series: JsonNode): JsonNode =
  ## Returns the last recorded value from a change series.
  if series.isNil or series.kind != JArray or series.len == 0:
    return newJNull()
  let last = series[series.len - 1]
  if last.kind == JArray and last.len >= 2:
    return last[1]
  newJNull()
