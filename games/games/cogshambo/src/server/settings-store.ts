import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import type { DatabaseSync as DatabaseSyncType } from "node:sqlite";

import {
  cloneGameConfig,
  DEFAULT_GAME_CONFIG,
  normalizeGameConfig,
  type GameConfig,
  type GameConfigInput,
  type TraitConfig,
  type TraitConfigInput,
} from "../shared/rules.js";
import { resolveCogshamboSqlitePath } from "./session-defaults.js";

export type SettingsPreset = {
  settingsDb: string;
  name: string;
  config: GameConfig;
  updatedAt: string;
};

export type SettingsState = {
  settingsDb: string;
  config: GameConfig;
  presets: SettingsPreset[];
};

export type SettingsStore = {
  load(): SettingsState;
  saveCurrentConfig(input: GameConfigInput): SettingsState;
  createPreset(name: string): SettingsState;
  selectPreset(settingsDb: string): SettingsState;
  close(): void;
};

type PresetRow = {
  settings_db: string;
  name: string;
  config_json: string;
  updated_at: string;
};

type StateRow = {
  current_settings_db: string;
};

const DEFAULT_SETTINGS_DB = "default";
const DEFAULT_SETTINGS_NAME = "Default";

export function createSqliteSettingsStore(dbPath = defaultSettingsDbPath()): SettingsStore {
  if (dbPath !== ":memory:") {
    mkdirSync(path.dirname(dbPath), { recursive: true });
  }
  const database = new DatabaseSync(dbPath);
  database.exec(`
    CREATE TABLE IF NOT EXISTS settings_presets (
      settings_db TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      config_json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS settings_state (
      id TEXT PRIMARY KEY CHECK (id = 'current'),
      current_settings_db TEXT NOT NULL REFERENCES settings_presets(settings_db)
    );
  `);

  ensureDefaultPreset(database);

  return {
    load() {
      return loadState(database);
    },
    saveCurrentConfig(input) {
      const state = loadState(database);
      const nextConfig = normalizeGameConfig({
        ...state.config,
        ...input,
        traitConfig: mergeTraitConfigInput(state.config.traitConfig, input.traitConfig),
      });
      savePresetConfig(database, state.settingsDb, nextConfig);
      return loadState(database);
    },
    createPreset(name) {
      const state = loadState(database);
      const presetName = normalizePresetName(name);
      const settingsDb = uniqueSettingsDb(database, slugify(presetName));
      const updatedAt = new Date().toISOString();
      database
        .prepare(`
          INSERT INTO settings_presets (settings_db, name, config_json, updated_at)
          VALUES (?, ?, ?, ?)
        `)
        .run(settingsDb, presetName, JSON.stringify(state.config), updatedAt);
      setCurrentSettingsDb(database, settingsDb);
      return loadState(database);
    },
    selectPreset(settingsDb) {
      const preset = presetRow(database, settingsDb);
      if (!preset) {
        throw new Error(`Unknown settings preset: ${settingsDb}`);
      }

      setCurrentSettingsDb(database, preset.settings_db);
      return loadState(database);
    },
    close() {
      database.close();
    },
  };
}

function ensureDefaultPreset(database: DatabaseSyncType): void {
  const now = new Date().toISOString();
  database
    .prepare(`
      INSERT INTO settings_presets (settings_db, name, config_json, updated_at)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(settings_db) DO NOTHING
    `)
    .run(DEFAULT_SETTINGS_DB, DEFAULT_SETTINGS_NAME, JSON.stringify(DEFAULT_GAME_CONFIG), now);
  database
    .prepare(`
      INSERT INTO settings_state (id, current_settings_db)
      VALUES ('current', ?)
      ON CONFLICT(id) DO NOTHING
    `)
    .run(DEFAULT_SETTINGS_DB);
}

function loadState(database: DatabaseSyncType): SettingsState {
  const currentSettingsDb = currentSettingsDbRow(database)?.current_settings_db ?? DEFAULT_SETTINGS_DB;
  const currentRow = presetRow(database, currentSettingsDb) ?? presetRow(database, DEFAULT_SETTINGS_DB);
  if (!currentRow) {
    throw new Error("Missing default settings preset");
  }

  if (currentRow.settings_db !== currentSettingsDb) {
    setCurrentSettingsDb(database, currentRow.settings_db);
  }

  return {
    settingsDb: currentRow.settings_db,
    config: configFromRow(currentRow),
    presets: presetRows(database).map(presetFromRow),
  };
}

function savePresetConfig(database: DatabaseSyncType, settingsDb: string, config: GameConfig): void {
  database
    .prepare(`
      UPDATE settings_presets
      SET config_json = ?, updated_at = ?
      WHERE settings_db = ?
    `)
    .run(JSON.stringify(config), new Date().toISOString(), settingsDb);
}

function currentSettingsDbRow(database: DatabaseSyncType): StateRow | undefined {
  return database
    .prepare("SELECT current_settings_db FROM settings_state WHERE id = 'current'")
    .get() as StateRow | undefined;
}

function presetRow(database: DatabaseSyncType, settingsDb: string): PresetRow | undefined {
  return database
    .prepare("SELECT settings_db, name, config_json, updated_at FROM settings_presets WHERE settings_db = ?")
    .get(settingsDb) as PresetRow | undefined;
}

function presetRows(database: DatabaseSyncType): PresetRow[] {
  return database
    .prepare("SELECT settings_db, name, config_json, updated_at FROM settings_presets ORDER BY settings_db = 'default' DESC, name ASC")
    .all() as PresetRow[];
}

function presetFromRow(row: PresetRow): SettingsPreset {
  return {
    settingsDb: row.settings_db,
    name: row.name,
    config: configFromRow(row),
    updatedAt: row.updated_at,
  };
}

function configFromRow(row: PresetRow): GameConfig {
  return normalizeGameConfig(JSON.parse(row.config_json) as GameConfigInput);
}

function setCurrentSettingsDb(database: DatabaseSyncType, settingsDb: string): void {
  database
    .prepare(`
      INSERT INTO settings_state (id, current_settings_db)
      VALUES ('current', ?)
      ON CONFLICT(id) DO UPDATE SET current_settings_db = excluded.current_settings_db
    `)
    .run(settingsDb);
}

function normalizePresetName(name: string): string {
  const normalized = name.trim().replace(/\s+/g, " ");
  return normalized || "Untitled Settings";
}

function uniqueSettingsDb(database: DatabaseSyncType, baseSettingsDb: string): string {
  let candidate = baseSettingsDb || "settings";
  let suffix = 2;
  while (presetRow(database, candidate)) {
    candidate = `${baseSettingsDb}-${suffix}`;
    suffix += 1;
  }
  return candidate;
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || "settings";
}

function mergeTraitConfigInput(base: TraitConfig, input: TraitConfigInput | undefined): TraitConfig {
  return Object.fromEntries(
    Object.entries(base).map(([traitId, traitConfig]) => [
      traitId,
      {
        ...traitConfig,
        ...(input?.[traitId as keyof TraitConfig] ?? {}),
      },
    ]),
  ) as TraitConfig;
}

function defaultSettingsDbPath(): string {
  return resolveCogshamboSqlitePath(undefined);
}

const require = createRequire(import.meta.url);
const { DatabaseSync } = require("node:sqlite") as { DatabaseSync: new (filename: string) => DatabaseSyncType };
