import { startCogshamboServer } from "../server/runtime.js";

export type CodexBuilderOptions = {
  host?: string;
  port?: number;
  allowPortFallback?: boolean;
  sqlitePath?: string;
  scripted?: boolean;
  tickMs?: number;
  log?: (message: string) => void;
};

export type CodexBuilderSession = {
  serverUrl: string;
  url: string;
  close: () => Promise<void>;
};

export async function startCodexBuilderSession(options: CodexBuilderOptions = {}): Promise<CodexBuilderSession> {
  const server = await startCogshamboServer({
    host: options.host,
    port: options.port,
    allowPortFallback: options.allowPortFallback,
    sqlitePath: options.sqlitePath,
    scripted: options.scripted,
    tickMs: options.tickMs,
    log: options.log,
  });

  return {
    serverUrl: server.url,
    url: cogBuilderUrl(server.url),
    close: server.close,
  };
}

export function cogBuilderUrl(baseUrl: string): string {
  const url = new URL(baseUrl);
  url.pathname = "/builder";
  url.searchParams.delete("builder");
  url.searchParams.delete("config");
  url.searchParams.delete("profile");
  url.searchParams.delete("editor");
  url.hash = "";
  return url.toString();
}
