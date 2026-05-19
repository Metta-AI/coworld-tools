import { describe, expect, it } from "vitest";
import { resolveCogshamboPorts } from "../../src/server/ports.js";

describe("resolveCogshamboPorts", () => {
  it("keeps the historical defaults outside Codex sessions", () => {
    expect(resolveCogshamboPorts({})).toEqual({
      serverPort: 8787,
      vitePort: 5173,
      backendOrigin: "http://127.0.0.1:8787",
    });
  });

  it("derives stable per-session ports from the Codex thread id", () => {
    const first = resolveCogshamboPorts({ CODEX_THREAD_ID: "session-a" });
    const second = resolveCogshamboPorts({ CODEX_THREAD_ID: "session-a" });
    const other = resolveCogshamboPorts({ CODEX_THREAD_ID: "session-b" });

    expect(first).toEqual(second);
    expect(first.serverPort).not.toBe(8787);
    expect(first.vitePort).not.toBe(5173);
    expect(first).not.toEqual(other);
    expect(first.backendOrigin).toBe(`http://127.0.0.1:${first.serverPort}`);
  });

  it("derives stable per-session ports from the Codex terminal tty when no thread id is exported", () => {
    const first = resolveCogshamboPorts({ CODEX_SHELL: "1" }, { terminalPath: "/dev/ttys024" });
    const second = resolveCogshamboPorts({ CODEX_SHELL: "1" }, { terminalPath: "/dev/ttys024" });
    const other = resolveCogshamboPorts({ CODEX_SHELL: "1" }, { terminalPath: "/dev/ttys025" });

    expect(first).toEqual(second);
    expect(first.serverPort).not.toBe(8787);
    expect(first.vitePort).not.toBe(5173);
    expect(first).not.toEqual(other);
    expect(first.backendOrigin).toBe(`http://127.0.0.1:${first.serverPort}`);
  });

  it("lets explicit port overrides win over session-derived ports", () => {
    expect(
      resolveCogshamboPorts({
        CODEX_THREAD_ID: "session-a",
        COGSHAMBO_API_PORT: "9101",
        VITE_PORT: "6101",
      }),
    ).toEqual({
      serverPort: 9101,
      vitePort: 6101,
      backendOrigin: "http://127.0.0.1:9101",
    });
  });
});
