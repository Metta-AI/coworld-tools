import { currentCodexSessionId, type SessionRuntime } from "./session-defaults.js";

const DEFAULT_SERVER_PORT = 8787;
const DEFAULT_VITE_PORT = 5173;
const SESSION_PORT_SPAN = 1000;

export type CogshamboPorts = {
  serverPort: number;
  vitePort: number;
  backendOrigin: string;
};

type PortEnv = Record<string, string | undefined>;

export function resolveCogshamboPorts(env: PortEnv = process.env, runtime: SessionRuntime = {}): CogshamboPorts {
  const offset = sessionPortOffset(env, runtime);
  const serverPort =
    parsePort("COGSHAMBO_API_PORT", env.COGSHAMBO_API_PORT) ??
    parsePort("COGSHAMBO_PORT", env.COGSHAMBO_PORT) ??
    parsePort("PORT", env.PORT) ??
    DEFAULT_SERVER_PORT + offset;
  const vitePort = parsePort("VITE_PORT", env.VITE_PORT) ?? DEFAULT_VITE_PORT + offset;

  return {
    serverPort,
    vitePort,
    backendOrigin: `http://127.0.0.1:${serverPort}`,
  };
}

function sessionPortOffset(env: PortEnv, runtime: SessionRuntime): number {
  const sessionId = currentCodexSessionId(env, runtime);
  if (!sessionId) {
    return 0;
  }

  let hash = 0;
  for (const char of sessionId) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return hash % SESSION_PORT_SPAN;
}

function parsePort(name: string, value: string | undefined): number | undefined {
  if (value === undefined || value.trim() === "") {
    return undefined;
  }

  const port = Number.parseInt(value, 10);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error(`Invalid ${name}: ${value}`);
  }
  return port;
}
