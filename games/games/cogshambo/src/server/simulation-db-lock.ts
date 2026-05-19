import { closeSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { resolveCogshamboSqlitePath } from "./session-defaults.js";

export type SimulationDbLock = {
  sqlitePath: string | undefined;
  release(): void;
};

type LockFileState = {
  pid?: number;
  startedAt?: string;
  sqlitePath?: string;
};

export function acquireSimulationDbLock(sqlitePath: string | undefined): SimulationDbLock {
  const resolvedSqlitePath = resolveSqlitePath(sqlitePath);
  if (!resolvedSqlitePath) {
    return { sqlitePath: undefined, release: () => undefined };
  }

  const lockPath = `${resolvedSqlitePath}.sim.lock`;
  mkdirSync(path.dirname(lockPath), { recursive: true });

  for (let attempt = 0; attempt < 2; attempt += 1) {
    let fd: number | undefined;
    try {
      fd = openSync(lockPath, "wx");
      writeFileSync(
        fd,
        JSON.stringify(
          {
            pid: process.pid,
            startedAt: new Date().toISOString(),
            sqlitePath: resolvedSqlitePath,
          },
          null,
          2,
        ),
      );
      const lockFd = fd;
      fd = undefined;

      let released = false;
      return {
        sqlitePath: resolvedSqlitePath,
        release() {
          if (released) {
            return;
          }

          released = true;
          closeSync(lockFd);
          unlinkLockFile(lockPath);
        },
      };
    } catch (error) {
      if (fd !== undefined) {
        closeSync(fd);
      }

      if (!isFileExistsError(error)) {
        throw error;
      }

      const state = readLockFile(lockPath);
      if (typeof state.pid === "number" && processIsRunning(state.pid)) {
        throw new Error(
          `A Cogshambo simulation is already running for sqlite database ${resolvedSqlitePath} (pid ${state.pid}). Use --db to choose a different database or stop the existing simulation first.`,
        );
      }

      unlinkSync(lockPath);
    }
  }

  throw new Error(`Unable to acquire Cogshambo simulation lock for sqlite database ${resolvedSqlitePath}`);
}

function resolveSqlitePath(sqlitePath: string | undefined): string | undefined {
  const value = resolveCogshamboSqlitePath(sqlitePath);
  return value === ":memory:" ? undefined : path.resolve(value);
}

function readLockFile(lockPath: string): LockFileState {
  try {
    return JSON.parse(readFileSync(lockPath, "utf8")) as LockFileState;
  } catch {
    return {};
  }
}

function unlinkLockFile(lockPath: string): void {
  try {
    unlinkSync(lockPath);
  } catch (error) {
    if (!isFileNotFoundError(error)) {
      throw error;
    }
  }
}

function processIsRunning(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return isPermissionError(error);
  }
}

function isFileExistsError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "EEXIST";
}

function isFileNotFoundError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}

function isPermissionError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "EPERM";
}
