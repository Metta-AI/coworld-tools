import { describe, expect, it } from "vitest";
import { renderOptionsForFrame } from "../../src/client/render/render-clock";

describe("renderOptionsForFrame", () => {
  it("uses the browser frame timestamp for disco light animation", () => {
    expect(
      renderOptionsForFrame({
        frameTimeMs: 16.7,
        selectedCogId: "ada",
        serverStatus: { discoMode: true },
      }),
    ).toEqual({
      discoLightTimeMs: 16.7,
      discoMode: true,
      selectedCogId: "ada",
    });

    expect(
      renderOptionsForFrame({
        frameTimeMs: 33.4,
        selectedCogId: "ada",
        serverStatus: { discoMode: true },
      }).discoLightTimeMs,
    ).toBe(33.4);
  });
});
