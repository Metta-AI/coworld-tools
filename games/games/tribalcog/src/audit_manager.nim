## Centralized orchestration for the optional audit subsystems.

import types

when defined(combatAudit):
  import combat_audit as ca

when defined(econAudit):
  import econ_audit as ea

when defined(techAudit):
  import tech_audit as ta

when defined(actionAudit):
  import action_audit as aa

when defined(tumorAudit):
  import tumor_audit as tua

when defined(aiAudit):
  import scripted/ai_audit as aia

type
  AuditKind* = enum
    akCombat
    akEcon
    akTech
    akAction
    akTumor
    akAi

proc isAuditEnabled*(kind: AuditKind): bool =
  ## Return whether one audit kind is compiled into this build.
  case kind
  of akCombat:
    when defined(combatAudit):
      true
    else:
      false
  of akEcon:
    when defined(econAudit):
      true
    else:
      false
  of akTech:
    when defined(techAudit):
      true
    else:
      false
  of akAction:
    when defined(actionAudit):
      true
    else:
      false
  of akTumor:
    when defined(tumorAudit):
      true
    else:
      false
  of akAi:
    when defined(aiAudit):
      true
    else:
      false

proc addEnabledAudit(enabled: var seq[AuditKind], kind: AuditKind) =
  ## Appends one audit kind when it is compiled into the binary.
  if isAuditEnabled(kind):
    enabled.add(kind)

proc getEnabledAudits*(): seq[AuditKind] =
  ## Return all audit kinds compiled into this build.
  result = @[]
  for kind in AuditKind:
    addEnabledAudit(result, kind)

proc initAllAudits*() =
  ## Initialize every enabled audit subsystem.
  when defined(combatAudit):
    ca.initCombatAudit()
  when defined(econAudit):
    ea.initEconAudit()
  when defined(techAudit):
    ta.initTechAudit()
  when defined(actionAudit):
    aa.initActionAudit()
  when defined(tumorAudit):
    tua.initTumorAudit()
  when defined(aiAudit):
    aia.initAuditLog()

proc flushAllAudits*(env: Environment, step: int) =
  ## Flush or print reports for every enabled audit subsystem.
  when defined(combatAudit):
    ca.printCombatReport(step)
  when defined(tumorAudit):
    tua.printTumorReport(env)
  when defined(actionAudit):
    aa.printActionAuditReport(step)
  when defined(techAudit):
    ta.maybePrintTechSummary(env, step)
  when defined(econAudit):
    ea.maybePrintEconDashboard(env, step)
  when defined(aiAudit):
    aia.printAuditSummary(step)

proc resetAllAudits*() =
  ## Reset the audit subsystems that expose explicit reset procedures.
  when defined(econAudit):
    ea.resetEconAudit()
  when defined(techAudit):
    ta.resetTechAudit()
  discard
