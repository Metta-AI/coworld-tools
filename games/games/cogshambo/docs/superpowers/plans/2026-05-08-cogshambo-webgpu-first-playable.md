# Cogshambo WebGPU First Playable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first playable Cogshambo prototype: a server-authoritative grid simulation with cogs, vibes, WebSocket snapshots, a cog creation endpoint, and a native WebGPU chunky sprite-board client.

**Architecture:** The server owns simulation state and controller decisions. Shared TypeScript types define the protocol boundary. The browser client connects by WebSocket, renders authoritative snapshots with native WebGPU, and uses DOM overlays for status, selected-cog detail, and debug controls.

**Tech Stack:** TypeScript, Node.js ESM, Express, ws, Vite, native WebGPU/WGSL, Vitest, Playwright.

---

## File Structure

Create this structure:

```text
package.json
tsconfig.json
tsconfig.node.json
vite.config.ts
vitest.config.ts
playwright.config.ts
index.html
src/
  shared/
    protocol.ts
    types.ts
  server/
    index.ts
    http.ts
    websocket.ts
    controllers/
      cog-controller.ts
      llm-controller.ts
      stub-controller.ts
      wander-controller.ts
    simulation/
      bump.ts
      observation.ts
      random.ts
      seed-world.ts
      world.ts
  client/
    main.ts
    net/
      world-socket.ts
    render/
      atlas.ts
      camera.ts
      shaders.ts
      webgpu-board-renderer.ts
    ui/
      hud.ts
      styles.css
tests/
  server/
    api.test.ts
    controllers.test.ts
    simulation.test.ts
  smoke/
    client.spec.ts
```

Responsibilities:

- `src/shared`: Serializable contracts used by server and client.
- `src/server/simulation`: Pure world rules, perception, bump handling, and seeded state.
- `src/server/controllers`: Cog decision implementations behind one interface.
- `src/server/http.ts`: Express app, API routes, and static client serving.
- `src/server/websocket.ts`: WebSocket connection lifecycle and snapshot broadcasting.
- `src/client/net`: WebSocket client with reconnect behavior.
- `src/client/render`: Native WebGPU renderer, camera math, WGSL shader code, starter sprite atlas.
- `src/client/ui`: DOM HUD and debug controls.

---

### Task 1: Project Scaffold

**Files:**

- Create: `package.json`
- Create: `tsconfig.json`
- Create: `tsconfig.node.json`
- Create: `vite.config.ts`
- Create: `vitest.config.ts`
- Create: `playwright.config.ts`
- Create: `index.html`
- Create: `src/client/ui/styles.css`

- [ ] **Step 1: Create package and TypeScript configuration**

Create `package.json`:

```json
{
  "name": "cogshambo",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "dev:server": "tsx watch src/server/index.ts",
    "build": "tsc -p tsconfig.node.json && vite build",
    "start": "node dist-server/server/index.js",
    "test": "vitest run",
    "test:watch": "vitest",
    "smoke": "playwright test",
    "check": "npm run test && npm run build"
  },
  "dependencies": {
    "express": "^4.19.2",
    "nanoid": "^5.0.7",
    "ws": "^8.17.1",
    "zod": "^3.23.8"
  },
  "devDependencies": {
    "@playwright/test": "^1.44.1",
    "@types/express": "^4.17.21",
    "@types/node": "^20.14.2",
    "@types/ws": "^8.5.10",
    "tsx": "^4.15.6",
    "typescript": "^5.4.5",
    "vite": "^5.2.12",
    "vitest": "^1.6.0"
  }
}
```

Create `tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true
  },
  "include": ["src/client", "src/shared", "tests/smoke"]
}
```

Create `tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "outDir": "dist-server",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "skipLibCheck": true
  },
  "include": ["src/server", "src/shared"],
  "exclude": ["tests", "dist", "dist-server"]
}
```

- [ ] **Step 2: Create Vite, Vitest, and Playwright config**

Create `vite.config.ts`:

```ts
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
```

Create `vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/server/**/*.test.ts"],
    coverage: {
      reporter: ["text", "html"],
    },
  },
});
```

Create `playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/smoke",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
  },
});
```

- [ ] **Step 3: Create the browser shell**

Create `index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Cogshambo</title>
  </head>
  <body>
    <div id="app">
      <canvas id="world-canvas" aria-label="Cogshambo world"></canvas>
      <section id="hud" aria-live="polite"></section>
    </div>
    <script type="module" src="/src/client/main.ts"></script>
  </body>
</html>
```

Create `src/client/ui/styles.css`:

```css
:root {
  color: #e8f2f0;
  background: #101314;
  font-family:
    Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
    sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  overflow: hidden;
}

#app {
  min-height: 100vh;
  position: relative;
}

#world-canvas {
  display: block;
  height: 100vh;
  width: 100vw;
}

#hud {
  inset: 12px 12px auto auto;
  max-width: min(360px, calc(100vw - 24px));
  position: fixed;
  z-index: 2;
}

.hud-panel {
  background: rgba(12, 18, 18, 0.82);
  border: 1px solid rgba(220, 255, 248, 0.18);
  border-radius: 8px;
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.28);
  display: grid;
  gap: 10px;
  padding: 12px;
}

.hud-row {
  align-items: center;
  display: flex;
  gap: 10px;
  justify-content: space-between;
}

.hud-label {
  color: #9fb4b0;
  font-size: 12px;
}

.hud-value {
  font-size: 13px;
  font-weight: 700;
}

.hud-button {
  background: #d4f75f;
  border: 0;
  border-radius: 6px;
  color: #111809;
  cursor: pointer;
  font-weight: 800;
  padding: 8px 10px;
}

.hud-button:focus-visible {
  outline: 2px solid #ffffff;
  outline-offset: 2px;
}

.fallback {
  align-items: center;
  display: flex;
  min-height: 100vh;
  justify-content: center;
  padding: 24px;
  text-align: center;
}
```

- [ ] **Step 4: Install dependencies**

Run:

```bash
npm install
```

Expected: `package-lock.json` is created and npm exits with code 0.

- [ ] **Step 5: Run scaffold checks**

Run:

```bash
npm run build
```

Expected: build fails because `src/client/main.ts` does not exist yet. The failure confirms scripts are wired.

- [ ] **Step 6: Commit scaffold**

Run:

```bash
git add package.json package-lock.json tsconfig.json tsconfig.node.json vite.config.ts vitest.config.ts playwright.config.ts index.html src/client/ui/styles.css
git commit -m "chore: scaffold TypeScript WebGPU app"
```

Expected: a new commit containing only scaffold files.

---

### Task 2: Shared Types and Protocol Contracts

**Files:**

- Create: `src/shared/types.ts`
- Create: `src/shared/protocol.ts`
- Create: `tests/server/protocol.test.ts`

- [ ] **Step 1: Write protocol validation tests**

Create `tests/server/protocol.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  createCogRequestSchema,
  isClientMessage,
  isServerMessage,
} from "../../src/shared/protocol.js";

describe("protocol contracts", () => {
  it("accepts a valid create cog request", () => {
    const parsed = createCogRequestSchema.parse({
      name: "Ada",
      spriteSheetKey: "cog-ada",
      controllerId: "wander",
      vibe: "curious",
      attributes: { energy: 7, focus: 4 },
    });

    expect(parsed.name).toBe("Ada");
    expect(parsed.attributes.energy).toBe(7);
  });

  it("rejects a create cog request without a name", () => {
    expect(() =>
      createCogRequestSchema.parse({
        spriteSheetKey: "cog-empty",
      }),
    ).toThrow();
  });

  it("recognizes server and client message shapes", () => {
    expect(isClientMessage({ type: "hello", clientName: "test" })).toBe(true);
    expect(isClientMessage({ type: "snapshot" })).toBe(false);
    expect(
      isServerMessage({
        type: "serverStatus",
        status: {
          tick: 1,
          cogCount: 2,
          clientCount: 0,
          controllerMode: "stub",
        },
      }),
    ).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests to verify the missing module failure**

Run:

```bash
npm run test -- tests/server/protocol.test.ts
```

Expected: FAIL with a module resolution error for `src/shared/protocol.js`.

- [ ] **Step 3: Add shared gameplay types**

Create `src/shared/types.ts`:

```ts
export type Direction = "north" | "south" | "east" | "west";

export type Vibe = "curious" | "pushy" | "friendly" | "guarded";

export type ControllerId = "stub" | "wander" | "llm";

export type EntityKind = "cog" | "object";

export type Position = {
  x: number;
  y: number;
};

export type Attributes = Record<string, number>;

export type SpriteSheetRef = {
  key: string;
  url: string;
  frameWidth: number;
  frameHeight: number;
  animations: Record<string, number[]>;
};

export type Cog = {
  id: string;
  name: string;
  position: Position;
  spriteSheetKey: string;
  attributes: Attributes;
  vibe: Vibe;
  controllerId: ControllerId;
  intent?: string;
};

export type WorldObject = {
  id: string;
  type: "rock" | "berry" | "beacon" | "crate";
  position: Position;
  spriteKey: string;
  attributes: Attributes;
  bumpBehavior: "solid" | "movable" | "collectible" | "signal";
};

export type WorldDimensions = {
  width: number;
  height: number;
};

export type VisibleEntity =
  | {
      kind: "cog";
      id: string;
      name: string;
      position: Position;
      vibe: Vibe;
      spriteSheetKey: string;
    }
  | {
      kind: "object";
      id: string;
      objectType: WorldObject["type"];
      position: Position;
      spriteKey: string;
      bumpBehavior: WorldObject["bumpBehavior"];
    };

export type WorldEvent = {
  id: string;
  tick: number;
  type: "spawn" | "bump" | "move" | "vibeChange" | "controllerError" | "inspect";
  actorId?: string;
  targetId?: string;
  message: string;
  position?: Position;
};

export type CogObservation = {
  cog: Cog;
  radius: number;
  dimensions: WorldDimensions;
  visibleEntities: VisibleEntity[];
  visibleCells: Position[];
  recentEvents: WorldEvent[];
};

export type CogAction =
  | { type: "wait"; intent?: string }
  | { type: "move"; direction: Direction; intent?: string }
  | { type: "setVibe"; vibe: Vibe; intent?: string }
  | { type: "say"; text: string; intent?: string };

export type CogDecisionInput = {
  tick: number;
  observation: CogObservation;
  allowedActions: CogAction["type"][];
};

export type WorldSnapshot = {
  tick: number;
  dimensions: WorldDimensions;
  cogs: Cog[];
  objects: WorldObject[];
  recentEvents: WorldEvent[];
};

export type ServerStatus = {
  tick: number;
  cogCount: number;
  clientCount: number;
  controllerMode: ControllerId;
};
```

- [ ] **Step 4: Add protocol schemas and type guards**

Create `src/shared/protocol.ts`:

```ts
import { z } from "zod";
import type { ControllerId, ServerStatus, Vibe, WorldEvent, WorldSnapshot } from "./types.js";

export const vibeSchema = z.enum(["curious", "pushy", "friendly", "guarded"]);
export const controllerIdSchema = z.enum(["stub", "wander", "llm"]);

export const createCogRequestSchema = z.object({
  name: z.string().min(1).max(40),
  spriteSheetKey: z.string().min(1).max(80).default("cog-default"),
  controllerId: controllerIdSchema.default("wander"),
  vibe: vibeSchema.default("curious"),
  attributes: z.record(z.number()).default({ energy: 5, focus: 5 }),
  position: z
    .object({
      x: z.number().int().nonnegative(),
      y: z.number().int().nonnegative(),
    })
    .optional(),
});

export type CreateCogRequest = z.infer<typeof createCogRequestSchema>;

export type CreateCogResponse = {
  cogId: string;
  snapshot: WorldSnapshot;
};

export type ServerMessage =
  | { type: "snapshot"; snapshot: WorldSnapshot }
  | { type: "event"; event: WorldEvent }
  | { type: "serverStatus"; status: ServerStatus };

export type ClientMessage =
  | { type: "hello"; clientName: string }
  | { type: "debugCommand"; command: "followCog" | "togglePerception"; cogId?: string };

export function isServerMessage(value: unknown): value is ServerMessage {
  if (!isRecord(value) || typeof value.type !== "string") {
    return false;
  }

  if (value.type === "snapshot") {
    return isRecord(value.snapshot) && Array.isArray(value.snapshot.cogs);
  }

  if (value.type === "event") {
    return isRecord(value.event) && typeof value.event.message === "string";
  }

  if (value.type === "serverStatus") {
    const status = value.status as Partial<ServerStatus> | undefined;
    return (
      isRecord(status) &&
      typeof status.tick === "number" &&
      typeof status.cogCount === "number" &&
      typeof status.clientCount === "number" &&
      typeof status.controllerMode === "string"
    );
  }

  return false;
}

export function isClientMessage(value: unknown): value is ClientMessage {
  if (!isRecord(value) || typeof value.type !== "string") {
    return false;
  }

  if (value.type === "hello") {
    return typeof value.clientName === "string";
  }

  if (value.type === "debugCommand") {
    return value.command === "followCog" || value.command === "togglePerception";
  }

  return false;
}

export function parseControllerId(value: string | undefined): ControllerId {
  return controllerIdSchema.catch("stub").parse(value);
}

export function parseVibe(value: string | undefined): Vibe {
  return vibeSchema.catch("curious").parse(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
```

- [ ] **Step 5: Run protocol tests**

Run:

```bash
npm run test -- tests/server/protocol.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit shared contracts**

Run:

```bash
git add src/shared tests/server/protocol.test.ts
git commit -m "feat: define shared world protocol"
```

Expected: a commit with shared contracts and protocol tests.

---

### Task 3: Simulation Core

**Files:**

- Create: `src/server/simulation/random.ts`
- Create: `src/server/simulation/observation.ts`
- Create: `src/server/simulation/bump.ts`
- Create: `src/server/simulation/world.ts`
- Create: `src/server/simulation/seed-world.ts`
- Create: `tests/server/simulation.test.ts`

- [ ] **Step 1: Write simulation tests**

Create `tests/server/simulation.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { CogAction } from "../../src/shared/types.js";
import { createSeedWorld } from "../../src/server/simulation/seed-world.js";
import { GridWorld } from "../../src/server/simulation/world.js";

describe("GridWorld", () => {
  it("creates observations with a radius-5 circular field of view", () => {
    const world = new GridWorld({ width: 20, height: 20 });
    const centerCog = world.addCog({
      name: "Center",
      spriteSheetKey: "cog-center",
      controllerId: "stub",
      vibe: "curious",
      attributes: { energy: 5 },
      position: { x: 10, y: 10 },
    });
    const nearCog = world.addCog({
      name: "Near",
      spriteSheetKey: "cog-near",
      controllerId: "stub",
      vibe: "friendly",
      attributes: { energy: 5 },
      position: { x: 13, y: 14 },
    });
    world.addCog({
      name: "Far",
      spriteSheetKey: "cog-far",
      controllerId: "stub",
      vibe: "guarded",
      attributes: { energy: 5 },
      position: { x: 16, y: 10 },
    });

    const observation = world.getObservation(centerCog.id);

    expect(observation.radius).toBe(5);
    expect(observation.visibleEntities.some((entity) => entity.id === nearCog.id)).toBe(true);
    expect(observation.visibleEntities.some((entity) => entity.kind === "cog" && entity.name === "Far")).toBe(false);
    expect(observation.visibleCells).toContainEqual({ x: 10, y: 10 });
    expect(observation.visibleCells).toContainEqual({ x: 15, y: 10 });
    expect(observation.visibleCells).not.toContainEqual({ x: 16, y: 10 });
  });

  it("creates a cog in an empty cell", () => {
    const world = new GridWorld({ width: 8, height: 8 });

    const cog = world.addCog({
      name: "New Cog",
      spriteSheetKey: "cog-new",
      controllerId: "wander",
      vibe: "friendly",
      attributes: { energy: 8 },
    });

    expect(cog.id).toMatch(/^cog_/);
    expect(cog.position.x).toBeGreaterThanOrEqual(0);
    expect(cog.position.y).toBeGreaterThanOrEqual(0);
    expect(world.snapshot().cogs).toHaveLength(1);
  });

  it("produces bump events when a cog moves into a solid object", async () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const cog = world.addCog({
      name: "Bumper",
      spriteSheetKey: "cog-bumper",
      controllerId: "stub",
      vibe: "curious",
      attributes: { energy: 5 },
      position: { x: 2, y: 2 },
    });
    world.addObject({
      id: "rock_1",
      type: "rock",
      position: { x: 3, y: 2 },
      spriteKey: "rock",
      attributes: {},
      bumpBehavior: "solid",
    });

    await world.step(new Map<string, CogAction>([[cog.id, { type: "move", direction: "east" }]]));

    const movedCog = world.snapshot().cogs.find((candidate) => candidate.id === cog.id);
    expect(movedCog?.position).toEqual({ x: 2, y: 2 });
    expect(world.snapshot().recentEvents.at(-1)?.type).toBe("bump");
  });

  it("lets pushy cogs nudge movable objects", async () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const cog = world.addCog({
      name: "Pusher",
      spriteSheetKey: "cog-pusher",
      controllerId: "stub",
      vibe: "pushy",
      attributes: { energy: 5 },
      position: { x: 2, y: 2 },
    });
    world.addObject({
      id: "crate_1",
      type: "crate",
      position: { x: 3, y: 2 },
      spriteKey: "crate",
      attributes: {},
      bumpBehavior: "movable",
    });

    await world.step(new Map<string, CogAction>([[cog.id, { type: "move", direction: "east" }]]));

    const snapshot = world.snapshot();
    expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)?.position).toEqual({ x: 3, y: 2 });
    expect(snapshot.objects.find((object) => object.id === "crate_1")?.position).toEqual({ x: 4, y: 2 });
  });

  it("creates deterministic seeded worlds", () => {
    const world = createSeedWorld();
    const snapshot = world.snapshot();

    expect(snapshot.dimensions).toEqual({ width: 24, height: 18 });
    expect(snapshot.cogs.length).toBeGreaterThanOrEqual(3);
    expect(snapshot.objects.length).toBeGreaterThanOrEqual(8);
  });
});
```

- [ ] **Step 2: Run tests to verify missing simulation modules**

Run:

```bash
npm run test -- tests/server/simulation.test.ts
```

Expected: FAIL with module resolution errors for `src/server/simulation/seed-world.js` and `world.js`.

- [ ] **Step 3: Add deterministic random helper**

Create `src/server/simulation/random.ts`:

```ts
export class SeededRandom {
  private state: number;

  constructor(seed = 0xdecafbad) {
    this.state = seed >>> 0;
  }

  next(): number {
    this.state = (1664525 * this.state + 1013904223) >>> 0;
    return this.state / 0x100000000;
  }

  int(maxExclusive: number): number {
    return Math.floor(this.next() * maxExclusive);
  }

  choice<T>(values: readonly T[]): T {
    if (values.length === 0) {
      throw new Error("Cannot choose from an empty array");
    }

    return values[this.int(values.length)];
  }
}
```

- [ ] **Step 4: Add observation and bump helpers**

Create `src/server/simulation/observation.ts`:

```ts
import type { Cog, CogObservation, Position, VisibleEntity, WorldEvent, WorldObject, WorldSnapshot } from "../../shared/types.js";

export const COG_SIGHT_RADIUS = 5;

export function squaredDistance(a: Position, b: Position): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return dx * dx + dy * dy;
}

export function isInsideRadius(origin: Position, target: Position, radius: number): boolean {
  return squaredDistance(origin, target) <= radius * radius;
}

export function visibleCells(origin: Position, width: number, height: number, radius = COG_SIGHT_RADIUS): Position[] {
  const cells: Position[] = [];

  for (let y = Math.max(0, origin.y - radius); y <= Math.min(height - 1, origin.y + radius); y += 1) {
    for (let x = Math.max(0, origin.x - radius); x <= Math.min(width - 1, origin.x + radius); x += 1) {
      const position = { x, y };
      if (isInsideRadius(origin, position, radius)) {
        cells.push(position);
      }
    }
  }

  return cells;
}

export function createObservation(cog: Cog, snapshot: WorldSnapshot): CogObservation {
  const visibleEntities: VisibleEntity[] = [
    ...snapshot.cogs
      .filter((candidate) => candidate.id !== cog.id)
      .filter((candidate) => isInsideRadius(cog.position, candidate.position, COG_SIGHT_RADIUS))
      .map((candidate) => ({
        kind: "cog" as const,
        id: candidate.id,
        name: candidate.name,
        position: candidate.position,
        vibe: candidate.vibe,
        spriteSheetKey: candidate.spriteSheetKey,
      })),
    ...snapshot.objects
      .filter((object) => isInsideRadius(cog.position, object.position, COG_SIGHT_RADIUS))
      .map((object) => objectToVisibleEntity(object)),
  ];

  const recentEvents = snapshot.recentEvents.filter((event) =>
    event.position ? isInsideRadius(cog.position, event.position, COG_SIGHT_RADIUS) : event.actorId === cog.id || event.targetId === cog.id,
  );

  return {
    cog,
    radius: COG_SIGHT_RADIUS,
    dimensions: snapshot.dimensions,
    visibleEntities,
    visibleCells: visibleCells(cog.position, snapshot.dimensions.width, snapshot.dimensions.height),
    recentEvents,
  };
}

function objectToVisibleEntity(object: WorldObject): VisibleEntity {
  return {
    kind: "object",
    id: object.id,
    objectType: object.type,
    position: object.position,
    spriteKey: object.spriteKey,
    bumpBehavior: object.bumpBehavior,
  };
}
```

Create `src/server/simulation/bump.ts`:

```ts
import type { Cog, Direction, Position, WorldObject } from "../../shared/types.js";

export function nextPosition(position: Position, direction: Direction): Position {
  switch (direction) {
    case "north":
      return { x: position.x, y: position.y - 1 };
    case "south":
      return { x: position.x, y: position.y + 1 };
    case "east":
      return { x: position.x + 1, y: position.y };
    case "west":
      return { x: position.x - 1, y: position.y };
  }
}

export function bumpMessage(actor: Cog, target: Cog | WorldObject): string {
  if ("name" in target) {
    return `${actor.name} bumped into ${target.name} with a ${actor.vibe} vibe`;
  }

  return `${actor.name} bumped into ${target.type} with a ${actor.vibe} vibe`;
}
```

- [ ] **Step 5: Add GridWorld**

Create `src/server/simulation/world.ts`:

```ts
import { nanoid } from "nanoid";
import type {
  Cog,
  CogAction,
  CogObservation,
  ControllerId,
  Direction,
  Position,
  Vibe,
  WorldDimensions,
  WorldEvent,
  WorldObject,
  WorldSnapshot,
} from "../../shared/types.js";
import { bumpMessage, nextPosition } from "./bump.js";
import { createObservation } from "./observation.js";

export type AddCogInput = {
  name: string;
  spriteSheetKey: string;
  controllerId: ControllerId;
  vibe: Vibe;
  attributes: Record<string, number>;
  position?: Position;
};

export class GridWorld {
  private tick = 0;
  private readonly dimensions: WorldDimensions;
  private readonly cogs = new Map<string, Cog>();
  private readonly objects = new Map<string, WorldObject>();
  private readonly recentEvents: WorldEvent[] = [];

  constructor(dimensions: WorldDimensions) {
    this.dimensions = dimensions;
  }

  addCog(input: AddCogInput): Cog {
    const position = input.position ?? this.findEmptyCell();
    if (!this.isInsideBounds(position)) {
      throw new Error(`Cog position is outside bounds: ${position.x},${position.y}`);
    }
    if (this.entityAt(position)) {
      throw new Error(`Cog position is occupied: ${position.x},${position.y}`);
    }

    const cog: Cog = {
      id: `cog_${nanoid(8)}`,
      name: input.name,
      position,
      spriteSheetKey: input.spriteSheetKey,
      attributes: input.attributes,
      vibe: input.vibe,
      controllerId: input.controllerId,
    };

    this.cogs.set(cog.id, cog);
    this.recordEvent({
      type: "spawn",
      actorId: cog.id,
      message: `${cog.name} entered the board`,
      position: cog.position,
    });
    return cog;
  }

  addObject(object: WorldObject): WorldObject {
    if (!this.isInsideBounds(object.position)) {
      throw new Error(`Object position is outside bounds: ${object.position.x},${object.position.y}`);
    }
    if (this.entityAt(object.position)) {
      throw new Error(`Object position is occupied: ${object.position.x},${object.position.y}`);
    }

    this.objects.set(object.id, object);
    return object;
  }

  getObservation(cogId: string): CogObservation {
    const cog = this.cogs.get(cogId);
    if (!cog) {
      throw new Error(`Unknown cog: ${cogId}`);
    }

    return createObservation(cog, this.snapshot());
  }

  async step(actions: Map<string, CogAction>): Promise<WorldSnapshot> {
    this.tick += 1;

    for (const [cogId, action] of actions) {
      const cog = this.cogs.get(cogId);
      if (!cog) {
        continue;
      }

      this.applyAction(cog, action);
    }

    return this.snapshot();
  }

  snapshot(): WorldSnapshot {
    return {
      tick: this.tick,
      dimensions: this.dimensions,
      cogs: Array.from(this.cogs.values()).map((cog) => ({ ...cog, position: { ...cog.position }, attributes: { ...cog.attributes } })),
      objects: Array.from(this.objects.values()).map((object) => ({
        ...object,
        position: { ...object.position },
        attributes: { ...object.attributes },
      })),
      recentEvents: this.recentEvents.map((event) => ({ ...event, position: event.position ? { ...event.position } : undefined })),
    };
  }

  private applyAction(cog: Cog, action: CogAction): void {
    cog.intent = action.intent;

    if (action.type === "wait") {
      return;
    }

    if (action.type === "setVibe") {
      cog.vibe = action.vibe;
      this.recordEvent({
        type: "vibeChange",
        actorId: cog.id,
        message: `${cog.name} shifted to ${action.vibe}`,
        position: cog.position,
      });
      return;
    }

    if (action.type === "say") {
      this.recordEvent({
        type: "inspect",
        actorId: cog.id,
        message: `${cog.name}: ${action.text}`,
        position: cog.position,
      });
      return;
    }

    this.tryMove(cog, action.direction);
  }

  private tryMove(cog: Cog, direction: Direction): void {
    const destination = nextPosition(cog.position, direction);
    if (!this.isInsideBounds(destination)) {
      this.recordEvent({
        type: "bump",
        actorId: cog.id,
        message: `${cog.name} bumped into the edge of the board`,
        position: cog.position,
      });
      return;
    }

    const target = this.entityAt(destination);
    if (!target) {
      cog.position = destination;
      this.recordEvent({
        type: "move",
        actorId: cog.id,
        message: `${cog.name} moved ${direction}`,
        position: cog.position,
      });
      return;
    }

    if ("bumpBehavior" in target && target.bumpBehavior === "movable" && cog.vibe === "pushy") {
      const pushedPosition = nextPosition(destination, direction);
      if (this.isInsideBounds(pushedPosition) && !this.entityAt(pushedPosition)) {
        target.position = pushedPosition;
        cog.position = destination;
        this.recordEvent({
          type: "bump",
          actorId: cog.id,
          targetId: target.id,
          message: `${cog.name} pushed ${target.type}`,
          position: destination,
        });
        return;
      }
    }

    if ("name" in target && cog.vibe === "friendly") {
      target.attributes.cheered = (target.attributes.cheered ?? 0) + 1;
    }

    this.recordEvent({
      type: "bump",
      actorId: cog.id,
      targetId: target.id,
      message: bumpMessage(cog, target),
      position: destination,
    });
  }

  private entityAt(position: Position): Cog | WorldObject | undefined {
    return (
      Array.from(this.cogs.values()).find((cog) => samePosition(cog.position, position)) ??
      Array.from(this.objects.values()).find((object) => samePosition(object.position, position))
    );
  }

  private findEmptyCell(): Position {
    for (let y = 0; y < this.dimensions.height; y += 1) {
      for (let x = 0; x < this.dimensions.width; x += 1) {
        const position = { x, y };
        if (!this.entityAt(position)) {
          return position;
        }
      }
    }

    throw new Error("World is full");
  }

  private isInsideBounds(position: Position): boolean {
    return position.x >= 0 && position.y >= 0 && position.x < this.dimensions.width && position.y < this.dimensions.height;
  }

  private recordEvent(event: Omit<WorldEvent, "id" | "tick">): void {
    this.recentEvents.push({
      ...event,
      id: `event_${nanoid(8)}`,
      tick: this.tick,
    });

    while (this.recentEvents.length > 40) {
      this.recentEvents.shift();
    }
  }
}

function samePosition(a: Position, b: Position): boolean {
  return a.x === b.x && a.y === b.y;
}
```

- [ ] **Step 6: Add seeded world content**

Create `src/server/simulation/seed-world.ts`:

```ts
import type { WorldObject } from "../../shared/types.js";
import { GridWorld } from "./world.js";

export function createSeedWorld(): GridWorld {
  const world = new GridWorld({ width: 24, height: 18 });

  world.addCog({
    name: "Ada",
    spriteSheetKey: "cog-ada",
    controllerId: "wander",
    vibe: "curious",
    attributes: { energy: 7, focus: 8 },
    position: { x: 5, y: 5 },
  });
  world.addCog({
    name: "Babbage",
    spriteSheetKey: "cog-babbage",
    controllerId: "wander",
    vibe: "pushy",
    attributes: { energy: 8, focus: 5 },
    position: { x: 12, y: 9 },
  });
  world.addCog({
    name: "Mira",
    spriteSheetKey: "cog-mira",
    controllerId: "stub",
    vibe: "friendly",
    attributes: { energy: 6, focus: 9 },
    position: { x: 18, y: 12 },
  });

  seedObjects().forEach((object) => world.addObject(object));
  return world;
}

function seedObjects(): WorldObject[] {
  return [
    { id: "rock_1", type: "rock", position: { x: 8, y: 5 }, spriteKey: "rock", attributes: {}, bumpBehavior: "solid" },
    { id: "rock_2", type: "rock", position: { x: 9, y: 5 }, spriteKey: "rock", attributes: {}, bumpBehavior: "solid" },
    { id: "crate_1", type: "crate", position: { x: 13, y: 9 }, spriteKey: "crate", attributes: {}, bumpBehavior: "movable" },
    { id: "crate_2", type: "crate", position: { x: 17, y: 12 }, spriteKey: "crate", attributes: {}, bumpBehavior: "movable" },
    { id: "berry_1", type: "berry", position: { x: 4, y: 10 }, spriteKey: "berry", attributes: { nutrition: 2 }, bumpBehavior: "collectible" },
    { id: "berry_2", type: "berry", position: { x: 20, y: 6 }, spriteKey: "berry", attributes: { nutrition: 2 }, bumpBehavior: "collectible" },
    { id: "beacon_1", type: "beacon", position: { x: 2, y: 2 }, spriteKey: "beacon", attributes: { signal: 1 }, bumpBehavior: "signal" },
    { id: "beacon_2", type: "beacon", position: { x: 21, y: 15 }, spriteKey: "beacon", attributes: { signal: 1 }, bumpBehavior: "signal" },
  ];
}
```

- [ ] **Step 7: Run simulation tests**

Run:

```bash
npm run test -- tests/server/simulation.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit simulation core**

Run:

```bash
git add src/server/simulation tests/server/simulation.test.ts
git commit -m "feat: add grid world simulation"
```

Expected: a commit containing simulation modules and tests.

---

### Task 4: Cog Controllers

**Files:**

- Create: `src/server/controllers/cog-controller.ts`
- Create: `src/server/controllers/stub-controller.ts`
- Create: `src/server/controllers/wander-controller.ts`
- Create: `src/server/controllers/llm-controller.ts`
- Create: `tests/server/controllers.test.ts`

- [ ] **Step 1: Write controller tests**

Create `tests/server/controllers.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { CogDecisionInput } from "../../src/shared/types.js";
import { LlmController } from "../../src/server/controllers/llm-controller.js";
import { StubController } from "../../src/server/controllers/stub-controller.js";
import { WanderController } from "../../src/server/controllers/wander-controller.js";

const input: CogDecisionInput = {
  tick: 1,
  allowedActions: ["wait", "move", "setVibe", "say"],
  observation: {
    radius: 5,
    dimensions: { width: 10, height: 10 },
    visibleEntities: [],
    visibleCells: [{ x: 1, y: 1 }],
    recentEvents: [],
    cog: {
      id: "cog_test",
      name: "Test",
      position: { x: 1, y: 1 },
      spriteSheetKey: "cog-test",
      attributes: { energy: 5 },
      vibe: "curious",
      controllerId: "stub",
    },
  },
};

describe("cog controllers", () => {
  it("stub controller returns a deterministic wait action", async () => {
    const action = await new StubController().decide(input);

    expect(action).toEqual({ type: "wait", intent: "observing" });
  });

  it("wander controller returns valid movement decisions", async () => {
    const controller = new WanderController(123);
    const action = await controller.decide(input);

    expect(["move", "wait", "setVibe"]).toContain(action.type);
  });

  it("llm controller fails closed to wait when no provider is configured", async () => {
    const controller = new LlmController({ apiKey: undefined });
    const action = await controller.decide(input);

    expect(action.type).toBe("wait");
    expect(action.intent).toContain("LLM disabled");
  });
});
```

- [ ] **Step 2: Run tests to verify missing controller modules**

Run:

```bash
npm run test -- tests/server/controllers.test.ts
```

Expected: FAIL with module resolution errors for `src/server/controllers/*`.

- [ ] **Step 3: Add controller interface and implementations**

Create `src/server/controllers/cog-controller.ts`:

```ts
import type { CogAction, CogDecisionInput, ControllerId } from "../../shared/types.js";
import { LlmController } from "./llm-controller.js";
import { StubController } from "./stub-controller.js";
import { WanderController } from "./wander-controller.js";

export interface CogController {
  decide(input: CogDecisionInput): Promise<CogAction>;
}

export type ControllerRegistry = Record<ControllerId, CogController>;

export function createControllerRegistry(): ControllerRegistry {
  return {
    stub: new StubController(),
    wander: new WanderController(0xc09_5a4b0),
    llm: new LlmController({ apiKey: process.env.COGSHAMBO_LLM_API_KEY }),
  };
}
```

Create `src/server/controllers/stub-controller.ts`:

```ts
import type { CogAction, CogDecisionInput } from "../../shared/types.js";
import type { CogController } from "./cog-controller.js";

export class StubController implements CogController {
  async decide(_input: CogDecisionInput): Promise<CogAction> {
    return { type: "wait", intent: "observing" };
  }
}
```

Create `src/server/controllers/wander-controller.ts`:

```ts
import type { CogAction, CogDecisionInput, Direction, Vibe } from "../../shared/types.js";
import { SeededRandom } from "../simulation/random.js";
import type { CogController } from "./cog-controller.js";

const directions: Direction[] = ["north", "south", "east", "west"];
const vibes: Vibe[] = ["curious", "pushy", "friendly", "guarded"];

export class WanderController implements CogController {
  private readonly random: SeededRandom;

  constructor(seed: number) {
    this.random = new SeededRandom(seed);
  }

  async decide(input: CogDecisionInput): Promise<CogAction> {
    const roll = this.random.next();

    if (roll < 0.1) {
      return { type: "wait", intent: "pausing to observe" };
    }

    if (roll < 0.2) {
      return {
        type: "setVibe",
        vibe: this.random.choice(vibes),
        intent: "shifting vibe after scanning nearby entities",
      };
    }

    return {
      type: "move",
      direction: this.random.choice(directions),
      intent: `wandering with ${input.observation.cog.vibe} vibe`,
    };
  }
}
```

Create `src/server/controllers/llm-controller.ts`:

```ts
import type { CogAction, CogDecisionInput } from "../../shared/types.js";
import type { CogController } from "./cog-controller.js";

export type LlmControllerConfig = {
  apiKey: string | undefined;
};

export class LlmController implements CogController {
  private readonly apiKey: string | undefined;

  constructor(config: LlmControllerConfig) {
    this.apiKey = config.apiKey;
  }

  async decide(input: CogDecisionInput): Promise<CogAction> {
    if (!this.apiKey) {
      return {
        type: "wait",
        intent: `LLM disabled for ${input.observation.cog.name}; set COGSHAMBO_LLM_API_KEY to enable provider calls`,
      };
    }

    return {
      type: "wait",
      intent: "LLM provider hook configured; provider call is intentionally not enabled in the first playable",
    };
  }
}
```

- [ ] **Step 4: Run controller tests**

Run:

```bash
npm run test -- tests/server/controllers.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit controllers**

Run:

```bash
git add src/server/controllers tests/server/controllers.test.ts
git commit -m "feat: add cog controller interface"
```

Expected: a commit containing controller implementations and tests.

---

### Task 5: HTTP API and WebSocket Server

**Files:**

- Create: `src/server/http.ts`
- Create: `src/server/websocket.ts`
- Create: `src/server/index.ts`
- Create: `tests/server/api.test.ts`

- [ ] **Step 1: Write API tests**

Create `tests/server/api.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createServer } from "node:http";
import { AddressInfo } from "node:net";
import { createApp } from "../../src/server/http.js";
import { createControllerRegistry } from "../../src/server/controllers/cog-controller.js";
import { createSeedWorld } from "../../src/server/simulation/seed-world.js";

let server: ReturnType<typeof createServer>;
let baseUrl: string;

beforeEach(async () => {
  const world = createSeedWorld();
  const app = createApp({ world, controllers: createControllerRegistry() });
  server = createServer(app);
  await new Promise<void>((resolve) => server.listen(0, resolve));
  const address = server.address() as AddressInfo;
  baseUrl = `http://127.0.0.1:${address.port}`;
});

afterEach(async () => {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
});

describe("HTTP API", () => {
  it("returns health status", async () => {
    const response = await fetch(`${baseUrl}/health`);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(body.snapshot.cogs.length).toBeGreaterThan(0);
  });

  it("returns the latest world snapshot", async () => {
    const response = await fetch(`${baseUrl}/api/world`);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.tick).toBe(0);
    expect(body.dimensions.width).toBe(24);
  });

  it("creates a cog through the API", async () => {
    const response = await fetch(`${baseUrl}/api/cogs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Grace",
        spriteSheetKey: "cog-grace",
        vibe: "friendly",
        controllerId: "stub",
        attributes: { energy: 9 },
      }),
    });
    const body = await response.json();

    expect(response.status).toBe(201);
    expect(body.cogId).toMatch(/^cog_/);
    expect(body.snapshot.cogs.some((cog: { name: string }) => cog.name === "Grace")).toBe(true);
  });

  it("returns structured validation errors", async () => {
    const response = await fetch(`${baseUrl}/api/cogs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "" }),
    });
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toBe("Invalid create cog request");
  });
});
```

- [ ] **Step 2: Run API tests to verify missing HTTP module**

Run:

```bash
npm run test -- tests/server/api.test.ts
```

Expected: FAIL with a module resolution error for `src/server/http.js`.

- [ ] **Step 3: Add Express app**

Create `src/server/http.ts`:

```ts
import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { ControllerRegistry } from "./controllers/cog-controller.js";
import type { GridWorld } from "./simulation/world.js";
import { createCogRequestSchema } from "../shared/protocol.js";

export type AppContext = {
  world: GridWorld;
  controllers: ControllerRegistry;
};

export function createApp(context: AppContext): express.Express {
  const app = express();
  app.use(express.json());

  app.get("/health", (_request, response) => {
    response.json({
      ok: true,
      snapshot: context.world.snapshot(),
    });
  });

  app.get("/api/world", (_request, response) => {
    response.json(context.world.snapshot());
  });

  app.post("/api/cogs", (request, response) => {
    const parsed = createCogRequestSchema.safeParse(request.body);
    if (!parsed.success) {
      response.status(400).json({
        error: "Invalid create cog request",
        issues: parsed.error.issues.map((issue) => ({
          path: issue.path.join("."),
          message: issue.message,
        })),
      });
      return;
    }

    const cog = context.world.addCog(parsed.data);
    response.status(201).json({
      cogId: cog.id,
      snapshot: context.world.snapshot(),
    });
  });

  const clientDist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../dist");
  app.use(express.static(clientDist));
  app.get("*", (_request, response) => {
    response.sendFile(path.join(clientDist, "index.html"));
  });

  return app;
}
```

- [ ] **Step 4: Add WebSocket hub and simulation loop**

Create `src/server/websocket.ts`:

```ts
import type { Server } from "node:http";
import { WebSocketServer, WebSocket } from "ws";
import type { CogAction, ServerStatus } from "../shared/types.js";
import type { ServerMessage } from "../shared/protocol.js";
import { isClientMessage } from "../shared/protocol.js";
import type { ControllerRegistry } from "./controllers/cog-controller.js";
import type { GridWorld } from "./simulation/world.js";

export type WorldSocketServer = {
  clientCount(): number;
  broadcast(message: ServerMessage): void;
  close(): void;
};

export function attachWorldSocketServer(options: {
  server: Server;
  world: GridWorld;
  controllers: ControllerRegistry;
  tickMs: number;
}): WorldSocketServer {
  const wss = new WebSocketServer({ server: options.server, path: "/ws" });

  wss.on("connection", (socket) => {
    send(socket, { type: "snapshot", snapshot: options.world.snapshot() });
    send(socket, { type: "serverStatus", status: status(options.world, wss.clients.size) });

    socket.on("message", (raw) => {
      const parsed = parseJson(raw.toString());
      if (isClientMessage(parsed) && parsed.type === "hello") {
        send(socket, { type: "serverStatus", status: status(options.world, wss.clients.size) });
      }
    });
  });

  const timer = setInterval(async () => {
    const snapshot = options.world.snapshot();
    const actions = new Map<string, CogAction>();

    await Promise.all(
      snapshot.cogs.map(async (cog) => {
        const controller = options.controllers[cog.controllerId] ?? options.controllers.stub;
        try {
          const input = {
            tick: snapshot.tick,
            observation: options.world.getObservation(cog.id),
            allowedActions: ["wait", "move", "setVibe", "say"] as CogAction["type"][],
          };
          actions.set(cog.id, await controller.decide(input));
        } catch (error) {
          actions.set(cog.id, {
            type: "wait",
            intent: error instanceof Error ? `controller error: ${error.message}` : "controller error",
          });
        }
      }),
    );

    const nextSnapshot = await options.world.step(actions);
    broadcast({ type: "snapshot", snapshot: nextSnapshot });
    broadcast({ type: "serverStatus", status: status(options.world, wss.clients.size) });
  }, options.tickMs);

  function broadcast(message: ServerMessage): void {
    for (const client of wss.clients) {
      send(client, message);
    }
  }

  return {
    clientCount: () => wss.clients.size,
    broadcast,
    close: () => {
      clearInterval(timer);
      wss.close();
    },
  };
}

function send(socket: WebSocket, message: ServerMessage): void {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
  }
}

function status(world: GridWorld, clientCount: number): ServerStatus {
  const snapshot = world.snapshot();
  return {
    tick: snapshot.tick,
    cogCount: snapshot.cogs.length,
    clientCount,
    controllerMode: "stub",
  };
}

function parseJson(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return undefined;
  }
}
```

Create `src/server/index.ts`:

```ts
import { createServer } from "node:http";
import { createControllerRegistry } from "./controllers/cog-controller.js";
import { createApp } from "./http.js";
import { createSeedWorld } from "./simulation/seed-world.js";
import { attachWorldSocketServer } from "./websocket.js";

const port = Number(process.env.PORT ?? 8787);
const world = createSeedWorld();
const controllers = createControllerRegistry();
const app = createApp({ world, controllers });
const server = createServer(app);

attachWorldSocketServer({
  server,
  world,
  controllers,
  tickMs: 500,
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Cogshambo server listening on http://127.0.0.1:${port}`);
});
```

- [ ] **Step 5: Run API tests**

Run:

```bash
npm run test -- tests/server/api.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit server endpoints**

Run:

```bash
git add src/server tests/server/api.test.ts
git commit -m "feat: add server API and world socket"
```

Expected: a commit containing HTTP API, WebSocket loop, and tests.

---

### Task 6: Client Networking and HUD

**Files:**

- Create: `src/client/net/world-socket.ts`
- Create: `src/client/ui/hud.ts`
- Create: `src/client/main.ts`

- [ ] **Step 1: Add WebSocket client**

Create `src/client/net/world-socket.ts`:

```ts
import type { ClientMessage, ServerMessage } from "../../shared/protocol";
import { isServerMessage } from "../../shared/protocol";

export type WorldSocketHandlers = {
  onMessage(message: ServerMessage): void;
  onStatus(status: "connecting" | "open" | "closed" | "error"): void;
};

export class WorldSocket {
  private socket: WebSocket | undefined;
  private retryMs = 500;

  constructor(private readonly handlers: WorldSocketHandlers) {}

  connect(): void {
    this.handlers.onStatus("connecting");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

    this.socket.addEventListener("open", () => {
      this.retryMs = 500;
      this.handlers.onStatus("open");
      this.send({ type: "hello", clientName: "browser" });
    });

    this.socket.addEventListener("message", (event) => {
      const parsed = parseJson(event.data);
      if (isServerMessage(parsed)) {
        this.handlers.onMessage(parsed);
      }
    });

    this.socket.addEventListener("close", () => {
      this.handlers.onStatus("closed");
      window.setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 1.5, 5_000);
    });

    this.socket.addEventListener("error", () => {
      this.handlers.onStatus("error");
    });
  }

  send(message: ClientMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }
}

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") {
    return undefined;
  }

  try {
    return JSON.parse(value);
  } catch {
    return undefined;
  }
}
```

- [ ] **Step 2: Add compact HUD**

Create `src/client/ui/hud.ts`:

```ts
import type { ServerStatus, WorldSnapshot } from "../../shared/types";

export type HudState = {
  connection: "connecting" | "open" | "closed" | "error";
  snapshot: WorldSnapshot | undefined;
  serverStatus: ServerStatus | undefined;
  selectedCogId: string | undefined;
  perceptionEnabled: boolean;
};

export type HudActions = {
  spawnCog(): void;
  togglePerception(): void;
  selectNextCog(): void;
};

export class Hud {
  private state: HudState = {
    connection: "connecting",
    snapshot: undefined,
    serverStatus: undefined,
    selectedCogId: undefined,
    perceptionEnabled: true,
  };

  constructor(
    private readonly root: HTMLElement,
    private readonly actions: HudActions,
  ) {}

  update(next: Partial<HudState>): void {
    this.state = { ...this.state, ...next };
    this.render();
  }

  selectedCogId(): string | undefined {
    return this.state.selectedCogId;
  }

  private render(): void {
    const snapshot = this.state.snapshot;
    const selectedCog =
      snapshot?.cogs.find((cog) => cog.id === this.state.selectedCogId) ?? snapshot?.cogs[0];

    if (!this.state.selectedCogId && selectedCog) {
      this.state.selectedCogId = selectedCog.id;
    }

    this.root.innerHTML = `
      <div class="hud-panel">
        <div class="hud-row">
          <span class="hud-label">Connection</span>
          <span class="hud-value">${this.state.connection}</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">Tick</span>
          <span class="hud-value">${snapshot?.tick ?? "-"}</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">Cogs</span>
          <span class="hud-value">${snapshot?.cogs.length ?? 0}</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">Selected</span>
          <span class="hud-value">${selectedCog ? `${selectedCog.name} / ${selectedCog.vibe}` : "-"}</span>
        </div>
        <div class="hud-row">
          <button class="hud-button" data-action="spawn">Spawn cog</button>
          <button class="hud-button" data-action="next">Next cog</button>
          <button class="hud-button" data-action="perception">${this.state.perceptionEnabled ? "Hide radius" : "Show radius"}</button>
        </div>
      </div>
    `;

    this.root.querySelector<HTMLButtonElement>('[data-action="spawn"]')?.addEventListener("click", () => this.actions.spawnCog());
    this.root.querySelector<HTMLButtonElement>('[data-action="next"]')?.addEventListener("click", () => this.actions.selectNextCog());
    this.root.querySelector<HTMLButtonElement>('[data-action="perception"]')?.addEventListener("click", () => this.actions.togglePerception());
  }
}
```

- [ ] **Step 3: Add temporary client boot without renderer**

Create `src/client/main.ts`:

```ts
import "./ui/styles.css";
import type { ServerMessage } from "../shared/protocol";
import type { WorldSnapshot } from "../shared/types";
import { WorldSocket } from "./net/world-socket";
import { Hud } from "./ui/hud";

const canvas = document.querySelector<HTMLCanvasElement>("#world-canvas");
const hudRoot = document.querySelector<HTMLElement>("#hud");

if (!canvas || !hudRoot) {
  throw new Error("Cogshambo DOM shell is missing");
}

let snapshot: WorldSnapshot | undefined;
let selectedCogId: string | undefined;
let perceptionEnabled = true;

const hud = new Hud(hudRoot, {
  spawnCog: async () => {
    const index = (snapshot?.cogs.length ?? 0) + 1;
    await fetch("/api/cogs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: `Cog ${index}`,
        spriteSheetKey: "cog-default",
        controllerId: "wander",
        vibe: "curious",
        attributes: { energy: 5, focus: 5 },
      }),
    });
  },
  togglePerception: () => {
    perceptionEnabled = !perceptionEnabled;
    hud.update({ perceptionEnabled });
  },
  selectNextCog: () => {
    if (!snapshot?.cogs.length) {
      return;
    }

    const currentIndex = snapshot.cogs.findIndex((cog) => cog.id === selectedCogId);
    selectedCogId = snapshot.cogs[(currentIndex + 1) % snapshot.cogs.length].id;
    hud.update({ selectedCogId });
  },
});

const socket = new WorldSocket({
  onStatus: (connection) => hud.update({ connection }),
  onMessage: handleMessage,
});

socket.connect();

function handleMessage(message: ServerMessage): void {
  if (message.type === "snapshot") {
    snapshot = message.snapshot;
    selectedCogId ??= snapshot.cogs[0]?.id;
    hud.update({ snapshot, selectedCogId });
  }

  if (message.type === "serverStatus") {
    hud.update({ serverStatus: message.status });
  }
}
```

- [ ] **Step 4: Run build and expect server-only import issues if present**

Run:

```bash
npm run build
```

Expected: PASS. If TypeScript reports missing `.js` extensions in server files, update server-side relative imports to include `.js`; client-side Vite imports can remain extensionless.

- [ ] **Step 5: Commit client networking and HUD**

Run:

```bash
git add src/client
git commit -m "feat: add client socket and hud"
```

Expected: a commit containing browser networking and HUD files.

---

### Task 7: Native WebGPU Board Renderer

**Files:**

- Create: `src/client/render/atlas.ts`
- Create: `src/client/render/camera.ts`
- Create: `src/client/render/shaders.ts`
- Create: `src/client/render/webgpu-board-renderer.ts`
- Modify: `src/client/main.ts`

- [ ] **Step 1: Add renderer support files**

Create `src/client/render/atlas.ts`:

```ts
export type AtlasEntry = {
  key: string;
  color: [number, number, number, number];
};

export const atlasEntries: AtlasEntry[] = [
  { key: "tile", color: [0.08, 0.13, 0.14, 1] },
  { key: "tile-alt", color: [0.1, 0.16, 0.17, 1] },
  { key: "cog-default", color: [0.24, 0.88, 0.68, 1] },
  { key: "cog-ada", color: [0.45, 0.66, 1, 1] },
  { key: "cog-babbage", color: [0.96, 0.74, 0.28, 1] },
  { key: "cog-mira", color: [0.86, 0.47, 1, 1] },
  { key: "rock", color: [0.42, 0.47, 0.48, 1] },
  { key: "crate", color: [0.7, 0.42, 0.2, 1] },
  { key: "berry", color: [0.92, 0.18, 0.34, 1] },
  { key: "beacon", color: [0.72, 0.95, 0.34, 1] },
  { key: "radius", color: [0.24, 0.6, 1, 0.24] },
];

export function colorForKey(key: string): [number, number, number, number] {
  return atlasEntries.find((entry) => entry.key === key)?.color ?? atlasEntries[2].color;
}
```

Create `src/client/render/camera.ts`:

```ts
import type { Position, WorldDimensions } from "../../shared/types";

export type BoardCamera = {
  zoom: number;
  offsetX: number;
  offsetY: number;
};

export function createBoardCamera(): BoardCamera {
  return {
    zoom: 28,
    offsetX: 0,
    offsetY: 0,
  };
}

export function centerCameraOnBoard(camera: BoardCamera, dimensions: WorldDimensions, canvas: HTMLCanvasElement): void {
  camera.offsetX = canvas.width / 2 - (dimensions.width * camera.zoom) / 2;
  camera.offsetY = canvas.height / 2 - (dimensions.height * camera.zoom) / 2;
}

export function boardToClip(position: Position, camera: BoardCamera, canvas: HTMLCanvasElement): [number, number] {
  const pixelX = camera.offsetX + position.x * camera.zoom;
  const pixelY = camera.offsetY + position.y * camera.zoom;
  return [(pixelX / canvas.width) * 2 - 1, 1 - (pixelY / canvas.height) * 2];
}
```

Create `src/client/render/shaders.ts`:

```ts
export const boardShader = `
struct VertexInput {
  @location(0) corner: vec2<f32>,
  @location(1) center: vec2<f32>,
  @location(2) size: vec2<f32>,
  @location(3) color: vec4<f32>,
};

struct VertexOutput {
  @builtin(position) position: vec4<f32>,
  @location(0) color: vec4<f32>,
};

@vertex
fn vertexMain(input: VertexInput) -> VertexOutput {
  var output: VertexOutput;
  let xy = input.center + input.corner * input.size;
  output.position = vec4<f32>(xy, 0.0, 1.0);
  output.color = input.color;
  return output;
}

@fragment
fn fragmentMain(input: VertexOutput) -> @location(0) vec4<f32> {
  return input.color;
}
`;
```

- [ ] **Step 2: Add WebGPU renderer**

Create `src/client/render/webgpu-board-renderer.ts`:

```ts
import type { Cog, Position, WorldSnapshot } from "../../shared/types";
import { colorForKey } from "./atlas";
import { boardShader } from "./shaders";

type Instance = {
  center: [number, number];
  size: [number, number];
  color: [number, number, number, number];
};

export type RenderOptions = {
  selectedCogId: string | undefined;
  perceptionEnabled: boolean;
};

export class WebGpuBoardRenderer {
  private device: GPUDevice | undefined;
  private context: GPUCanvasContext | undefined;
  private pipeline: GPURenderPipeline | undefined;
  private vertexBuffer: GPUBuffer | undefined;
  private instanceBuffer: GPUBuffer | undefined;
  private format: GPUTextureFormat | undefined;

  constructor(private readonly canvas: HTMLCanvasElement) {}

  async initialize(): Promise<void> {
    if (!navigator.gpu) {
      throw new Error("WebGPU is not available in this browser");
    }

    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) {
      throw new Error("No WebGPU adapter is available");
    }

    this.device = await adapter.requestDevice();
    this.context = this.canvas.getContext("webgpu") ?? undefined;
    if (!this.context) {
      throw new Error("Could not create WebGPU canvas context");
    }

    this.format = navigator.gpu.getPreferredCanvasFormat();
    this.context.configure({
      device: this.device,
      format: this.format,
      alphaMode: "opaque",
    });

    const shader = this.device.createShaderModule({ code: boardShader });
    this.pipeline = this.device.createRenderPipeline({
      layout: "auto",
      vertex: {
        module: shader,
        entryPoint: "vertexMain",
        buffers: [
          {
            arrayStride: 8,
            attributes: [{ shaderLocation: 0, offset: 0, format: "float32x2" }],
          },
          {
            arrayStride: 32,
            stepMode: "instance",
            attributes: [
              { shaderLocation: 1, offset: 0, format: "float32x2" },
              { shaderLocation: 2, offset: 8, format: "float32x2" },
              { shaderLocation: 3, offset: 16, format: "float32x4" },
            ],
          },
        ],
      },
      fragment: {
        module: shader,
        entryPoint: "fragmentMain",
        targets: [{ format: this.format }],
      },
      primitive: {
        topology: "triangle-strip",
      },
    });

    this.vertexBuffer = this.device.createBuffer({
      size: 32,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    });
    this.device.queue.writeBuffer(this.vertexBuffer, 0, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]));
  }

  resize(): void {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.floor(this.canvas.clientWidth * ratio);
    const height = Math.floor(this.canvas.clientHeight * ratio);
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
  }

  render(snapshot: WorldSnapshot | undefined, options: RenderOptions): void {
    if (!this.device || !this.context || !this.pipeline || !this.vertexBuffer || !snapshot) {
      return;
    }

    this.resize();
    const instances = this.createInstances(snapshot, options);
    const data = new Float32Array(instances.length * 8);
    instances.forEach((instance, index) => {
      const offset = index * 8;
      data.set(instance.center, offset);
      data.set(instance.size, offset + 2);
      data.set(instance.color, offset + 4);
    });

    const requiredBytes = Math.max(data.byteLength, 32);
    if (!this.instanceBuffer || this.instanceBuffer.size < requiredBytes) {
      this.instanceBuffer?.destroy();
      this.instanceBuffer = this.device.createBuffer({
        size: requiredBytes,
        usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
      });
    }

    this.device.queue.writeBuffer(this.instanceBuffer, 0, data);

    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: this.context.getCurrentTexture().createView(),
          loadOp: "clear",
          storeOp: "store",
          clearValue: { r: 0.04, g: 0.06, b: 0.065, a: 1 },
        },
      ],
    });

    pass.setPipeline(this.pipeline);
    pass.setVertexBuffer(0, this.vertexBuffer);
    pass.setVertexBuffer(1, this.instanceBuffer);
    pass.draw(4, instances.length);
    pass.end();
    this.device.queue.submit([encoder.finish()]);
  }

  private createInstances(snapshot: WorldSnapshot, options: RenderOptions): Instance[] {
    const tileWidth = 1.72 / snapshot.dimensions.width;
    const tileHeight = 1.72 / snapshot.dimensions.height;
    const x0 = -0.86;
    const y0 = 0.86;
    const instances: Instance[] = [];

    for (let y = 0; y < snapshot.dimensions.height; y += 1) {
      for (let x = 0; x < snapshot.dimensions.width; x += 1) {
        instances.push({
          center: [x0 + x * tileWidth + tileWidth / 2, y0 - y * tileHeight - tileHeight / 2],
          size: [tileWidth * 0.46, tileHeight * 0.46],
          color: colorForKey((x + y) % 2 === 0 ? "tile" : "tile-alt"),
        });
      }
    }

    const selectedCog = snapshot.cogs.find((cog) => cog.id === options.selectedCogId);
    if (options.perceptionEnabled && selectedCog) {
      for (const cell of cellsInRadius(selectedCog.position, snapshot.dimensions.width, snapshot.dimensions.height, 5)) {
        instances.push({
          center: [x0 + cell.x * tileWidth + tileWidth / 2, y0 - cell.y * tileHeight - tileHeight / 2],
          size: [tileWidth * 0.48, tileHeight * 0.48],
          color: colorForKey("radius"),
        });
      }
    }

    for (const object of snapshot.objects) {
      instances.push({
        center: [x0 + object.position.x * tileWidth + tileWidth / 2, y0 - object.position.y * tileHeight - tileHeight / 2],
        size: [tileWidth * 0.36, tileHeight * 0.36],
        color: colorForKey(object.spriteKey),
      });
    }

    for (const cog of snapshot.cogs) {
      const color = colorForCog(cog, cog.id === options.selectedCogId);
      instances.push({
        center: [x0 + cog.position.x * tileWidth + tileWidth / 2, y0 - cog.position.y * tileHeight - tileHeight / 2],
        size: [tileWidth * 0.42, tileHeight * 0.42],
        color,
      });
    }

    return instances;
  }
}

function colorForCog(cog: Cog, selected: boolean): [number, number, number, number] {
  if (selected) {
    return [1, 1, 1, 1];
  }

  return colorForKey(cog.spriteSheetKey);
}

function cellsInRadius(origin: Position, width: number, height: number, radius: number): Position[] {
  const cells: Position[] = [];
  for (let y = Math.max(0, origin.y - radius); y <= Math.min(height - 1, origin.y + radius); y += 1) {
    for (let x = Math.max(0, origin.x - radius); x <= Math.min(width - 1, origin.x + radius); x += 1) {
      const dx = x - origin.x;
      const dy = y - origin.y;
      if (dx * dx + dy * dy <= radius * radius) {
        cells.push({ x, y });
      }
    }
  }
  return cells;
}
```

- [ ] **Step 3: Wire renderer into main**

Replace `src/client/main.ts` with:

```ts
import "./ui/styles.css";
import type { ServerMessage } from "../shared/protocol";
import type { WorldSnapshot } from "../shared/types";
import { WorldSocket } from "./net/world-socket";
import { WebGpuBoardRenderer } from "./render/webgpu-board-renderer";
import { Hud } from "./ui/hud";

const canvas = document.querySelector<HTMLCanvasElement>("#world-canvas");
const hudRoot = document.querySelector<HTMLElement>("#hud");

if (!canvas || !hudRoot) {
  throw new Error("Cogshambo DOM shell is missing");
}

let snapshot: WorldSnapshot | undefined;
let selectedCogId: string | undefined;
let perceptionEnabled = true;

const renderer = new WebGpuBoardRenderer(canvas);
const hud = new Hud(hudRoot, {
  spawnCog: async () => {
    const index = (snapshot?.cogs.length ?? 0) + 1;
    await fetch("/api/cogs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: `Cog ${index}`,
        spriteSheetKey: "cog-default",
        controllerId: "wander",
        vibe: "curious",
        attributes: { energy: 5, focus: 5 },
      }),
    });
  },
  togglePerception: () => {
    perceptionEnabled = !perceptionEnabled;
    hud.update({ perceptionEnabled });
  },
  selectNextCog: () => {
    if (!snapshot?.cogs.length) {
      return;
    }

    const currentIndex = snapshot.cogs.findIndex((cog) => cog.id === selectedCogId);
    selectedCogId = snapshot.cogs[(currentIndex + 1) % snapshot.cogs.length].id;
    hud.update({ selectedCogId });
  },
});

renderer
  .initialize()
  .then(() => {
    const socket = new WorldSocket({
      onStatus: (connection) => hud.update({ connection }),
      onMessage: handleMessage,
    });
    socket.connect();
    requestAnimationFrame(frame);
  })
  .catch((error: unknown) => {
    document.body.innerHTML = `<main class="fallback"><p>${error instanceof Error ? error.message : "WebGPU initialization failed"}</p></main>`;
  });

function handleMessage(message: ServerMessage): void {
  if (message.type === "snapshot") {
    snapshot = message.snapshot;
    selectedCogId ??= snapshot.cogs[0]?.id;
    hud.update({ snapshot, selectedCogId });
  }

  if (message.type === "serverStatus") {
    hud.update({ serverStatus: message.status });
  }
}

function frame(): void {
  renderer.render(snapshot, {
    selectedCogId,
    perceptionEnabled,
  });
  requestAnimationFrame(frame);
}
```

- [ ] **Step 4: Run build**

Run:

```bash
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit WebGPU renderer**

Run:

```bash
git add src/client
git commit -m "feat: render WebGPU sprite board"
```

Expected: a commit containing the renderer and main wiring.

---

### Task 8: Smoke Test and End-to-End Verification

**Files:**

- Create: `tests/smoke/client.spec.ts`
- Modify: `package.json`

- [ ] **Step 1: Add smoke test**

Create `tests/smoke/client.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("client boots and shows the HUD", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("#world-canvas")).toBeVisible();
  await expect(page.locator("#hud")).toContainText("Connection");

  const webgpuAvailable = await page.evaluate(() => Boolean(navigator.gpu));
  if (webgpuAvailable) {
    await expect(page.locator(".fallback")).toHaveCount(0);
  } else {
    await expect(page.locator(".fallback")).toContainText("WebGPU");
  }
});
```

- [ ] **Step 2: Update smoke script to run against the full server**

Modify `package.json` scripts:

```json
{
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "dev:server": "tsx watch src/server/index.ts",
    "build": "tsc -p tsconfig.node.json && vite build",
    "start": "node dist-server/server/index.js",
    "test": "vitest run",
    "test:watch": "vitest",
    "smoke": "npm run build && node dist-server/server/index.js",
    "check": "npm run test && npm run build"
  }
}
```

Do not run `npm run smoke` after this script edit because it starts a long-running server. Use the manual verification steps below instead.

- [ ] **Step 3: Run test and build checks**

Run:

```bash
npm run test
npm run build
```

Expected: both commands PASS.

- [ ] **Step 4: Manually run server for verification**

Run:

```bash
PORT=8787 npm run start
```

Expected: terminal prints `Cogshambo server listening on http://127.0.0.1:8787`. Keep this process running while doing the next checks.

- [ ] **Step 5: Verify health and cog creation in another terminal**

Run:

```bash
curl -s http://127.0.0.1:8787/health
curl -s -X POST http://127.0.0.1:8787/api/cogs \
  -H 'content-type: application/json' \
  -d '{"name":"Smoke","spriteSheetKey":"cog-default","controllerId":"stub","vibe":"curious","attributes":{"energy":5}}'
```

Expected: first response contains `"ok":true`; second response contains a `"cogId"` that starts with `"cog_"`.

- [ ] **Step 6: Browser check**

Open:

```text
http://127.0.0.1:8787
```

Expected when WebGPU is available: a dark chunky board renders with cogs and objects, the HUD shows connection/tick/cog count, and clicking `Spawn cog` increases the cog count after the next snapshot.

Expected when WebGPU is unavailable: the page shows a clear WebGPU fallback message.

- [ ] **Step 7: Stop the verification server**

Press `Ctrl-C` in the server terminal.

Expected: the server process exits.

- [ ] **Step 8: Commit verification**

Run:

```bash
git add package.json tests/smoke/client.spec.ts
git commit -m "test: add first playable smoke coverage"
```

Expected: a commit containing smoke coverage and package script updates.

---

## Final Verification

Run:

```bash
npm run check
git status --short
```

Expected:

- `npm run test` passes.
- `npm run build` passes.
- `git status --short` shows no tracked-file changes.
- `.superpowers/` may exist locally but remains ignored by `.gitignore`.

Then push:

```bash
git push origin main
```

Expected: all first-playable implementation commits are on `origin/main`.

---

## Self-Review

Spec coverage:

- Native WebGPU renderer: Task 7.
- Chunky sprite-board style: Task 7.
- Server-authoritative simulation: Tasks 3 and 5.
- WebSocket snapshots: Task 5 and Task 6.
- `POST /api/cogs`: Task 5.
- Perception radius 5: Task 3.
- Bump interactions and vibe effects: Task 3.
- LLM-ready controller interface with stub default: Task 4.
- DOM HUD and debug spawn control: Task 6.
- WebGPU fallback message: Task 7.
- Unit and smoke tests: Tasks 2, 3, 4, 5, and 8.

Placeholder scan:

- The plan contains no incomplete sections.
- The only intentionally simple content is the starter atlas color renderer in Task 7; it is a complete first implementation and can be replaced by sprite textures later without changing simulation or protocol contracts.

Type consistency:

- Shared `CogAction`, `CogDecisionInput`, `WorldSnapshot`, and `ServerMessage` names are defined in Task 2 and reused consistently in later tasks.
- Server-side NodeNext imports include `.js` suffixes where TypeScript emits ESM.
- Client-side Vite imports are extensionless and stay within client/shared modules.
