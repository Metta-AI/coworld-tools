import { describe, it } from "vitest";
import { runTraitIntegration } from "./run-trait-integration.js";

describe("insular trait integration", () => {
  it("runs through GridWorld behavior", async () => {
    await runTraitIntegration("insular");
  });
});
