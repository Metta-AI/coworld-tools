import { describe, expect, it } from "vitest";

import { discoLightSpots } from "../../src/client/render/disco-lights";

describe("discoLightSpots", () => {
  it("keeps light motion inside the venue without pinning spots to hard edges", () => {
    const edgeSamples = [];
    for (let timeMs = 0; timeMs <= 6_000; timeMs += 100) {
      for (const spot of discoLightSpots(timeMs)) {
        expect(spot.x).toBeGreaterThan(0.04);
        expect(spot.x).toBeLessThan(0.96);
        expect(spot.y).toBeGreaterThan(0.04);
        expect(spot.y).toBeLessThan(0.96);
        if (spot.x === 0.04 || spot.x === 0.96 || spot.y === 0.04 || spot.y === 0.96) {
          edgeSamples.push(spot);
        }
      }
    }

    expect(edgeSamples).toHaveLength(0);
  });
});
