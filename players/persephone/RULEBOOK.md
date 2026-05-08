# Persephone's Escape -- Rulebook

A digital implementation of **Two Rooms and a Boom**, re-themed around the
Greek myth of Persephone. Built on the bitworld engine (128x128 4-bit pixel
protocol). Source lives at `~/coding/bitworld/persephones_escape/`.

---

## Overview

Two teams -- **Shades** and **Nymphs** -- are split across two disjoint rooms.
Over three timed rounds, players communicate in private whispers and global
room chat to discover identities and form alliances. Between rounds, room
leaders select hostages to swap between rooms, meeting briefly in a private
summit before the exchange. After the final round, the game checks whether
each team's key roles fulfilled their win condition.

---

## Teams and Roles

There are two teams and eleven possible roles (six core + five auxiliary).

### Core Roles

| Role | Team | Key? | Description |
|------|------|------|-------------|
| **Hades** | Shades | Yes | Wants to end the game in the **same room** as Persephone |
| **Cerberus** | Shades | Yes | Hades must perform a **mutual role exchange** with Cerberus for Shades to win |
| **Shade** (grunt) | Shades | No | No special ability; wins with team |
| **Persephone** | Nymphs | Yes | Wants to end the game in a **different room** from Hades |
| **Demeter** | Nymphs | Yes | Persephone must perform a **mutual role exchange** with Demeter for Nymphs to win |
| **Nymph** (grunt) | Nymphs | No | No special ability; wins with team |

### Auxiliary Roles

| Role | Team | Description |
|------|------|-------------|
| **Spy** | Either | Color/role reveals show the **opposite** team. Only mutual role exchange (`sharedWith`) reveals truth. |
| **Echo of Hades** | Shades | Substitutes for Hades if Hades is absent from the config |
| **Echo of Persephone** | Nymphs | Substitutes for Persephone if Persephone is absent |
| **Echo of Cerberus** | Shades | Substitutes for Cerberus if Cerberus is absent |
| **Echo of Demeter** | Nymphs | Substitutes for Demeter if Demeter is absent |

"Key role" means the role is directly referenced in the win condition.
Grunts have no special mechanics but share their team's fate. Echo roles
activate only when their corresponding core role is not in the match config;
they fulfill the same win-condition slot as the core role they replace.

### Default Composition (10 players)

| Role | Count |
|------|-------|
| Hades | 1 |
| Persephone | 1 |
| Cerberus | 1 |
| Demeter | 1 |
| Shade (grunt) | 3 |
| Nymph (grunt) | 3 |

Minimum 6 players required. The composition is configurable via
`GameConfig.roles`.

---

## Rooms

Two completely disjoint rooms:

| Room | Internal Name | Floor Color (palette index) |
|------|---------------|-----------------------------|
| **Underworld** | RoomA | Dark blue (12) |
| **Mortal Realm** | RoomB | Dark purple (9) |

Rooms are separate coordinate spaces with no physical connection. Players
can only move between rooms via hostage exchange. Room size scales with
player count:

| Players | Room Size | Obstacles/Room |
|---------|-----------|----------------|
| 6--8 | 100x100 | 4 |
| 9--11 | 120x120 | 5 |
| 12--14 | 140x140 | 7 |
| 15--17 | 160x160 | 9 |
| 18--20 | 180x180 | 11 |
| 21--24 | 200x200 | 14 |

Obstacles are randomly placed square blocks (8x8 pixels) that block
movement and line of sight. Rooms have fog of war via raycasting from the
player's position.

---

## Game Flow

```
Lobby -> RosterReveal -> RoleReveal -> [Playing -> HostageSelect -> LeaderSummit -> HostageExchange] x3 -> Reveal -> GameOver
```

### Lobby

- Players connect and are added to the game
- Once the required player count is reached, a 1-second countdown starts
- No actions available; players can see each other in a shared view

### Roster Reveal (part of 15-second intro sequence)

The intro sequence consists of 4 panels displayed over 15 seconds total.
Players navigate forward (A or Right) and back (B or Left). The game
advances phases as the panels change:

**Panel 0 -- Roster Reveal** (phase = `RosterReveal`):
- Shows the player roster split by room (two columns: Underworld / Mortal Realm)
- Each player's sprite and character name are listed under their room

### Role Reveal (panels 1--3 of intro, phase = `RoleReveal`)

**Panel 1 -- Your Role Card**:
- Bordered intro screen in your team color showing:
  - Your role and team
  - Your assigned room
  - Player count and room dimensions
  - Control reference

**Panel 2 -- Role Summary**:
- Lists all roles present in the match
- Shows missing core roles and active Echo substitutions

**Panel 3 -- Round Schedule**:
- Table showing round count, duration, and hostage count per round
- Players on this panel can press forward to mark themselves "ready"
- If all players are ready (or the 15-second timer expires), the first
  round begins

Players are shuffled randomly across rooms (roughly equal split).
One leader per room is randomly assigned.

### Playing Phase (configurable per round; default 15 seconds, 3 rounds)

- Free movement within your room using directional input
- Movement uses momentum-based physics (acceleration, friction, collision
  sliding)
- Players can:
  - **Create private whispers** (press A/J near open space)
  - **Request entry** to existing whispers (press B/K near a whisper player)
  - **Open global room chat** (press Select/L)
  - **View known players** (cycle to info surface via Left/Right while in
    shout or whisper view)
- Fog of war hides players behind walls and obstacles
- 20x20 minimap in the top-right shows visible players as colored dots

### Hostage Select (15 seconds)

- Each room's leader selects hostages to send to the other room
- Default: 1 hostage per room per round (configurable per round)
- Leaders use left/right to cursor through eligible players, A/J to toggle
  selection, B/K to commit
- **Leaders cannot be selected as hostages**
- If the leader doesn't commit before the timer expires, remaining slots
  are auto-filled randomly from eligible players
- Non-leaders can still access whispers and global chat during this phase

### Leader Summit (15 seconds)

- Both room leaders are teleported to a private "Summit" room
- A forced whisper is created between them (they cannot exit it)
- **Chat only:** Leaders can send text messages to each other. The
  whisper action menu (B button) is disabled during summit -- no
  color/role exchanges, leadership transfer, or other whisper actions
  are possible. (`sim.ts:544` gates B-button on `!isSummit`; the summit
  whisper is created fresh with empty offer sets.)
- Leaders can tab between whisper, shout (global room chat), and info
  screen surfaces using Left/Right. They remain in the summit whisper
  but can read their room's global chat.
- Hostage selections are announced to both rooms' shout channels
- All other players remain in their rooms with fog of war active
- After the timer expires, leaders return to their original rooms

### Hostage Exchange (8 seconds)

- Cutscene showing hostages being transferred between rooms
- All whispers are ejected before the exchange begins
- No player input during this phase
- After the exchange, the next round starts with new random leaders
  (or proceeds to Reveal if this was the final round)

### Reveal (5 seconds)

- All roles are revealed to all players
- The winning team (or "NO ONE WINS") is displayed
- Win condition is evaluated at this point

### Game Over (10 seconds)

- Results screen remains visible
- After the timer expires, the game resets to Lobby

---

## Communication

### Private Whispers

- Created by pressing A/J while not near another whisper player
- The whisper spawns at the creator's position in the game world
- Maximum 4 occupants per whisper
- Other players can **request entry** by pressing B/K near any whisper
  occupant
- Entry requires an occupant to **GRANT** the request via the action menu
  (or auto-granted if `autoGrantWhisperEntry` is configured)
- Entry requests timeout after 10 seconds (240 ticks)
- While in a whisper, the view switches to a full-screen chat interface
  (header shows "WHISP")
- A speech bubble indicator appears above your world sprite (visible to
  other players)
- Players in a whisper cannot move; velocity is zeroed
- Leaving a whisper (via Select/L button or action menu EXIT) returns to
  the game world
- When all occupants leave, the whisper is destroyed and pending requests
  are cancelled

**Chat messages**: Players can type text messages (printable ASCII, max 58
characters = 29 chars/line x 2 lines) visible to all current whisper
occupants. Only occupants present when a message is sent can see it.
Rate-limited to one message per 2 seconds (48 ticks).

**Isolation**: While in a whisper, a player has **no access to global
chat** -- they cannot send global messages, read global messages, or see an
unread indicator. Chat packets sent while in a whisper are routed to the
whisper, not global. The player must exit the whisper first to interact
with global chat in any way.

### Global Room Chat (Shout)

- Accessible by pressing Select/L in the overworld
- Room-wide: all players in the same room can see messages
- Players only see messages sent after they entered the room (hostage
  exchangees lose prior history)
- Also used for **usurp voting** (non-leaders) and **hostage selection**
  (leaders during hostage select phase)
- A blinking green dot in the bottom-right of the overworld indicates
  unread global messages
- While in the overworld (not in a whisper), the most recent global
  message is shown on a "shout strip" above the bottom bar (during
  Playing and LeaderSummit phases)
- Rate-limited to one message per 10 seconds (240 ticks)

---

## Information Sharing

All information sharing happens inside private whispers via the action menu.

### Color Exchange (C.OFFER / C.ACCPT)

A safe first step -- reveals team colors without exposing specific roles.

1. Player A selects **C.OFFER** -- system message: "offered color"
2. Player B sees **C.ACCPT** appear in their action menu
3. Player B selects **C.ACCPT**, then picks Player A from the target picker
4. Both players' team colors are revealed to each other
5. System message: "swapped colors"

- Either player can withdraw before acceptance (**C.UNOFFR**)
- Offers are cleared when a player leaves the whisper
- **Does NOT count toward win condition**

### One-Way Role Reveal (ROLE)

Show your full role card to all current whisper occupants.

1. Player selects **ROLE**
2. All occupants now see the player's full role and team
3. System message: "showed role"

- **Does NOT count toward win condition** -- this is a one-way reveal,
  not a mutual exchange
- Useful for building trust ("I'll show mine if you show yours" -- but
  the game only mechanically tracks the one-way reveal)
- **Spy caveat**: A Spy's one-way ROLE reveal still shows the Spy's true
  role to occupants (they see "Spy"). However, color reveals and the
  Spy's visual team indicator show the *opposite* team.

### Mutual Role Exchange (R.OFFER / R.ACCPT)

**This is the core mechanic for the win condition.** Requires consent from
both parties.

1. Player A selects **R.OFFER** -- system message: "offered role"
2. Player B sees **R.ACCPT** appear in their action menu
3. Player B selects **R.ACCPT**, then picks Player A from the target picker
4. Both players' full roles are revealed to each other
5. System message: "shared roles"
6. Both players are added to each other's `sharedWith` set

- Either player can withdraw before acceptance (**R.UNOFFR**)
- Offers are cleared when a player leaves the whisper
- **This is the ONLY action that satisfies the win condition requirement**

### Key Distinction

| Action | Type | Counts for Win? |
|--------|------|-----------------|
| C.OFFER/C.ACCPT | Mutual color reveal | No |
| ROLE | One-way role show | No |
| R.OFFER/R.ACCPT | Mutual role exchange | **Yes** |

---

## Leadership

### Assignment

- One leader per room, randomly assigned at the start of each round
- Leaders are visually marked with crown pixels above their sprite
- Leaders cannot be selected as hostages

### Leadership Transfer (PASS / TAKE)

Inside a whisper:
1. The current leader selects **PASS** -- system message: "offered lead"
2. Another occupant sees **TAKE** appear in their action menu
3. The other player selects **TAKE** to accept leadership

### Usurp (Majority Vote)

Via global room chat (shout view):
1. Any non-leader opens global chat (Select/L)
2. The usurp candidate selector shows at the top of the shout view
3. Navigate candidates with left/right (NONE, player sprites, ME)
4. Press A/J to cast vote
5. Votes are visible via system messages ("voted for [sprite]")
6. If a candidate receives **majority votes** (floor(room_size / 2) + 1),
   they immediately become leader
7. All usurp votes in the room reset after a successful usurp or after
   hostage exchange (exchangees' votes reset)
- Available during Playing, HostageSelect, and LeaderSummit phases

---

## Hostage Selection Details

- After each round's Playing phase, the game enters HostageSelect
- Each room's leader must select a configured number of hostages (default: 1)
- The interface shows eligible players (everyone in the room except the leader)
  in a grid; the leader cursors through and toggles selections
- **Toggle**: A/J button to select/deselect a player
- **Commit**: B/K button to finalize the selection
- **Close view**: Select/L to return to world view without committing
- **Auto-fill**: If the timer (15 seconds) expires without commitment,
  remaining hostage slots are filled randomly from eligible unselected players
- After both rooms commit (or timeout), the LeaderSummit phase begins

---

## Win Conditions

Evaluated after the final round's hostage exchange. The decision tree:

```
Are Hades and Persephone in the SAME room?
 |
 +-- YES: Did Hades mutually exchange roles with Cerberus?
 |    +-- YES --> SHADES WIN
 |    +-- NO:  Did Persephone mutually exchange roles with Demeter?
 |         +-- YES --> NYMPHS WIN
 |         +-- NO  --> NOBODY WINS
 |
 +-- NO:  Did Persephone mutually exchange roles with Demeter?
      +-- YES --> NYMPHS WIN
      +-- NO:  Did Hades mutually exchange roles with Cerberus?
           +-- YES --> SHADES WIN
           +-- NO  --> NOBODY WINS
```

### Key Rules

1. **Both teams must earn their win.** If neither Hades/Cerberus nor
   Persephone/Demeter performed a mutual role exchange, **nobody wins**.

2. **Room co-location is the tiebreaker.** If both key pairs completed their
   exchanges, the team whose key pair is in the same room gets priority.
   Specifically: when Hades and Persephone are in the same room, Shades
   are checked first.

3. **"Mutual role exchange" means R.OFFER + R.ACCPT.** The `sharedWith`
   set on each player tracks these. One-way reveals (ROLE), color exchanges,
   and verbal claims do NOT count.

4. **Players may lie verbally but card reveals are truthful.** Mechanically
   revealed information (colors, roles) is always accurate. Chat messages
   can contain any text.

### Strategy Implications

- **Shades** want Hades in the same room as Persephone, AND Hades must find
  and exchange roles with Cerberus. Shades benefit from manipulation --
  getting Persephone moved to Hades' room (or Hades to Persephone's room)
  while completing the Hades-Cerberus exchange.

- **Nymphs** want Persephone in a different room from Hades, AND Persephone
  must find and exchange roles with Demeter. Nymphs benefit from keeping
  Persephone away from Hades while completing the Persephone-Demeter
  exchange.

- **Grunts** on either team can help by:
  - Locating key roles through chatroom interactions
  - Sharing intelligence via global chat
  - Volunteering (or refusing) to be hostages
  - Seeking leadership to control hostage selection
  - Usurping unhelpful leaders
  - Misleading the opposing team about identities

---

## Differences from Standard Two Rooms and a Boom

1. **Disjoint rooms** -- rooms are completely separate coordinate spaces with
   no physical connection. No "peeking" or standing at a doorway.

2. **Random leader selection** -- leaders are randomly assigned each round
   (can be passed via chatroom or usurped via majority vote).

3. **Chatroom-based communication** -- private whispers (up to 4 players)
   replace physical card showing. Entry requires an occupant's GRANT.

4. **Global room chat** -- room-wide text channel for public communication,
   usurp voting, and shout announcements.

5. **Mandatory role exchange for victory** -- Cerberus and Demeter create a
   hard requirement: the key roles (Hades/Persephone) must perform a
   consensual mutual role exchange (R.OFFER + R.ACCPT) with their partner
   for their team to win. Without this, nobody wins. This is stricter than
   standard 2R1B where the bomber just needs to be in the same room.

6. **Pixel-only observation** -- players see a 128x128 4-bit pixel
   framebuffer. There is no structured state API. All information must be
   extracted visually or through chat text.

---

## Timing Reference

| Phase | Duration | Notes |
|-------|----------|-------|
| Lobby | Until full (+ 1s countdown) | Configurable player count |
| Roster Reveal | ~15 seconds (shared intro timer) | Panel 0 of intro sequence |
| Role Reveal | ~15 seconds (shared intro timer) | Panels 1-3; auto-advances when all ready |
| Playing | **Configurable per round** | See config presets below |
| Hostage Select | 15 seconds | Auto-fills on timeout |
| Leader Summit | 15 seconds | Chat only; leaders meet privately |
| Hostage Exchange | 8 seconds | Cutscene, no input |
| Reveal | 5 seconds | |
| Game Over | 10 seconds | Then resets to Lobby |

**Playing phase duration** varies widely across named presets:

| Config | Playing Duration per Round |
|--------|--------------------------|
| `default` / `fast` | 15s / 15s / 15s (rapid testing) |
| `short` / `empty` | 30s (single round) |
| `empty3` | 45s / 45s / 45s |
| `simple` | 60s (single round) |
| `medium` | 180s / 120s / 60s (descending) |
| `medium12` | 300s / 240s / 180s / 120s / 60s |

The `medium` family uses descending durations: early rounds are long
(exploration), later rounds are short (urgency). See GAME_API.md
§Named Presets for the complete list.

At 24 FPS, 15 seconds = 360 ticks. With `fastTimers` enabled, most phase
durations are reduced to 0.5--1 second for testing.

---

## Action Rate Limits

Actions and chat messages are rate-limited:

| Context | Default Cooldown | Notes |
|---------|-----------------|-------|
| Shout (global chat) | 10 seconds (240 ticks) | Between room-wide messages |
| Whisper chat | 2 seconds (48 ticks) | Between whisper messages |
| Whisper actions | 2 seconds (48 ticks) | Per-action cooldown |

Rate limits can be customized per action via `GameConfig.actionRateLimits`.
The special key `"_default"` sets the fallback for unlisted actions.
