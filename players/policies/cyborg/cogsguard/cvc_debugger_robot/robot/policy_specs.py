"""Canonical policy spec strings for the CVC debugger robot."""

ROBOT_POLICY_CLASS_PATH = (
  "policies.cyborg.cogsguard.cvc_debugger_robot.robot.RobotPolicy"
)
ROBOT_POLICY_SPEC = f"class={ROBOT_POLICY_CLASS_PATH}"
ROBOT_DEBUG_POLICY_SPEC = f"{ROBOT_POLICY_SPEC},kw.debug=true"

