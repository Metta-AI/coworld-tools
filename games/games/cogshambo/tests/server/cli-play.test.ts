import { mkdtempSync, rmSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import type { AddressInfo } from "node:net";
import { describe, expect, it } from "vitest";

describe("cogshambo play CLI", () => {
  it("exposes a cogshambo binary in package metadata", async () => {
    const packageJson = JSON.parse(await readFile(path.resolve("package.json"), "utf-8")) as {
      bin?: Record<string, string>;
      scripts?: Record<string, string>;
    };

    expect(packageJson.bin?.cogshambo).toBe("dist-server/cli.js");
    expect(packageJson.scripts?.preplay).toBe("npm run build");
    expect(packageJson.scripts?.["codex:builder"]).toBe("tsx src/cli.ts builder");
  });

  it("starts the game server and closes it idempotently", async () => {
    const { startCogshamboServer } = (await import("../../src/server/runtime.js")) as {
      startCogshamboServer: (options: { host: string; port: number; sqlitePath: string; tickMs: number; scripted: true }) => Promise<{
        url: string;
        close: () => Promise<void>;
      }>;
    };
    const tempDb = tempSqlitePath("cli-start");
    let server: Awaited<ReturnType<typeof startCogshamboServer>> | undefined;

    try {
      server = await startCogshamboServer({
        host: "127.0.0.1",
        port: 0,
        sqlitePath: tempDb.dbPath,
        tickMs: 1_000,
        scripted: true,
      });
      const response = await fetch(`${server.url}/health`);

      expect(response.status).toBe(200);

      await server.close();
      await server.close();
      await expect(fetch(`${server.url}/health`)).rejects.toThrow();
    } finally {
      await server?.close();
      tempDb.cleanup();
    }
  });

  it("requires live Anthropic configuration by default in tests", async () => {
    const { startCogshamboServer } = (await import("../../src/server/runtime.js")) as {
      startCogshamboServer: (options: { host: string; port: number; sqlitePath: string; tickMs: number }) => Promise<{
        close: () => Promise<void>;
      }>;
    };
    const tempDb = tempSqlitePath("cli-require-llm");

    try {
      await expect(
        startCogshamboServer({
          host: "127.0.0.1",
          port: 0,
          sqlitePath: tempDb.dbPath,
          tickMs: 1_000,
        }),
      ).rejects.toThrow("Anthropic credentials");
    } finally {
      tempDb.cleanup();
    }
  });

  it("falls back to the next available port when requested", async () => {
    const host = "127.0.0.1";
    const blockingServer = createServer((_request, response) => {
      response.end("occupied");
    });
    await new Promise<void>((resolve) => blockingServer.listen(0, host, resolve));
    const blockedPort = (blockingServer.address() as AddressInfo).port;
    const { startCogshamboServer } = (await import("../../src/server/runtime.js")) as {
      startCogshamboServer: (options: {
        host: string;
        port: number;
        tickMs: number;
        allowPortFallback: boolean;
        sqlitePath: string;
        scripted: true;
      }) => Promise<{
        port: number;
        url: string;
        close: () => Promise<void>;
      }>;
    };
    const tempDb = tempSqlitePath("cli-port");
    let server: Awaited<ReturnType<typeof startCogshamboServer>> | undefined;

    try {
      server = await startCogshamboServer({
        host,
        port: blockedPort,
        sqlitePath: tempDb.dbPath,
        tickMs: 1_000,
        allowPortFallback: true,
        scripted: true,
      });

      expect(server.port).toBeGreaterThan(blockedPort);
      expect((await fetch(`${server.url}/health`)).status).toBe(200);

      await server.close();
    } finally {
      await server?.close();
      tempDb.cleanup();
      await new Promise<void>((resolve, reject) => {
        blockingServer.close((error) => (error ? reject(error) : resolve()));
      });
    }
  });

  it("lets the play app viewport follow the native window size", async () => {
    const { playWindowLaunchOptions } = (await import("../../src/cli/play.js")) as {
      playWindowLaunchOptions: (url: string) => {
        args: string[];
        viewport?: unknown;
      };
    };

    expect(playWindowLaunchOptions("http://127.0.0.1:8787")).toMatchObject({
      args: ["--enable-unsafe-webgpu", "--app=http://127.0.0.1:8787"],
      viewport: null,
    });
  });

  it("parses sqlite database paths for play and builder server args", async () => {
    const { parseServerArgs } = (await import("../../src/cli/server-args.js")) as {
      parseServerArgs: (args: string[]) => {
        host: string;
        port: number | undefined;
        sqlitePath: string | undefined;
        scripted: boolean;
      };
    };

    expect(parseServerArgs(["--host", "0.0.0.0", "--port", "8799", "--db", "data/play.sqlite"])).toEqual({
      host: "0.0.0.0",
      port: 8799,
      sqlitePath: "data/play.sqlite",
      scripted: false,
    });
    expect(parseServerArgs(["--scripted"])).toEqual({
      host: "127.0.0.1",
      port: undefined,
      sqlitePath: undefined,
      scripted: true,
    });
  });

  it("builds a Codex browser URL for the cog builder screen", async () => {
    const { cogBuilderUrl } = (await import("../../src/cli/builder.js")) as {
      cogBuilderUrl: (baseUrl: string) => string;
    };

    expect(cogBuilderUrl("http://127.0.0.1:8787/?profile=cog-1&foo=bar#details")).toBe(
      "http://127.0.0.1:8787/builder?foo=bar",
    );
  });

  it("keeps the game server running when the play browser window closes", async () => {
    const { playCogshambo } = (await import("../../src/cli/play.js")) as {
      playCogshambo: (options: {
        host: string;
        port: number;
        sqlitePath: string;
        tickMs: number;
        scripted: true;
        log: (message: string) => void;
        openBrowser: (url: string) => Promise<{
          close: () => Promise<void>;
          closed: Promise<void>;
        }>;
      }) => Promise<{
        url: string;
        close: () => Promise<void>;
        finished: Promise<void>;
      }>;
    };

    const tempDb = tempSqlitePath("cli-play");
    let openedUrl: string | undefined;
    let closeWindow: (() => void) | undefined;
    try {
      const session = await playCogshambo({
        host: "127.0.0.1",
        port: 0,
        sqlitePath: tempDb.dbPath,
        tickMs: 1_000,
        scripted: true,
        log: () => undefined,
        openBrowser: async (url) => {
          openedUrl = url;
          const closed = new Promise<void>((resolve) => {
            closeWindow = resolve;
          });
          return {
            close: async () => {
              closeWindow?.();
            },
            closed,
          };
        },
      });

      expect(openedUrl).toBe(session.url);
      expect((await fetch(`${session.url}/health`)).status).toBe(200);

      closeWindow?.();
      await session.finished;
      expect((await fetch(`${session.url}/health`)).status).toBe(200);
      await session.close();
      await expect(fetch(`${session.url}/health`)).rejects.toThrow();
    } finally {
      closeWindow?.();
      tempDb.cleanup();
    }
  });

  it("reseeds an empty saved world before opening play", async () => {
    const { initializeCogshamboDatabase } = (await import("../../src/server/init-db.js")) as {
      initializeCogshamboDatabase: (options: { sqlitePath: string; cogCount: number }) => void;
    };
    const { playCogshambo } = (await import("../../src/cli/play.js")) as {
      playCogshambo: (options: {
        host: string;
        port: number;
        sqlitePath: string;
        tickMs: number;
        scripted: true;
        log: (message: string) => void;
        openBrowser: (url: string) => Promise<{
          close: () => Promise<void>;
          closed: Promise<void>;
        }>;
      }) => Promise<{
        url: string;
        close: () => Promise<void>;
      }>;
    };

    const tempDb = tempSqlitePath("cli-empty-play");
    let closeWindow: (() => void) | undefined;
    try {
      initializeCogshamboDatabase({ sqlitePath: tempDb.dbPath, cogCount: 0 });
      const session = await playCogshambo({
        host: "127.0.0.1",
        port: 0,
        sqlitePath: tempDb.dbPath,
        tickMs: 1_000,
        scripted: true,
        log: () => undefined,
        openBrowser: async () => {
          const closed = new Promise<void>((resolve) => {
            closeWindow = resolve;
          });
          return {
            close: async () => {
              closeWindow?.();
            },
            closed,
          };
        },
      });

      const response = await fetch(`${session.url}/api/world`);
      const snapshot = (await response.json()) as { cogs: unknown[] };

      expect(snapshot.cogs.length).toBeGreaterThan(0);
      await session.close();
    } finally {
      closeWindow?.();
      tempDb.cleanup();
    }
  });

  it("does not reject when browser profile cleanup leaves files behind", async () => {
    const { cleanupPlayWindowProfile } = (await import("../../src/cli/play.js")) as {
      cleanupPlayWindowProfile: (
        userDataDir: string,
        options: {
          remove: (path: string, options: { force: boolean; recursive: boolean }) => Promise<void>;
          retryDelayMs: number;
          retries: number;
        },
      ) => Promise<void>;
    };
    const error = Object.assign(new Error("directory not empty"), {
      code: "ENOTEMPTY",
    });

    await expect(
      cleanupPlayWindowProfile("/tmp/cogshambo-leftover", {
        remove: async () => {
          throw error;
        },
        retryDelayMs: 0,
        retries: 1,
      }),
    ).resolves.toBeUndefined();
  });
});

function tempSqlitePath(slug: string): { dbPath: string; cleanup: () => void } {
  const tempDir = mkdtempSync(path.join(tmpdir(), `cogshambo-${slug}-`));
  return {
    dbPath: path.join(tempDir, "cogshambo.sqlite"),
    cleanup: () => rmSync(tempDir, { recursive: true, force: true }),
  };
}
