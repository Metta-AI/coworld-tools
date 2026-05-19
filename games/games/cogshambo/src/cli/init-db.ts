#!/usr/bin/env node
import { initializeCogshamboDatabase } from "../server/init-db.js";

const { cogCount, sqlitePath } = parseArgs(process.argv.slice(2));
const result = initializeCogshamboDatabase({ cogCount, sqlitePath });

console.log(`Initialized ${result.sqlitePath} with ${result.cogCount} cogs at tick ${result.tick}.`);

function parseArgs(args: string[]): { cogCount: number | undefined; sqlitePath: string | undefined } {
  return {
    cogCount: parseOptionalNumberArg("--cogs", parseStringArg(args, "--cogs")),
    sqlitePath: parseStringArg(args, "--db"),
  };
}

function parseOptionalNumberArg(name: string, value: string | undefined): number | undefined {
  if (value === undefined) {
    return undefined;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`Invalid ${name}: ${value}`);
  }
  return parsed;
}

function parseStringArg(args: string[], name: string): string | undefined {
  const prefix = `${name}=`;
  const inline = args.find((arg) => arg.startsWith(prefix));
  if (inline) {
    return inline.slice(prefix.length);
  }

  const index = args.indexOf(name);
  return index === -1 ? undefined : args[index + 1];
}
