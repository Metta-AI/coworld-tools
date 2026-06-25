# Cogshambo WebGPU First Playable Design

## Status

Approved direction:

- LLM-ready prototype, with stubbed controllers enabled by default.
- Native WebGPU renderer.
- Chunky sprite-board camera style.
- Server-authoritative grid simulation.

## Goal

Build the first playable version of Cogshambo: a browser-based WebGPU grid world populated by objects and agents called cogs. Each cog has an id, name, sprite-sheet reference, attributes, and a current vibe. Cogs are controlled in parallel by controller implementations that can be backed by LLMs later, but the default development mode uses deterministic or random stub controllers so the game is playable without model keys or model latency.

The first milestone should prove the end-to-end loop: start the server, open the browser client, render the grid world, run multiple cogs, show their local perception and vibe state, resolve bump interactions, create a cog through an HTTP endpoint, and stream authoritative world snapshots over WebSocket.

## Non-Goals

- No production account system or authentication in the first playable.
- No hosted deployment target in the first milestone.
- No required real LLM calls for local development.
- No complex asset pipeline beyond sprite-sheet manifest references and placeholder atlas content.
- No client-authoritative gameplay state.

## Architecture

The project should use a TypeScript monorepo-style layout with shared types between server and client.

```text
src/
  shared/
    protocol.ts
    types.ts
  server/
    index.ts
    http.ts
    websocket.ts
    controllers/
    simulation/
  client/
    main.ts
    net/
    render/
    ui/
```

The server owns all gameplay state. The client receives snapshots and renders them. The renderer is an adapter over simulation data, not a source of truth.

## Server Components

The HTTP server serves the built client and exposes API endpoints:

- `GET /health` returns basic server status.
- `GET /api/world` returns the latest world snapshot.
- `POST /api/cogs` creates a new cog and inserts it into the world.
- `GET /ws` or `/ws` upgrades to a WebSocket that streams world snapshots and events.

The simulation runs on a fixed tick. On each tick, every cog receives an observation derived from its position and sight radius. Cog controllers run concurrently through a `CogController` interface and return intended actions. The simulation validates and applies those actions, resolves collisions and bump effects, then broadcasts a snapshot.

## Simulation Model

The grid is discrete. Positions are integer `{ x, y }` cells. The first playable should use a bounded rectangular world with deterministic seed content.

Core entities:

- `Cog`: id, name, position, sprite sheet key, attributes, vibe, controller id, and optional metadata.
- `WorldObject`: id, type, position, sprite key, attributes, and bump behavior.
- `Vibe`: a compact mode value that affects bump resolution.
- `WorldSnapshot`: tick number, dimensions, cogs, objects, recent events, and optional debug state.

Perception is a circle of radius 5 grid cells around the cog. Observations should include visible cogs, visible objects, visible terrain bounds, the cog's own attributes, current vibe, and recent local events.

Bump resolution is centralized in the simulation. When a cog tries to move into an occupied cell, the world produces a bump event and applies behavior based on the cog's current vibe and the target entity type. First-pass vibes can be intentionally simple, for example:

- `curious`: inspect or annotate the target.
- `pushy`: nudge movable targets if possible.
- `friendly`: transfer a small positive status marker to another cog.
- `guarded`: avoid or step back after contact.

Exact vibe effects can start small, but the data model should allow adding more effects without changing the WebSocket protocol shape.

## Cog Controllers

Controllers implement one interface:

```ts
interface CogController {
  decide(input: CogDecisionInput): Promise<CogAction>;
}
```

`CogDecisionInput` contains the cog state, local observation, allowed actions, and recent local events. `CogAction` supports movement, waiting, vibe changes, and optional speech or intent text.

Default controllers:

- `stub`: deterministic behavior for tests and demos.
- `wander`: seeded random movement for a living world feel.
- `llm`: provider-backed implementation behind environment config, disabled unless explicitly configured.

LLM readiness means prompts and observation payloads are shaped now, but local play does not require API keys. Secrets must come from `.env` or process environment and must not be committed.

## WebSocket Protocol

The server sends:

- `snapshot`: full world snapshot at connect and at a regular cadence.
- `event`: compact recent world event such as bump, spawn, vibe change, or controller error.
- `serverStatus`: tick rate, connected clients, and controller mode.

The client sends:

- `hello`: client metadata.
- `debugCommand`: optional development commands such as follow cog or toggle overlays.

The client does not send authoritative cog actions in the first playable.

## WebGPU Client

The client uses native WebGPU through `navigator.gpu`. It renders a chunky sprite-board using instanced quads:

- Grid tiles are instanced quads.
- Objects are instanced quads using sprite atlas coordinates.
- Cogs are instanced quads using their sprite-sheet key and animation frame.
- Optional perception radius overlay is rendered as a translucent ring or highlighted tile mask.

The camera is top-down, board-like, and readable. It can pan and zoom, with a default follow mode for a selected cog. Text-heavy UI stays in DOM overlays rather than inside the canvas.

If WebGPU is unavailable, the client should show a clear DOM fallback message. A full WebGL fallback is not part of the first milestone.

## UI

The first screen is the game, not a landing page. Persistent UI stays compact:

- Status strip: connection, tick, cog count, controller mode.
- Selected cog panel: name, id, vibe, attributes, visible entity count.
- Debug controls: spawn cog, follow selected cog, toggle perception overlay.

The UI should avoid hiding the playfield. Larger debug detail can be collapsed.

## Assets

The first playable uses placeholder generated sprite sheets or simple atlas regions, but cogs are modeled as having their own sprite-sheet reference from day one. Asset lookup should be manifest-based rather than filename-driven.

Example manifest shape:

```ts
type SpriteSheetRef = {
  key: string;
  url: string;
  frameWidth: number;
  frameHeight: number;
  animations: Record<string, number[]>;
};
```

## Error Handling

Server:

- Controller failures produce a `wait` action and a world event.
- Invalid API payloads return structured `400` responses.
- WebSocket disconnects do not affect simulation state.

Client:

- WebGPU initialization failure shows a readable message.
- WebSocket disconnect displays status and retries with backoff.
- Malformed snapshots are ignored with a visible debug error.

## Testing

Unit tests should cover:

- Perception radius includes cells inside radius 5 and excludes cells outside it.
- Cog creation validates required fields and inserts into an empty cell.
- Collision attempts produce bump events.
- Vibe-specific bump behavior changes the world or event stream as expected.
- Stub controllers return valid actions.

Smoke tests should cover:

- Server boots and `GET /health` succeeds.
- Browser client loads.
- WebGPU initializes when available.
- A snapshot renders at least grid, objects, and cogs.
- `POST /api/cogs` creates a cog that appears in a subsequent snapshot.

## First Implementation Milestone

1. Scaffold TypeScript project with Vite client and Node server.
2. Define shared types and protocol messages.
3. Implement server simulation with seeded world content.
4. Implement stub and wander controllers through the future LLM interface.
5. Implement HTTP endpoints and WebSocket snapshot streaming.
6. Implement native WebGPU board renderer and compact DOM HUD.
7. Add focused tests and a browser smoke check.

## Review Notes

This design intentionally keeps hosted infrastructure, auth, and real LLM provider behavior out of the first milestone. Those can be added after the server-authoritative loop, protocol, and renderer are proven locally.
