import { fstatSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

type SessionEnv = Record<string, string | undefined>;

export type SessionRuntime = {
  terminalPath?: string;
};

export function currentCodexSessionId(
  env: SessionEnv = process.env,
  runtime: SessionRuntime = {},
): string | undefined {
  return firstNonEmpty(env.COGSHAMBO_SESSION_ID, env.CODEX_THREAD_ID, codexTerminalSessionId(env, runtime));
}

export function resolveCogshamboSqlitePath(
  sqlitePath: string | undefined,
  env: SessionEnv = process.env,
  runtime: SessionRuntime = {},
): string {
  const explicitPath = firstNonEmpty(sqlitePath, env.COGSHAMBO_SQLITE_PATH);
  if (explicitPath) {
    return resolveSqlitePath(explicitPath);
  }

  const sessionId = currentCodexSessionId(env, runtime);
  if (sessionId) {
    return path.resolve("data/codex-tabs", `${sessionSlug(sessionId)}.sqlite`);
  }

  return path.resolve("data/cogshambo.sqlite");
}

function resolveSqlitePath(sqlitePath: string): string {
  return sqlitePath === ":memory:" ? sqlitePath : path.resolve(sqlitePath);
}

function firstNonEmpty(...values: Array<string | undefined>): string | undefined {
  return values.find((value) => value !== undefined && value.trim() !== "");
}

function codexTerminalSessionId(env: SessionEnv, runtime: SessionRuntime): string | undefined {
  if (env.CODEX_SHELL?.trim() !== "1") {
    return undefined;
  }

  const terminalPath = firstNonEmpty(runtime.terminalPath, env.TTY) ?? currentTerminalPath();
  const terminalName = terminalPath ? path.basename(terminalPath) : undefined;
  if (!terminalName || terminalName === "tty") {
    return undefined;
  }

  return `codex-shell-${terminalName}`;
}

function currentTerminalPath(): string | undefined {
  const fd = process.stdout.isTTY ? 1 : process.stdin.isTTY ? 0 : undefined;
  if (fd === undefined) {
    return undefined;
  }

  try {
    const terminal = fstatSync(fd);
    if (!terminal.isCharacterDevice()) {
      return undefined;
    }

    return findTerminalPath(terminal.rdev);
  } catch {
    return undefined;
  }
}

function findTerminalPath(rdev: number): string | undefined {
  for (const candidate of terminalDeviceCandidates()) {
    try {
      const stat = statSync(candidate);
      if (stat.isCharacterDevice() && stat.rdev === rdev) {
        return candidate;
      }
    } catch {
      // Ignore disappearing tty devices while scanning /dev.
    }
  }

  return undefined;
}

function terminalDeviceCandidates(): string[] {
  const candidates: string[] = [];
  for (const directory of ["/dev", "/dev/pts"]) {
    try {
      for (const name of readdirSync(directory)) {
        if (isTerminalDeviceName(name)) {
          candidates.push(path.join(directory, name));
        }
      }
    } catch {
      // /dev/pts is not present on macOS.
    }
  }
  return candidates;
}

function isTerminalDeviceName(name: string): boolean {
  return /^ttys?\d+$/.test(name) || /^\d+$/.test(name);
}

function sessionSlug(sessionId: string): string {
  return (
    sessionId
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 96) || "codex-tab"
  );
}
