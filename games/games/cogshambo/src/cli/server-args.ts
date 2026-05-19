export type ServerArgs = {
  host: string;
  port: number | undefined;
  sqlitePath: string | undefined;
  scripted: boolean;
};

export function parseServerArgs(args: string[]): ServerArgs {
  const portArgument = parseStringArg(args, "--port", undefined);
  return {
    host: parseStringArg(args, "--host", "127.0.0.1"),
    port: parseOptionalNumberArg("--port", portArgument) ?? parseOptionalNumberArg("PORT", process.env.PORT),
    sqlitePath: parseStringArg(args, "--db", undefined),
    scripted: args.includes("--scripted"),
  };
}

export function parseOptionalNumberArg(name: string, value: string | undefined): number | undefined {
  if (value === undefined) {
    return undefined;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    throw new Error(`Invalid ${name}: ${value}`);
  }

  return parsed;
}

export function parseStringArg(args: string[], name: string, fallback: string): string;
export function parseStringArg(args: string[], name: string, fallback: undefined): string | undefined;
export function parseStringArg(args: string[], name: string, fallback: string | undefined): string | undefined {
  const prefix = `${name}=`;
  const inline = args.find((arg) => arg.startsWith(prefix));
  if (inline) {
    return inline.slice(prefix.length);
  }

  const index = args.indexOf(name);
  if (index !== -1) {
    return args[index + 1] ?? fallback;
  }

  return fallback;
}
