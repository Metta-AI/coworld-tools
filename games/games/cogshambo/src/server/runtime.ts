import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { createApp } from "./http.js";
import { createControllerRegistry } from "./controllers/cog-controller.js";
import { createSimulationControls } from "./simulation/control.js";
import { createSeedWorld } from "./simulation/seed-world.js";
import { createSqliteSettingsStore } from "./settings-store.js";
import { attachWorldSocketServer } from "./websocket.js";
import { resolveCogshamboPorts } from "./ports.js";
import { acquireSimulationDbLock } from "./simulation-db-lock.js";
import { createSqliteWorldStateStore } from "./world-state-store.js";
import { createJsonVenueEditorStore } from "./venue-editor-store.js";
import { resolveCogshamboSqlitePath } from "./session-defaults.js";
import { SIMULATION_TICK_MS } from "../shared/timing.js";

export type StartCogshamboServerOptions = {
  host?: string;
  port?: number;
  allowPortFallback?: boolean;
  tickMs?: number;
  sqlitePath?: string;
  scripted?: boolean;
  seedIfEmpty?: boolean;
  log?: (message: string) => void;
};

export type RunningCogshamboServer = {
  host: string;
  port: number;
  url: string;
  close: () => Promise<void>;
};

export async function startCogshamboServer(
  options: StartCogshamboServerOptions = {},
): Promise<RunningCogshamboServer> {
  const host = options.host ?? "127.0.0.1";
  const requestedPort = options.port ?? resolveCogshamboPorts().serverPort;
  const tickMs = options.tickMs ?? SIMULATION_TICK_MS;
  const scripted = options.scripted === true;
  const sqlitePath = resolveCogshamboSqlitePath(options.sqlitePath);
  const simulationDbLock = acquireSimulationDbLock(sqlitePath);
  const closeables: Array<{ close(): void }> = [];
  let server: Server | undefined;
  let socketServer: ReturnType<typeof attachWorldSocketServer> | undefined;
  try {
    const settingsStore = createSqliteSettingsStore(sqlitePath);
    closeables.push(settingsStore);
    const venueEditorStore = createJsonVenueEditorStore();
    closeables.push(venueEditorStore);
    const worldStateStore = createSqliteWorldStateStore(sqlitePath);
    closeables.push(worldStateStore);
    const settings = settingsStore.load();
    const restoredWorld = worldStateStore.load();
    const restoredSnapshot = restoredWorld?.snapshot();
    const shouldSeedWorld = !restoredWorld || (options.seedIfEmpty === true && restoredSnapshot?.cogs.length === 0);
    const world = shouldSeedWorld
      ? createSeedWorld(settings.config, { controllerId: scripted ? "wander" : "llm" })
      : restoredWorld;
    if (!shouldSeedWorld) {
      settingsStore.saveCurrentConfig(restoredWorld.gameConfig());
    }
    worldStateStore.save(world);
    const controllers = createControllerRegistry({ requireLlm: !scripted, scriptLlm: scripted });
    const controls = createSimulationControls();
    const app = createApp({ world, controllers, controls, settingsStore, venueEditorStore, worldStateStore });
    server = createServer(app);
    const activeServer = server;

    await listenWithOptionalFallback({
      server: activeServer,
      host,
      port: requestedPort,
      allowFallback: options.allowPortFallback === true,
      log: options.log,
    });
    const activeSocketServer = attachWorldSocketServer({
      server: activeServer,
      world,
      controllers,
      controls,
      worldStateStore,
      tickMs,
      scripted,
    });
    socketServer = activeSocketServer;
    const address = server.address();
    if (!isAddressInfo(address)) {
      throw new Error("Unable to resolve Cogshambo server address");
    }

    const url = `http://${host}:${address.port}`;
    let closePromise: Promise<void> | undefined;
    options.log?.(`Cogshambo server listening on ${url}`);

    return {
      host,
      port: address.port,
      url,
      close: () => {
        closePromise ??= activeSocketServer
          .close()
          .then(() => closeHttpServer(activeServer))
          .finally(() => {
            closeStores(closeables);
            simulationDbLock.release();
          });
        return closePromise;
      },
    };
  } catch (error) {
    await socketServer?.close();
    if (server) {
      await closeHttpServer(server).catch(() => undefined);
    }
    closeStores(closeables);
    simulationDbLock.release();
    throw error;
  }
}

function closeStores(closeables: Array<{ close(): void }>): void {
  for (const closeable of [...closeables].reverse()) {
    closeable.close();
  }
}

async function listenWithOptionalFallback({
  server,
  host,
  port,
  allowFallback,
  log,
}: {
  server: Server;
  host: string;
  port: number;
  allowFallback: boolean;
  log?: (message: string) => void;
}): Promise<void> {
  const maxAttempts = allowFallback ? 20 : 1;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const candidatePort = port + attempt;
    try {
      await listen(server, candidatePort, host);
      return;
    } catch (error) {
      if (!allowFallback || !isAddressInUse(error) || attempt === maxAttempts - 1) {
        throw error;
      }

      log?.(`Port ${candidatePort} is in use; trying ${candidatePort + 1}`);
    }
  }
}

function listen(server: Server, port: number, host: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const onError = (error: Error): void => {
      server.off("listening", onListening);
      reject(error);
    };
    const onListening = (): void => {
      server.off("error", onError);
      resolve();
    };

    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(port, host);
  });
}

function isAddressInUse(error: unknown): boolean {
  return error instanceof Error && (error as NodeJS.ErrnoException).code === "EADDRINUSE";
}

function closeHttpServer(server: Server): Promise<void> {
  if (!server.listening) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    server.close((error) => {
      if (!error || (error as NodeJS.ErrnoException).code === "ERR_SERVER_NOT_RUNNING") {
        resolve();
        return;
      }

      reject(error);
    });
  });
}

function isAddressInfo(address: ReturnType<Server["address"]>): address is AddressInfo {
  return Boolean(address && typeof address === "object" && "port" in address);
}
