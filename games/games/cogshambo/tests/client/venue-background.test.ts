import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const DOTTED_VENUE_BACKGROUND_HASH = "ffdc94ddd59c0c8da96ad58ca4b27a869b1625ff2ff462be4ecfa1b6b7d06550";

describe("venue background asset", () => {
  it("does not use the marker-dotted floor plan", () => {
    const bytes = readFileSync(new URL("../../public/assets/cogshambo/venue/gray-area-floor-plan.png", import.meta.url));

    expect(bytes.readUInt32BE(16)).toBe(1672);
    expect(bytes.readUInt32BE(20)).toBe(941);
    expect(createHash("sha256").update(bytes).digest("hex")).not.toBe(DOTTED_VENUE_BACKGROUND_HASH);
  });
});
