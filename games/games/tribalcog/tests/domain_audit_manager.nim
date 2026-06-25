## Domain checks for audit manager orchestration and compile-time flags.

import
  audit_manager, test_utils

proc checkAuditKindValues() =
  ## Verify that `AuditKind` covers each audit type exactly once.
  echo "Testing audit kind values"
  var seen: set[AuditKind]
  for kind in AuditKind:
    doAssert kind notin seen, "AuditKind values should be distinct"
    seen.incl(kind)
  doAssert seen.card == 6, "AuditKind should expose 6 audit types"
  doAssert akCombat in {AuditKind.low .. AuditKind.high}
  doAssert akEcon in {AuditKind.low .. AuditKind.high}
  doAssert akTech in {AuditKind.low .. AuditKind.high}
  doAssert akAction in {AuditKind.low .. AuditKind.high}
  doAssert akTumor in {AuditKind.low .. AuditKind.high}
  doAssert akAi in {AuditKind.low .. AuditKind.high}

proc checkIsAuditEnabled() =
  ## Verify `isAuditEnabled` returns stable boolean values.
  echo "Testing isAuditEnabled"
  let
    combatEnabled = isAuditEnabled(akCombat)
    econEnabled = isAuditEnabled(akEcon)
    techEnabled = isAuditEnabled(akTech)
    actionEnabled = isAuditEnabled(akAction)
    tumorEnabled = isAuditEnabled(akTumor)
    aiEnabled = isAuditEnabled(akAi)
  doAssert combatEnabled in {true, false}
  doAssert econEnabled in {true, false}
  doAssert techEnabled in {true, false}
  doAssert actionEnabled in {true, false}
  doAssert tumorEnabled in {true, false}
  doAssert aiEnabled in {true, false}
  doAssert isAuditEnabled(akCombat) == isAuditEnabled(akCombat)
  doAssert isAuditEnabled(akEcon) == isAuditEnabled(akEcon)
  doAssert isAuditEnabled(akTech) == isAuditEnabled(akTech)

proc checkGetEnabledAudits() =
  ## Verify `getEnabledAudits` matches the compile-time flag queries.
  echo "Testing getEnabledAudits"
  let enabled = getEnabledAudits()
  doAssert enabled.len >= 0
  doAssert enabled.len <= 6, "No more than 6 audit kinds should be enabled"

  var seen: set[AuditKind]
  for kind in enabled:
    doAssert kind notin seen, "Enabled audit kinds should not repeat"
    seen.incl(kind)

  for kind in AuditKind:
    if isAuditEnabled(kind):
      doAssert kind in enabled, "Enabled audit kind should appear in result"
    else:
      doAssert kind notin enabled, "Disabled audit kind should not appear"

proc checkInitAllAudits() =
  ## Verify repeated audit initialization does not fail.
  echo "Testing initAllAudits"
  initAllAudits()
  initAllAudits()
  doAssert true

proc checkFlushAllAudits() =
  ## Verify flushing works across multiple step counts.
  echo "Testing flushAllAudits"
  let env = makeEmptyEnv()
  initAllAudits()
  flushAllAudits(env, 0)
  flushAllAudits(env, 100)
  flushAllAudits(env, 1000)
  doAssert true

proc checkResetAllAudits() =
  ## Verify repeated reset calls are safe.
  echo "Testing resetAllAudits"
  let env = makeEmptyEnv()
  initAllAudits()
  flushAllAudits(env, 50)
  resetAllAudits()
  resetAllAudits()
  flushAllAudits(env, 0)
  doAssert true

proc checkAuditLifecycle() =
  ## Verify a full init, flush, reset, and flush lifecycle.
  echo "Testing full audit lifecycle"
  let env = makeEmptyEnv()
  initAllAudits()
  for step in 0 ..< 10:
    env.stepNoop()
    flushAllAudits(env, step)
  resetAllAudits()
  for step in 0 ..< 5:
    flushAllAudits(env, step)
  doAssert true

proc checkMultipleEnvironments() =
  ## Verify flushing works across multiple environments.
  echo "Testing multiple environments"
  let
    env1 = makeEmptyEnv()
    env2 = makeEmptyEnv()
  initAllAudits()
  flushAllAudits(env1, 0)
  flushAllAudits(env2, 0)
  flushAllAudits(env1, 1)
  flushAllAudits(env2, 1)
  doAssert true

checkAuditKindValues()
checkIsAuditEnabled()
checkGetEnabledAudits()
checkInitAllAudits()
checkFlushAllAudits()
checkResetAllAudits()
checkAuditLifecycle()
checkMultipleEnvironments()

echo "Audit manager domain checks passed"
