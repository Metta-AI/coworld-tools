import { describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { createSqliteSettingsStore } from "../../src/server/settings-store.js";

describe("sqlite settings store", () => {
  it("persists the default preset and uses it as the current settings db", () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-settings-"));
    const dbPath = path.join(tempDir, "settings.sqlite");
    const store = createSqliteSettingsStore(dbPath);

    const state = store.load();

    expect(state.settingsDb).toBe("default");
    expect(state.config.conversionThreshold).toBe(100);
    expect(state.presets).toEqual([
      expect.objectContaining({
        settingsDb: "default",
        name: "Default",
      }),
    ]);

    store.close();
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("saves current config edits and reloads them from sqlite", () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-settings-"));
    const dbPath = path.join(tempDir, "settings.sqlite");
    const store = createSqliteSettingsStore(dbPath);

    store.saveCurrentConfig({
      debateDoubt: 31,
      traitConfig: {
        contrarian: {
          overwhelmingTeamThreshold: 0.95,
        },
      },
    });
    store.close();

    const reloaded = createSqliteSettingsStore(dbPath);
    const state = reloaded.load();

    expect(state.settingsDb).toBe("default");
    expect(state.config.debateDoubt).toBe(31);
    expect(state.config.traitConfig.contrarian.overwhelmingTeamThreshold).toBe(0.95);

    reloaded.close();
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("creates and selects a new preset copied from current settings", () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-settings-"));
    const dbPath = path.join(tempDir, "settings.sqlite");
    const store = createSqliteSettingsStore(dbPath);

    store.saveCurrentConfig({ debateDoubt: 42 });
    const created = store.createPreset("Fast Certainty");

    expect(created.settingsDb).toBe("fast-certainty");
    expect(created.config.debateDoubt).toBe(42);
    expect(store.load().settingsDb).toBe("fast-certainty");

    store.selectPreset("default");
    expect(store.load().settingsDb).toBe("default");
    expect(store.load().config.debateDoubt).toBe(42);

    store.close();
    rmSync(tempDir, { recursive: true, force: true });
  });
});
