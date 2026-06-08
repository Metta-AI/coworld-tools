# Submitting Under a Specific Player ("Player Swap")

How to upload and submit a Coworld policy as a chosen **player identity** when a
single user account owns more than one player.

This is a self-contained operational guide. It is intended to seed both package
documentation (coworld / softmax) and an agent skill.

## Mental model

- **One user account can own multiple players.** Authentication resolves to a
  *subject*. `whoami` returns `subject_type` (`user` or `player`), `subject_id`,
  and `owner_user_id`. A *user* subject's `subject_id` equals its
  `owner_user_id`; a *player* subject has its own `ply_…` `subject_id` and the
  owning user's `owner_user_id`.
- **A policy version is owned by the player that uploaded it.** `coworld
  upload-policy` stamps the *currently authenticated player* onto the new version
  (`policy_version.player_id`). Policy names and version numbers are shared across
  the whole account; each individual version has its own owning player.
- **A league submission is attributed to the version's owner.** To enter a league
  as player *P*, you must submit a version that *P* owns — which means uploading
  it while authenticated as *P*.
- **`coworld` authenticates from its own credential store.** It does **not** read
  the standalone `softmax` CLI's token store. Swapping players means changing the
  token in *coworld's* store (see [Credential storage](#credential-storage)).

## Prerequisites

- The owning **user** is logged into coworld (a user token is present in
  coworld's credential store — see below). If not, run coworld's bundled
  `softmax login` first.
- A built, loadable policy image (e.g. `players-crewborg:dev`).
- The Python interpreter from **coworld's environment** (the one that can
  `import softmax`). On a uv tool install that is
  `~/.local/share/uv/tools/coworld/bin/python3`. Referred to below as
  `$COWORLD_PY`.

```sh
COWORLD_PY=~/.local/share/uv/tools/coworld/bin/python3
API=https://softmax.com/api/observatory   # ${COGAMES_API_URL:-https://softmax.com/api}/observatory
```

## Procedure

### 1. Find the target player's ID

List the players owned by the account (uses the current user token):

```sh
TOKEN=$("$COWORLD_PY" -c "from softmax import auth; print(auth.load_user_token(server=auth.get_api_server()))")
curl -s -H "Authorization: Bearer $TOKEN" "$API/players" \
  | python3 -c "import sys,json; [print(p['id'], '|', p['name'], '| default=', p.get('is_default')) for p in json.load(sys.stdin)]"
```

Note the `ply_…` ID of the player you want to submit as (call it `$PLAYER_ID`).

### 2. Mint a player-scoped token

A *user* token is required to mint a player token (player tokens cannot mint or
manage players). No request body is needed.

```sh
PLAYER_ID=ply_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
"$COWORLD_PY" - "$PLAYER_ID" <<'PY'
import sys, httpx
from softmax import auth
server = auth.get_api_server()
user_tok = auth.load_user_token(server=server)
r = httpx.post(f"{server.rstrip('/')}/observatory/players/{sys.argv[1]}/login",
               headers={"Authorization": f"Bearer {user_tok}"}, timeout=30.0)
r.raise_for_status()
# Activate it as coworld's player session (this is what makes coworld act as the player):
auth.save_player_session(server=server, token=r.json()["token"])
who = auth.fetch_cogames_whoami(token=auth.load_current_token(server=server))
print("coworld now authenticates as:", who.subject_type, who.subject_id, who.user_email)
PY
```

Confirm the output shows `subject_type: player` and `subject_id` equal to
`$PLAYER_ID`. coworld now acts as that player.

### 3. Upload the image as the player

```sh
coworld upload-policy players-crewborg:dev --name <policy-name> --use-bedrock
# e.g. --name crewbond ; add --secret-env KEY=VAL as needed.
```

The new version is owned by the active player. Note the printed
`<policy-name>:vN`. (Versions increment account-wide; the *owner* of this new
version is the active player.)

### 4. Resolve the new version's ID and submit it as the player

Submit with an explicit `player_id` that matches the version owner. This is the
deterministic path; it guarantees the attribution.

```sh
LEAGUE_ID=league_xxxxxxxx-...
NAME=<policy-name>
TOKEN=$("$COWORLD_PY" -c "from softmax import auth; print(auth.load_current_token(server=auth.get_api_server()))")

VID=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/stats/policy-versions?limit=50" \
  | python3 -c "import sys,json,os
rows=json.load(sys.stdin); rows=rows if isinstance(rows,list) else rows.get('entries',rows.get('items',[]))
m=[r for r in rows if r.get('name')==os.environ['NAME']]; m.sort(key=lambda r:r.get('version',0))
print(m[-1]['id'])" NAME="$NAME")

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"league_id\":\"$LEAGUE_ID\",\"policy_version_id\":\"$VID\",\"player_id\":\"$PLAYER_ID\"}" \
  "$API/v2/league-submissions" | python3 -m json.tool
```

A success response includes `"player": {"name": "<target player>"}` and
`"status": "pending"`.

### 5. Verify

```sh
coworld submissions --mine | grep -i "<target player>"
coworld memberships --mine --league "$LEAGUE_ID" | grep -i "<target player>"
```

The `Player` column must show the target player.

### 6. Restore the default identity

Remove the player session so coworld falls back to the user token (the default
player) for subsequent work:

```sh
"$COWORLD_PY" -c "
from softmax import auth
s=auth.get_api_server(); auth._delete_player_session(server=s)
who=auth.fetch_cogames_whoami(token=auth.load_current_token(server=s))
print('restored to:', who.subject_type, who.user_email)"
```

## Credential storage

coworld reads `~/.softmax/credentials.yaml`:

```yaml
tokens:                              # user tokens, keyed by API server
  https://softmax.com/api: usr_...
player_sessions:                     # active player session, keyed by API server
  https://softmax.com/api: <player-token>
```

`load_current_token(server)` returns `player_sessions[server]` if present, else
`tokens[server]`. Setting a player session (step 2) overrides the active
identity; deleting it (step 6) reverts to the user token.

Server key = `get_api_server()` = `${COGAMES_API_URL:-https://softmax.com/api}`.
All endpoints below are under `<server>/observatory`.

## API reference

| Method & path | Purpose | Notes |
|---|---|---|
| `GET /whoami` | Identity of a token | Returns `subject_type`, `subject_id`, `owner_user_id`. |
| `GET /players` | List the account's players | Each has `id` (`ply_…`), `name`, `is_default`. |
| `POST /players/{player_id}/login` | Mint a player-scoped token | No body. Returns `{player_id, token, expires_at}`. Requires a **user** token. |
| `GET /stats/policy-versions?limit=N` | List policy versions | Resolve `id` from `name` + `version`. |
| `POST /v2/league-submissions` | Submit a version to a league | Body `{league_id, policy_version_id, player_id?}`. `player_id` must equal the version owner; omitted ⇒ account default player. |
| `POST /v2/league-policy-memberships/{lpm_id}/retire` | Retire a membership | Requires a **user** token. Marks the membership inactive/disqualified. |

## Constraints and gotchas

- **coworld and the standalone `softmax` CLI use separate credential stores.**
  Operations with a standalone `softmax` binary (`softmax set-token`,
  `softmax status`) do **not** affect coworld. Always change coworld's own store
  (step 2) and verify with coworld's `whoami` (not `softmax status`). If you use
  `softmax login` to authenticate coworld, use the `softmax` **bundled with
  coworld**, not a separately installed one.
- **Version ownership is fixed at upload time** and cannot be reassigned. To
  submit as a different player, upload a *new* version while authenticated as
  that player.
- **One active membership per (version, league).** Resubmitting the same version
  to the same league is rejected (`policy version … already has an active
  membership`). Upload a fresh version for each entry.
- **`player_id` must match the version owner** on submit
  (`policy version … is already assigned to player …` otherwise).
- **Setting the default player is not required** for a player swap and may be
  unauthorized for the available credentials. Do not rely on
  `POST /players/{id}/default`.
- **Player tokens are least-privilege.** They can upload/submit as their player
  but cannot mint tokens, list/manage players, set the default player, or retire
  memberships — those need a user token.
- **Policy names are account-global.** Reusing an existing policy name appends a
  new (player-owned) version to that shared policy. Use a distinct name if you
  want a visually separate policy per player.

## Cleanup

- Retire an unwanted membership: `POST /v2/league-policy-memberships/{lpm_id}/retire`
  (user token).
- Unsubmitted policy versions are inert (no league effect) and have no delete
  endpoint; they can be left in place.

## Notes for package maintainers

- Consider exposing `--player <id|name>` on `coworld upload-policy` and
  `coworld submit`, resolving and stamping the player without manual token
  juggling.
- Consider a `coworld players` (list) and `coworld use-player` (activate session)
  command pair, so swapping never requires hand-editing the credential store.
- Align (or clearly document) the credential-store divergence between the
  standalone `softmax` CLI and coworld's bundled `softmax`, so `softmax status`
  and coworld's effective identity cannot disagree.
