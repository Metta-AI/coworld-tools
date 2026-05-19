import { createSqliteSettingsStore } from "./settings-store.js";
import { resolveCogshamboSqlitePath } from "./session-defaults.js";
import { createSeedWorld } from "./simulation/seed-world.js";
import { createSqliteWorldStateStore } from "./world-state-store.js";

export type InitializeCogshamboDatabaseOptions = {
  sqlitePath?: string;
  cogCount?: number;
};

export type InitializeCogshamboDatabaseResult = {
  sqlitePath: string;
  tick: number;
  cogCount: number;
};

const DEFAULT_COG_COUNT = 20;

export function initializeCogshamboDatabase(
  options: InitializeCogshamboDatabaseOptions = {},
): InitializeCogshamboDatabaseResult {
  const sqlitePath = resolveCogshamboSqlitePath(options.sqlitePath);
  const settingsStore = createSqliteSettingsStore(sqlitePath);
  const worldStateStore = createSqliteWorldStateStore(sqlitePath);
  try {
    const world = createSeedWorld(settingsStore.load().config, {
      cogCount: options.cogCount ?? DEFAULT_COG_COUNT,
    });
    worldStateStore.save(world);
    const snapshot = world.snapshot();
    return {
      sqlitePath,
      tick: snapshot.tick,
      cogCount: snapshot.cogs.length,
    };
  } finally {
    settingsStore.close();
    worldStateStore.close();
  }
}
