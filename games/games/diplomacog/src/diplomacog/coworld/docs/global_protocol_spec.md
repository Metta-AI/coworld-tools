# diplomacog Global Protocol

Viewers connect to `/global`. The websocket streams JSON `state` messages with `protocol: coworld.global.v1`, current step, scores, connected slots, and latest actions. Viewers may send simple control messages such as `pause`, `resume`, or `speed`; the endpoint is safe for late viewers. Replay viewing uses `/client/replay` and `/replay`.
