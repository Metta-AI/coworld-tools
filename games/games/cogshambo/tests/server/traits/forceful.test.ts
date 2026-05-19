import { describe, it } from "vitest";
import { runTraitIntegration } from "./run-trait-integration.js";

describe("forceful trait integration", () => {
  it("runs through GridWorld behavior", async () => {
    await runTraitIntegration("forceful");
  });
});
