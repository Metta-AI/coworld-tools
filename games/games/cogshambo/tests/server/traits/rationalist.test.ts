import { describe, it } from "vitest";
import { runTraitIntegration } from "./run-trait-integration.js";

describe("rationalist trait integration", () => {
  it("runs through GridWorld behavior", async () => {
    await runTraitIntegration("rationalist");
  });
});
