# amongcogs Player Protocol

Players connect to `/player?slot=<slot>&token=<token>`. The server sends `player_config`, then `observation` messages using `coworld.player.v1`. Players reply with `action` messages containing either `action_name` or `action_index` and `request_id` set to `step-<step>`. Invalid slot/token pairs are rejected during the websocket handshake.
