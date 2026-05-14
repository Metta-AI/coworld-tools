#!/usr/bin/env bash
# Coborg Among Them player container entrypoint.
#
# Forwards all args to the policy_player module. Logs go to stderr; stdout is
# reserved for the BitWorld WebSocket protocol channel (currently unused —
# the bridge connects out, not in, but we keep the discipline).
set -euo pipefail
exec python -m agent_policies.policies.cyborg.bitworld.coborg_among_them.coworld.policy_player "$@"
