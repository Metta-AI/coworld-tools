import { resolveCogshamboPorts } from "./ports.js";
import { startCogshamboServer } from "./runtime.js";

const { serverPort } = resolveCogshamboPorts();
const server = await startCogshamboServer({
  port: serverPort,
  host: "127.0.0.1",
  scripted: process.env.COGSHAMBO_SCRIPTED === "1",
  seedIfEmpty: process.env.COGSHAMBO_SEED_IF_EMPTY === "1",
  log: (message) => console.log(message),
});

let shuttingDown = false;
async function shutdown(): Promise<void> {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;
  try {
    await server.close();
  } catch (error) {
    console.error("Server shutdown failed", error);
    process.exitCode = 1;
  }
}

process.on("SIGINT", () => {
  void shutdown();
});
process.on("SIGTERM", () => {
  void shutdown();
});
