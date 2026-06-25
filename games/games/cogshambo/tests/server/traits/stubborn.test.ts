import { describe, it } from "vitest";
import { runTraitIntegration } from "./run-trait-integration.js";

describe("stubborn trait integration", () => {
  it("runs through GridWorld behavior", async () => {
    await runTraitIntegration("stubborn");
  });
});
