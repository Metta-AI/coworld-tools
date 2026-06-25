import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

export type DeployVersion = {
  commit: string | null;
  shortCommit: string | null;
  deployId: string | null;
  deployedAt: string | null;
  ref: string | null;
  source: "file" | "env" | "unknown";
};

type EnvSource = Record<string, string | undefined>;

export function readDeployVersion(
  env: EnvSource = process.env,
  cwd = process.cwd(),
): DeployVersion {
  const filePath = env.COGSHAMBO_DEPLOY_VERSION_FILE ?? path.resolve(cwd, ".deploy-version.json");
  if (existsSync(filePath)) {
    const version = parseDeployVersionFile(filePath);
    if (version) {
      return version;
    }
  }

  const envVersion = deployVersionFromEnv(env);
  if (envVersion) {
    return envVersion;
  }

  return unknownDeployVersion();
}

function parseDeployVersionFile(filePath: string): DeployVersion | undefined {
  try {
    const parsed = JSON.parse(readFileSync(filePath, "utf8")) as unknown;
    return deployVersionFromRecord(parsed, "file");
  } catch {
    return undefined;
  }
}

function deployVersionFromEnv(env: EnvSource): DeployVersion | undefined {
  const commit = nonEmpty(env.COGSHAMBO_DEPLOY_COMMIT);
  const deployId = nonEmpty(env.COGSHAMBO_DEPLOY_ID);
  const deployedAt = nonEmpty(env.COGSHAMBO_DEPLOYED_AT);
  const ref = nonEmpty(env.COGSHAMBO_DEPLOY_REF);
  if (!commit && !deployId && !deployedAt && !ref) {
    return undefined;
  }

  return {
    commit,
    shortCommit: nonEmpty(env.COGSHAMBO_DEPLOY_SHORT_COMMIT) ?? shortCommit(commit),
    deployId,
    deployedAt,
    ref,
    source: "env",
  };
}

function deployVersionFromRecord(value: unknown, source: DeployVersion["source"]): DeployVersion | undefined {
  if (!isRecord(value)) {
    return undefined;
  }

  const commit = nonEmpty(value.commit);
  const short = nonEmpty(value.shortCommit) ?? shortCommit(commit);
  const deployId = nonEmpty(value.deployId);
  const deployedAt = nonEmpty(value.deployedAt);
  const ref = nonEmpty(value.ref);
  if (!commit && !short && !deployId && !deployedAt && !ref) {
    return undefined;
  }

  return {
    commit,
    shortCommit: short,
    deployId,
    deployedAt,
    ref,
    source,
  };
}

function unknownDeployVersion(): DeployVersion {
  return {
    commit: null,
    shortCommit: null,
    deployId: null,
    deployedAt: null,
    ref: null,
    source: "unknown",
  };
}

function shortCommit(commit: string | null): string | null {
  return commit ? commit.slice(0, 7) : null;
}

function nonEmpty(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
