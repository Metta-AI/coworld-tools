import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { initializeCogshamboDatabase } from "../../src/server/init-db.js";
import { createSeedWorld } from "../../src/server/simulation/seed-world.js";
import { createSqliteWorldStateStore } from "../../src/server/world-state-store.js";

describe("database initialization", () => {
  it("resets persisted world state to tick 0 with the requested cog count", async () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-init-db-"));
    const dbPath = path.join(tempDir, "cogshambo.sqlite");
    try {
      const dirtyWorld = createSeedWorld({ debateDoubt: 31 }, { cogCount: 12 });
      const ada = dirtyWorld.snapshot().cogs.find((cog) => cog.name === "Ada");
      if (!ada) {
        throw new Error("Expected Ada in dirty seed world");
      }
      await dirtyWorld.step(new Map([[ada.id, { type: "move", roomId: "green_room" }]]));

      const dirtyStore = createSqliteWorldStateStore(dbPath);
      dirtyStore.save(dirtyWorld);
      dirtyStore.close();

      const result = initializeCogshamboDatabase({ sqlitePath: dbPath, cogCount: 20 });
      const cleanStore = createSqliteWorldStateStore(dbPath);
      const restored = cleanStore.load();
      cleanStore.close();

      expect(result).toEqual({ sqlitePath: dbPath, tick: 0, cogCount: 20 });
      expect(restored?.snapshot().tick).toBe(0);
      expect(restored?.snapshot().cogs).toHaveLength(20);
      expect(restored?.snapshot().recentEvents.every((event) => event.tick === 0)).toBe(true);
    } finally {
      rmSync(tempDir, { recursive: true, force: true });
    }
  });
});
