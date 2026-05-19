import path from "node:path";
import { describe, expect, it } from "vitest";

import { currentCodexSessionId, resolveCogshamboSqlitePath } from "../../src/server/session-defaults.js";

describe("session defaults", () => {
  it("keeps the historical sqlite default outside Codex sessions", () => {
    expect(resolveCogshamboSqlitePath(undefined, {})).toBe(path.resolve("data/cogshambo.sqlite"));
  });

  it("derives a stable sqlite database path from the current Codex tab", () => {
    const first = resolveCogshamboSqlitePath(undefined, {
      CODEX_THREAD_ID: "019e27ad-0c55-75d0-b35f-f7902f288afc",
    });
    const second = resolveCogshamboSqlitePath(undefined, {
      CODEX_THREAD_ID: "019e27ad-0c55-75d0-b35f-f7902f288afc",
    });
    const other = resolveCogshamboSqlitePath(undefined, {
      CODEX_THREAD_ID: "019e27ca-6a4e-790b-bc80-a72bc261da35",
    });

    expect(first).toBe(second);
    expect(first).toBe(path.resolve("data/codex-tabs/019e27ad-0c55-75d0-b35f-f7902f288afc.sqlite"));
    expect(other).toBe(path.resolve("data/codex-tabs/019e27ca-6a4e-790b-bc80-a72bc261da35.sqlite"));
    expect(first).not.toBe(other);
  });

  it("derives a sqlite database path from the Codex terminal tty when no thread id is exported", () => {
    expect(
      resolveCogshamboSqlitePath(undefined, { CODEX_SHELL: "1" }, { terminalPath: "/dev/ttys024" }),
    ).toBe(path.resolve("data/codex-tabs/codex-shell-ttys024.sqlite"));
  });

  it("uses the explicit Cogshambo session id before the Codex thread id", () => {
    expect(
      currentCodexSessionId({
        COGSHAMBO_SESSION_ID: "manual/session",
        CODEX_THREAD_ID: "codex-thread",
      }),
    ).toBe("manual/session");
    expect(
      resolveCogshamboSqlitePath(undefined, {
        COGSHAMBO_SESSION_ID: "manual/session",
        CODEX_THREAD_ID: "codex-thread",
      }),
    ).toBe(path.resolve("data/codex-tabs/manual-session.sqlite"));
  });

  it("lets explicit sqlite database paths win over session-derived defaults", () => {
    expect(
      resolveCogshamboSqlitePath("data/explicit.sqlite", {
        CODEX_THREAD_ID: "codex-thread",
      }),
    ).toBe(path.resolve("data/explicit.sqlite"));
    expect(
      resolveCogshamboSqlitePath(undefined, {
        COGSHAMBO_SQLITE_PATH: "data/env.sqlite",
        CODEX_THREAD_ID: "codex-thread",
      }),
    ).toBe(path.resolve("data/env.sqlite"));
    expect(resolveCogshamboSqlitePath(":memory:", { CODEX_THREAD_ID: "codex-thread" })).toBe(":memory:");
  });
});
