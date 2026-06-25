import { describe, it } from "vitest";
import { runTraitIntegration } from "./run-trait-integration.js";

describe("spinner trait integration", () => {
  it("runs through GridWorld behavior", async () => {
    await runTraitIntegration("spinner");
  });
});
