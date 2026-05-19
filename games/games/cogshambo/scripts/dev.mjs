import { spawn } from "node:child_process";

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const childProcesses = new Set();
let shuttingDown = false;

const backend = spawnProcess("backend", ["run", "dev:server"], {
  COGSHAMBO_SCRIPTED: process.env.COGSHAMBO_SCRIPTED ?? "1",
  COGSHAMBO_SEED_IF_EMPTY: process.env.COGSHAMBO_SEED_IF_EMPTY ?? "1",
});
spawnProcess("vite", ["run", "dev:vite"]);

process.on("SIGINT", () => {
  shutdown();
});
process.on("SIGTERM", () => {
  shutdown();
});

function spawnProcess(name, args, env = {}) {
  const child = spawn(npmCommand, args, {
    env: {
      ...process.env,
      ...env,
    },
    stdio: "inherit",
  });
  childProcesses.add(child);

  child.once("exit", (code, signal) => {
    childProcesses.delete(child);
    if (!shuttingDown) {
      const reason = signal ? `signal ${signal}` : `exit code ${code ?? 0}`;
      console.error(`[dev] ${name} stopped with ${reason}`);
      shutdown(code ?? 1);
    }
  });

  child.once("error", (error) => {
    childProcesses.delete(child);
    if (!shuttingDown) {
      console.error(`[dev] failed to start ${name}:`, error);
      shutdown(1);
    }
  });

  return child;
}

function shutdown(code = 0) {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;
  for (const child of childProcesses) {
    child.kill();
  }

  if (backend.exitCode !== null && code === 0) {
    process.exitCode = backend.exitCode;
    return;
  }

  process.exitCode = code;
}
