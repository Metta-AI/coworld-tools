import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import type { DatabaseSync as DatabaseSyncType } from "node:sqlite";

import { GridWorld, type GridWorldState } from "./simulation/world.js";
import { resolveCogshamboSqlitePath } from "./session-defaults.js";

export type WorldStateStore = {
  load(): GridWorld | undefined;
  save(world: GridWorld): void;
  close(): void;
};

type WorldStateRow = {
  state_json: string;
};

export function createSqliteWorldStateStore(dbPath = defaultWorldStateDbPath()): WorldStateStore {
  if (dbPath !== ":memory:") {
    mkdirSync(path.dirname(dbPath), { recursive: true });
  }

  const database = new DatabaseSync(dbPath);
  database.exec(`
    CREATE TABLE IF NOT EXISTS world_state (
      id TEXT PRIMARY KEY CHECK (id = 'current'),
      state_json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
  `);

  return {
    load() {
      const row = database
        .prepare("SELECT state_json FROM world_state WHERE id = 'current'")
        .get() as WorldStateRow | undefined;
      return row ? GridWorld.fromState(JSON.parse(row.state_json) as GridWorldState) : undefined;
    },
    save(world) {
      database
        .prepare(`
          INSERT INTO world_state (id, state_json, updated_at)
          VALUES ('current', ?, ?)
          ON CONFLICT(id) DO UPDATE SET
            state_json = excluded.state_json,
            updated_at = excluded.updated_at
        `)
        .run(JSON.stringify(world.exportState()), new Date().toISOString());
    },
    close() {
      database.close();
    },
  };
}

function defaultWorldStateDbPath(): string {
  return resolveCogshamboSqlitePath(undefined);
}

const require = createRequire(import.meta.url);
const { DatabaseSync } = require("node:sqlite") as { DatabaseSync: new (filename: string) => DatabaseSyncType };
