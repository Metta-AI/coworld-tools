import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { startCogshamboServer } from "../server/runtime.js";

export type PlayBrowserHandle = {
  close: () => Promise<void>;
  closed: Promise<void>;
};

type PlayWindowLaunchOptions = {
  headless: false;
  args: string[];
  viewport: null;
};

type ProfileRemove = (path: string, options: { force: boolean; recursive: boolean }) => Promise<void>;

type ProfileCleanupOptions = {
  remove?: ProfileRemove;
  retries?: number;
  retryDelayMs?: number;
};

export type PlayCogshamboOptions = {
  host?: string;
  port?: number;
  allowPortFallback?: boolean;
  sqlitePath?: string;
  scripted?: boolean;
  tickMs?: number;
  log?: (message: string) => void;
  openBrowser?: (url: string) => Promise<PlayBrowserHandle>;
};

export type CogshamboPlaySession = {
  url: string;
  close: () => Promise<void>;
  finished: Promise<void>;
};

export async function playCogshambo(options: PlayCogshamboOptions = {}): Promise<CogshamboPlaySession> {
  const log = options.log ?? console.log;
  const server = await startCogshamboServer({
    host: options.host,
    port: options.port,
    allowPortFallback: options.allowPortFallback,
    sqlitePath: options.sqlitePath,
    scripted: options.scripted,
    seedIfEmpty: true,
    tickMs: options.tickMs,
    log,
  });

  let browser: PlayBrowserHandle;
  try {
    browser = await (options.openBrowser ?? openPlayWindow)(server.url);
  } catch (error) {
    await server.close();
    throw error;
  }

  let closePromise: Promise<void> | undefined;
  const close = async (): Promise<void> => {
    if (!closePromise) {
      closePromise = browser.close().finally(() => server.close());
    }
    await closePromise;
  };
  const finished = browser.closed;

  return {
    url: server.url,
    close,
    finished,
  };
}

export async function openPlayWindow(url: string): Promise<PlayBrowserHandle> {
  const { chromium } = await importPlaywright();
  const userDataDir = await mkdtemp(path.join(tmpdir(), "cogshambo-"));
  const context = await chromium
    .launchPersistentContext(userDataDir, playWindowLaunchOptions(url))
    .catch(async (error: unknown) => {
      await cleanupPlayWindowProfile(userDataDir);
      throw error;
    });

  let cleanedUp = false;
  const cleanup = async (): Promise<void> => {
    if (cleanedUp) {
      return;
    }

    cleanedUp = true;
    await cleanupPlayWindowProfile(userDataDir);
  };
  const closed = new Promise<void>((resolve) => {
    context.once("close", () => {
      resolve();
    });
  }).finally(cleanup);

  return {
    closed,
    close: async () => {
      await context.close().catch(() => undefined);
      await closed;
    },
  };
}

export async function cleanupPlayWindowProfile(
  userDataDir: string,
  options: ProfileCleanupOptions = {},
): Promise<void> {
  const remove = options.remove ?? rm;
  const retries = options.retries ?? 5;
  const retryDelayMs = options.retryDelayMs ?? 100;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      await remove(userDataDir, { recursive: true, force: true });
      return;
    } catch (error) {
      if (!isRetryableProfileCleanupError(error)) {
        throw error;
      }

      if (attempt === retries) {
        return;
      }

      await delay(retryDelayMs);
    }
  }
}

function isRetryableProfileCleanupError(error: unknown): boolean {
  const code = typeof error === "object" && error !== null && "code" in error
    ? (error as { code?: unknown }).code
    : undefined;
  return code === "ENOTEMPTY" || code === "EBUSY" || code === "EPERM" || code === "ENOENT";
}

function delay(ms: number): Promise<void> {
  return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve();
}

export function playWindowLaunchOptions(url: string): PlayWindowLaunchOptions {
  return {
    headless: false,
    args: ["--enable-unsafe-webgpu", `--app=${url}`],
    viewport: null,
  };
}

async function importPlaywright(): Promise<typeof import("playwright")> {
  try {
    return await import("playwright");
  } catch (error) {
    throw new Error(
      "cogshambo play requires Playwright to launch its browser window. Run npm install in this repo before using the command.",
      { cause: error },
    );
  }
}
