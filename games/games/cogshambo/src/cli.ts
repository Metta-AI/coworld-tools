#!/usr/bin/env node
import { startCodexBuilderSession, type CodexBuilderSession } from "./cli/builder.js";
import { playCogshambo } from "./cli/play.js";
import { parseOptionalNumberArg, parseServerArgs, parseStringArg } from "./cli/server-args.js";
import { initializeCogshamboDatabase } from "./server/init-db.js";

const [command, ...args] = process.argv.slice(2);

if (command === "play") {
  await runPlay(args);
} else if (command === "builder" || command === "codex-builder") {
  await runBuilder(args);
} else if (command === "init-db") {
  runInitDb(args);
} else {
  printUsage();
  process.exitCode = command ? 1 : 0;
}

async function runPlay(args: string[]): Promise<void> {
  const { host, port, sqlitePath, scripted } = parseServerArgs(args);
  const session = await playCogshambo({
    host,
    port,
    sqlitePath,
    scripted,
    allowPortFallback: port === undefined,
    log: (message) => console.log(message),
  });

  await waitForShutdown(session, () => {
    console.log(`Opened Cogshambo play window at ${session.url}`);
  });
}

async function runBuilder(args: string[]): Promise<void> {
  const { host, port, sqlitePath, scripted } = parseServerArgs(args);
  const session = await startCodexBuilderSession({
    host,
    port,
    sqlitePath,
    scripted,
    allowPortFallback: port === undefined,
    log: (message) => console.log(message),
  });

  await waitForShutdown(session, () => {
    console.log(`Open Cogshambo builder in the Codex browser pane: ${session.url}`);
  });
}

function runInitDb(args: string[]): void {
  const cogCount = parseOptionalNumberArg("--cogs", parseStringArg(args, "--cogs", undefined));
  const sqlitePath = parseStringArg(args, "--db", undefined);
  const result = initializeCogshamboDatabase({ cogCount, sqlitePath });
  console.log(`Initialized ${result.sqlitePath} with ${result.cogCount} cogs at tick ${result.tick}.`);
}

async function waitForShutdown(session: Pick<CodexBuilderSession, "close">, onReady: () => void): Promise<void> {
  let shuttingDown = false;
  let resolveFinished: (() => void) | undefined;
  const finished = new Promise<void>((resolve) => {
    resolveFinished = resolve;
  });
  const shutdown = async (): Promise<void> => {
    if (shuttingDown) {
      return;
    }

    shuttingDown = true;
    await session.close();
    resolveFinished?.();
  };

  process.on("SIGINT", () => {
    void shutdown();
  });
  process.on("SIGTERM", () => {
    void shutdown();
  });

  onReady();
  await finished;
}

function printUsage(): void {
  console.log("Usage: cogshambo play|builder|init-db [--host 127.0.0.1] [--port PORT] [--db PATH] [--scripted] [--cogs N]");
}
