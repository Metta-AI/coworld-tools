import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { TRAITS } from "../../../src/shared/types.js";

const TRAIT_IDS = TRAITS;
const ROOT = process.cwd();

describe("trait module structure", () => {
  for (const traitId of TRAIT_IDS) {
    it(`${traitId} has metadata, code, and a working integration test file`, () => {
      const modulePath = join(ROOT, "src/shared/traits", `${traitId}.ts`);
      const testPath = join(ROOT, "tests/server/traits", `${traitId}.test.ts`);

      expect(existsSync(modulePath), `${traitId} should live in its own shared trait module`).toBe(true);
      expect(existsSync(testPath), `${traitId} should have its own integration test`).toBe(true);

      const moduleSource = readFileSync(modulePath, "utf8");
      const testSource = readFileSync(testPath, "utf8");

      expect(moduleSource).toContain("userDescription");
      expect(moduleSource).toContain("promptDescription");
      expect(moduleSource).toContain("code");
      expect(testSource).toContain("runTraitIntegration");
    });
  }
});
