import std/unittest
import environment
import agent_control
import common
import types
import items
import test_utils
import scripted/ai_types

# =============================================================================
# Test defineBehavior macro - Simple Inverse Case
# =============================================================================

# Define a simple behavior where shouldTerminate is the negation of canStart
defineBehavior("TestSimple"):
  canStart: agent.hp > 50
  act:
    0'u8

suite "defineBehavior - Simple Inverse":
  test "canStart returns true when condition met":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.hp = 60
    var state: AgentState
    var controller: Controller
    check canStartTestSimple(controller, env, agent, 0, state) == true

  test "canStart returns false when condition not met":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.hp = 40
    var state: AgentState
    var controller: Controller
    check canStartTestSimple(controller, env, agent, 0, state) == false

  test "shouldTerminate is inverse of canStart":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.hp = 60
    var state: AgentState
    var controller: Controller
    # When canStart is true, shouldTerminate should be false
    check shouldTerminateTestSimple(controller, env, agent, 0, state) == false
    agent.hp = 40
    # When canStart is false, shouldTerminate should be true
    check shouldTerminateTestSimple(controller, env, agent, 0, state) == true

  test "OptionDef is created correctly":
    check TestSimpleOption.name == "TestSimple"
    check TestSimpleOption.interruptible == true

# =============================================================================
# Test defineBehavior macro - Complex Case (explicit shouldTerminate)
# =============================================================================

# Define a behavior with explicit shouldTerminate (not just negation)
defineBehavior("TestComplex"):
  canStart:
    agent.hp > 50 and agent.inventoryBread > 0
  shouldTerminate:
    agent.hp <= 30 or agent.inventoryBread == 0
  act:
    # Just return noop for this test
    0'u8
  interruptible: false

suite "defineBehavior - Complex Case":
  test "canStart uses provided condition":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.hp = 60
    agent.inventoryBread = 0
    var state: AgentState
    var controller: Controller
    # HP is high but no bread - should not start
    check canStartTestComplex(controller, env, agent, 0, state) == false
    agent.inventoryBread = 1
    # Now both conditions met
    check canStartTestComplex(controller, env, agent, 0, state) == true

  test "shouldTerminate uses explicit condition (not inverse)":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.hp = 40  # Between 30 and 50 - interesting case
    agent.inventoryBread = 1
    var state: AgentState
    var controller: Controller
    # HP=40 is NOT > 50, so canStart would be false
    # But HP=40 is NOT <= 30, and bread > 0, so shouldTerminate would be false
    # This shows that shouldTerminate is not just !canStart
    check canStartTestComplex(controller, env, agent, 0, state) == false
    check shouldTerminateTestComplex(controller, env, agent, 0, state) == false

  test "interruptible flag is set correctly":
    check TestComplexOption.interruptible == false
    check TestComplexOption.name == "TestComplex"

# =============================================================================
# Test defineBehavior macro - With Act Logic
# =============================================================================

var testActCallCount = 0

defineBehavior("TestWithAct"):
  canStart: true
  act:
    inc testActCallCount
    42'u8

suite "defineBehavior - Act Logic":
  test "act procedure is called and returns value":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    var state: AgentState
    var controller: Controller
    testActCallCount = 0
    let result = optTestWithAct(controller, env, agent, 0, state)
    check result == 42'u8
    check testActCallCount == 1

  test "OptionDef act points to correct procedure":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    var state: AgentState
    var controller: Controller
    testActCallCount = 0
    let result = TestWithActOption.act(controller, env, agent, 0, state)
    check result == 42'u8
    check testActCallCount == 1  # Incremented once by OptionDef.act call

# =============================================================================
# Test behaviorGuard template
# =============================================================================

behaviorGuard(TestGuard, canStartTestGuard, shouldTerminateTestGuard,
  agent.inventoryWood > 0,
  block:
    if agent.inventoryWood > 5:
      10'u8
    else:
      5'u8
)

suite "behaviorGuard Template":
  test "canStart uses condition":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryWood = 0
    var state: AgentState
    var controller: Controller
    check canStartTestGuard(controller, env, agent, 0, state) == false
    agent.inventoryWood = 1
    check canStartTestGuard(controller, env, agent, 0, state) == true

  test "shouldTerminate is inverse of condition":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryWood = 1
    var state: AgentState
    var controller: Controller
    check shouldTerminateTestGuard(controller, env, agent, 0, state) == false
    agent.inventoryWood = 0
    check shouldTerminateTestGuard(controller, env, agent, 0, state) == true

  test "act procedure works":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryWood = 3
    var state: AgentState
    var controller: Controller
    check optTestGuard(controller, env, agent, 0, state) == 5'u8
    agent.inventoryWood = 10
    check optTestGuard(controller, env, agent, 0, state) == 10'u8

  test "OptionDef is created":
    check TestGuardOption.name == "TestGuard"
    check TestGuardOption.interruptible == true
