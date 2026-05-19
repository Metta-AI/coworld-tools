## Domain checks for shared replay serialization helpers.

import
  std/json,
  replay_common

proc checkSerializeChanges() =
  ## Verify serialization of replay change series.
  echo "Testing replay common serializeChanges"

  let changes: ChangeSeries = @[
    (step: 0, value: newJInt(10)),
    (step: 5, value: newJInt(20)),
    (step: 10, value: newJInt(30))
  ]
  let serialized = serializeChanges(changes)
  doAssert serialized.kind == JArray
  doAssert serialized.len == 3
  doAssert serialized[0][0].getInt() == 0
  doAssert serialized[0][1].getInt() == 10
  doAssert serialized[1][0].getInt() == 5
  doAssert serialized[1][1].getInt() == 20
  doAssert serialized[2][0].getInt() == 10
  doAssert serialized[2][1].getInt() == 30

  let emptyChanges: ChangeSeries = @[]
  let emptySerialized = serializeChanges(emptyChanges)
  doAssert emptySerialized.kind == JArray
  doAssert emptySerialized.len == 0

  let singleChanges: ChangeSeries = @[
    (step: 42, value: newJString("hello"))
  ]
  let singleSerialized = serializeChanges(singleChanges)
  doAssert singleSerialized.len == 1
  doAssert singleSerialized[0][0].getInt() == 42
  doAssert singleSerialized[0][1].getStr() == "hello"

  let typedChanges: ChangeSeries = @[
    (step: 0, value: newJBool(true)),
    (step: 1, value: newJFloat(3.14)),
    (step: 2, value: newJNull()),
    (step: 3, value: newJString("test"))
  ]
  let typedSerialized = serializeChanges(typedChanges)
  doAssert typedSerialized[0][1].kind == JBool
  doAssert typedSerialized[1][1].kind == JFloat
  doAssert typedSerialized[2][1].kind == JNull
  doAssert typedSerialized[3][1].kind == JString

proc checkParseChanges() =
  ## Verify parsing of replay change series.
  echo "Testing replay common parseChanges"

  let original: ChangeSeries = @[
    (step: 0, value: newJInt(100)),
    (step: 10, value: newJInt(200)),
    (step: 20, value: newJInt(300))
  ]
  let
    serialized = serializeChanges(original)
    parsed = parseChanges(serialized)
  doAssert parsed.len == original.len
  for idx in 0 ..< parsed.len:
    doAssert parsed[idx].step == original[idx].step
    doAssert parsed[idx].value == original[idx].value

  let emptyParsed = parseChanges(newJArray())
  doAssert emptyParsed.len == 0

  let nilParsed = parseChanges(nil)
  doAssert nilParsed.len == 0

  let objectParsed = parseChanges(newJObject())
  doAssert objectParsed.len == 0

  var malformed = newJArray()
  var valid = newJArray()
  valid.add(newJInt(5))
  valid.add(newJString("ok"))
  malformed.add(valid)
  var bad = newJArray()
  bad.add(newJInt(10))
  malformed.add(bad)
  var validTwo = newJArray()
  validTwo.add(newJInt(15))
  validTwo.add(newJInt(99))
  malformed.add(validTwo)

  let malformedParsed = parseChanges(malformed)
  doAssert malformedParsed.len == 2
  doAssert malformedParsed[0].step == 5
  doAssert malformedParsed[0].value.getStr() == "ok"
  doAssert malformedParsed[1].step == 15
  doAssert malformedParsed[1].value.getInt() == 99

  var mixed = newJArray()
  mixed.add(newJInt(42))
  var validBool = newJArray()
  validBool.add(newJInt(0))
  validBool.add(newJBool(true))
  mixed.add(validBool)

  let mixedParsed = parseChanges(mixed)
  doAssert mixedParsed.len == 1
  doAssert mixedParsed[0].step == 0
  doAssert mixedParsed[0].value.getBool()

proc checkLastChangeValue() =
  ## Verify lookup of the last value in a change series.
  echo "Testing replay common lastChangeValue"

  var series = newJArray()
  var firstEntry = newJArray()
  firstEntry.add(newJInt(0))
  firstEntry.add(newJString("first"))
  series.add(firstEntry)
  var secondEntry = newJArray()
  secondEntry.add(newJInt(5))
  secondEntry.add(newJString("second"))
  series.add(secondEntry)
  var lastEntry = newJArray()
  lastEntry.add(newJInt(10))
  lastEntry.add(newJString("last"))
  series.add(lastEntry)

  let lastValue = lastChangeValue(series)
  doAssert lastValue.getStr() == "last"

  let emptyValue = lastChangeValue(newJArray())
  doAssert emptyValue.kind == JNull

  let nilValue = lastChangeValue(nil)
  doAssert nilValue.kind == JNull

  var singleSeries = newJArray()
  var singleEntry = newJArray()
  singleEntry.add(newJInt(0))
  singleEntry.add(newJInt(42))
  singleSeries.add(singleEntry)
  let singleValue = lastChangeValue(singleSeries)
  doAssert singleValue.getInt() == 42

  var arraySeries = newJArray()
  var arrayEntry = newJArray()
  arrayEntry.add(newJInt(0))
  var pos = newJArray()
  pos.add(newJInt(10))
  pos.add(newJInt(20))
  arrayEntry.add(pos)
  arraySeries.add(arrayEntry)
  let arrayValue = lastChangeValue(arraySeries)
  doAssert arrayValue.kind == JArray
  doAssert arrayValue[0].getInt() == 10
  doAssert arrayValue[1].getInt() == 20

proc checkConstants() =
  ## Verify replay constants stay sane.
  echo "Testing replay common constants"
  doAssert ReplayVersion > 0, "ReplayVersion should be positive"

checkSerializeChanges()
checkParseChanges()
checkLastChangeValue()
checkConstants()

echo "Replay common domain checks passed"
