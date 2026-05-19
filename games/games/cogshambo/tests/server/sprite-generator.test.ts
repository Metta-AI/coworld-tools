import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  createNanoBananaCogSpriteGenerator,
  loadNanoBananaSpriteExamples,
  nanoBananaSpritePrompt,
  spritePrompt,
  spriteSheetSpecText,
  spritesFromManifest,
} from "../../src/server/art/sprite-generator.js";

describe("sprite generator", () => {
  it("uses a short Nano Banana prompt with the user's description", () => {
    const request = {
      name: "Helix",
      description: "brass passionate cog with a teal glass eye",
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "underdog",
      spriteRoll: 2,
      count: 5,
    } as const;
    const prompt = nanoBananaSpritePrompt(request, 3);

    expect(prompt).toContain("Create one Cogshambo game avatar option 3 for Helix");
    expect(prompt).toContain("cute toy-like 3D mascot robot");
    expect(prompt).toContain("Starter reference set: a round sky-blue bot with a chest speaker");
    expect(prompt).toContain("Visual brief: brass passionate cog with a teal big eye.");
    expect(prompt).toContain("Use the name only for flavor; do not render letters");
    expect(prompt).toContain("Overall vibe: defensive stubborn, active passionate, goal underdog.");
    expect(prompt).toContain("soft glossy highlights");
    expect(prompt).toContain("smooth high-resolution edges");
    expect(prompt).toContain("rather than flat sticker art");
    expect(prompt).toContain("No scenery, no text, no labels, no sprite sheet, no collage");
    expect(prompt).toContain("Combine only the 2 or 3 strongest cues into one clean mascot design");
    expect(prompt).toContain("Favor face, body shape, chest icon, ear caps, and overall color");
    expect(prompt).not.toContain("Retro Diffusion");

    const referencedPrompt = nanoBananaSpritePrompt(request, 3, { hasReferenceImages: true });
    expect(referencedPrompt).toContain("attached existing Cogshambo starter sprite PNGs");
    expect(referencedPrompt).toContain("Do not copy any one example exactly");
  });

  it("normalizes glow-heavy appearance briefs toward starter-style highlights", () => {
    const prompt = nanoBananaSpritePrompt({
      name: "Helix",
      description: "polished red cog showing a round glass face and soft blue glow",
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "underdog",
      spriteRoll: 0,
      count: 1,
    }, 1);

    expect(prompt).toContain("Visual brief: polished red cog showing a round glass face and soft blue highlights.");
    expect(prompt).not.toContain("soft blue glow");
  });

  it("loads existing starter sprites as Nano Banana examples", () => {
    const examples = loadNanoBananaSpriteExamples(process.cwd());

    expect(examples.map((example) => example.label)).toEqual([
      "Ada starter sprite",
      "Babbage starter sprite",
      "Mira starter sprite",
      "Default starter sprite",
      "Kip starter sprite",
    ]);
    expect(examples.every((example) => example.mimeType === "image/png")).toBe(true);
    expect(examples.every((example) => example.data.length > 0)).toBe(true);
  });

  it("writes Nano Banana source images and normalizes them into sprite options", async () => {
    const previousGeminiKey = process.env.GEMINI_API_KEY;
    const previousDisable = process.env.COGSHAMBO_DISABLE_SPRITE_PIPELINE;
    let outputDir: string | undefined;
    try {
      process.env.GEMINI_API_KEY = "test-gemini-key";
      delete process.env.COGSHAMBO_DISABLE_SPRITE_PIPELINE;
      const prompts: string[] = [];
      const exampleImages = [{
        data: Buffer.from([1, 2, 3]),
        label: "Test starter sprite",
        mimeType: "image/png",
      }];
      const promptReferenceImages: unknown[] = [];
      const generator = createNanoBananaCogSpriteGenerator({
        imageClient: async ({ prompt, referenceImages }) => {
          prompts.push(prompt);
          promptReferenceImages.push(referenceImages);
          return { data: Buffer.from("fake image"), mimeType: "image/png" };
        },
        normalizeSourceImages: async ({ outputDir: normalizedOutputDir, sourcePaths }) => {
          outputDir = normalizedOutputDir;
          return sourcePaths.map((sourcePath, index) => ({
            key: `nano-test-${index + 1}`,
            label: `Sprite ${index + 1}`,
            url: `/assets/cogshambo/sprite-sheets/nano-test/frames/nano-test-${index + 1}.png`,
          }));
        },
        referenceImages: exampleImages,
      });

      const sprites = await generator({
        name: "Helix",
        description: "brass passionate cog with a teal glass eye",
        defensiveTrait: "stubborn",
        activeTrait: "passionate",
        personalGoal: "underdog",
        spriteRoll: 2,
        count: 3,
      });

      expect(prompts).toHaveLength(3);
      expect(prompts[0]).toContain("option 1");
      expect(prompts[0]).toContain("attached existing Cogshambo starter sprite PNGs");
      expect(prompts[2]).toContain("option 3");
      expect(promptReferenceImages).toEqual([exampleImages, exampleImages, exampleImages]);
      expect(sprites).toEqual([
        {
          key: "nano-test-1",
          label: "Sprite 1",
          url: "/assets/cogshambo/sprite-sheets/nano-test/frames/nano-test-1.png",
        },
        {
          key: "nano-test-2",
          label: "Sprite 2",
          url: "/assets/cogshambo/sprite-sheets/nano-test/frames/nano-test-2.png",
        },
        {
          key: "nano-test-3",
          label: "Sprite 3",
          url: "/assets/cogshambo/sprite-sheets/nano-test/frames/nano-test-3.png",
        },
      ]);
    } finally {
      if (previousGeminiKey === undefined) {
        delete process.env.GEMINI_API_KEY;
      } else {
        process.env.GEMINI_API_KEY = previousGeminiKey;
      }
      if (previousDisable === undefined) {
        delete process.env.COGSHAMBO_DISABLE_SPRITE_PIPELINE;
      } else {
        process.env.COGSHAMBO_DISABLE_SPRITE_PIPELINE = previousDisable;
      }
      if (outputDir) {
        const { rmSync } = await import("node:fs");
        rmSync(outputDir, { force: true, recursive: true });
      }
    }
  });

  it("sends sprite examples as inline Nano Banana request parts", async () => {
    const previousGeminiKey = process.env.GEMINI_API_KEY;
    const previousDisable = process.env.COGSHAMBO_DISABLE_SPRITE_PIPELINE;
    const previousFetch = globalThis.fetch;
    let outputDir: string | undefined;
    let requestBody: unknown;
    try {
      process.env.GEMINI_API_KEY = "test-gemini-key";
      delete process.env.COGSHAMBO_DISABLE_SPRITE_PIPELINE;
      globalThis.fetch = (async (_input, init) => {
        requestBody = JSON.parse(String(init?.body));
        return new Response(JSON.stringify({
          candidates: [{
            content: {
              parts: [{
                inlineData: {
                  data: Buffer.from("generated image").toString("base64"),
                  mimeType: "image/png",
                },
              }],
            },
          }],
        }), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }) as typeof fetch;

      const exampleImage = {
        data: Buffer.from([1, 2, 3]),
        label: "Test starter sprite",
        mimeType: "image/png",
      };
      const generator = createNanoBananaCogSpriteGenerator({
        normalizeSourceImages: async ({ outputDir: normalizedOutputDir }) => {
          outputDir = normalizedOutputDir;
          return [{
            key: "nano-test-1",
            label: "Sprite 1",
            url: "/assets/cogshambo/sprite-sheets/nano-test/frames/nano-test-1.png",
          }];
        },
        referenceImages: [exampleImage],
      });

      await generator({
        name: "Helix",
        description: "brass passionate cog with a teal glass eye",
        defensiveTrait: "stubborn",
        activeTrait: "passionate",
        personalGoal: "underdog",
        spriteRoll: 2,
        count: 1,
      });

      const parts = geminiRequestParts(requestBody);
      expect(parts[0]).toMatchObject({ text: expect.stringContaining("attached existing Cogshambo starter sprite PNGs") });
      expect(parts[1]).toMatchObject({ text: "Existing Cogshambo sprite example: Test starter sprite. Use this for visual style only." });
      expect(parts[2]).toEqual({
        inline_data: {
          data: Buffer.from([1, 2, 3]).toString("base64"),
          mime_type: "image/png",
        },
      });
    } finally {
      globalThis.fetch = previousFetch;
      if (previousGeminiKey === undefined) {
        delete process.env.GEMINI_API_KEY;
      } else {
        process.env.GEMINI_API_KEY = previousGeminiKey;
      }
      if (previousDisable === undefined) {
        delete process.env.COGSHAMBO_DISABLE_SPRITE_PIPELINE;
      } else {
        process.env.COGSHAMBO_DISABLE_SPRITE_PIPELINE = previousDisable;
      }
      if (outputDir) {
        const { rmSync } = await import("node:fs");
        rmSync(outputDir, { force: true, recursive: true });
      }
    }
  });

  it("uses solo high-resolution framing in the legacy art prompt", () => {
    const prompt = spritePrompt({
      name: "Helix",
      description: "brass passionate cog with a teal glass eye",
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "underdog",
      spriteRoll: 2,
      count: 5,
    });

    expect(prompt).toContain("avatar option");
    expect(prompt).toContain("no shirt, jacket, torso panel, or team-colored uniform");
    expect(prompt).toContain("exactly one solo cog character");
    expect(prompt).toContain("no sprite sheet");
    expect(prompt).toContain("no multi-view collage");
    expect(prompt).toContain("glossy toy-like 3D");
    expect(prompt).toContain("High-detail 192px sprite");
    expect(prompt).toContain("bright metal highlights");
    expect(prompt).toContain("avoid flat 2D sticker art");
  });

  it("writes high-resolution still-image settings for builder sprite options", () => {
    const spec = spriteSheetSpecText("builder-helix", {
      name: "Helix",
      description: "brass passionate cog with a teal glass eye",
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "underdog",
      spriteRoll: 2,
      count: 5,
    }, 42);

    expect(spec).toContain("model: rd-plus");
    expect(spec).toContain("style: topdown_asset");
    expect(spec).toContain("size: 192x192");
    expect(spec).toContain("frame_width: 192");
    expect(spec).toContain("frame_height: 192");
    expect(spec).toContain("columns: 5");
    expect(spec).toContain("rows: 1");
    expect(spec).toContain("variants: 5");
  });

  it("returns sliced frame URLs from the sheet manifest", () => {
    const sprites = spritesFromManifest(
      {
        source_sheet_url: "/assets/cogshambo/sprite-sheets/helix/helix-sheet.png",
        preview_url: "/assets/cogshambo/sprite-sheets/helix/helix-preview.png",
        frames: [
          { url: "/assets/cogshambo/sprite-sheets/helix/frames/helix-01.png" },
          { url: "/assets/cogshambo/sprite-sheets/helix/frames/helix-02.png" },
          { url: "/assets/cogshambo/sprite-sheets/helix/frames/helix-03.png" },
          { url: "/assets/cogshambo/sprite-sheets/helix/frames/helix-04.png" },
          { url: "/assets/cogshambo/sprite-sheets/helix/frames/helix-05.png" },
          { url: "/assets/cogshambo/sprite-sheets/helix/frames/helix-06.png" },
        ],
      },
      5,
    );

    expect(sprites).toHaveLength(5);
    expect(sprites[0]).toEqual({
      key: "helix-01",
      label: "Sprite 1",
      url: "/assets/cogshambo/sprite-sheets/helix/frames/helix-01.png",
    });
    expect(sprites.map((sprite) => sprite.url)).not.toContain("/assets/cogshambo/sprite-sheets/helix/helix-sheet.png");
  });

  it("ignores red and blue outfit variant URLs from the sheet manifest", () => {
    const sprites = spritesFromManifest(
      {
        frames: [
          {
            url: "/assets/cogshambo/sprite-sheets/helix/frames/helix-01.png",
            spriteUrls: {
              red: "/assets/cogshambo/sprite-sheets/helix/frames/helix-01-red.png",
              blue: "/assets/cogshambo/sprite-sheets/helix/frames/helix-01-blue.png",
            },
          },
        ],
      },
      1,
    );

    expect(sprites[0]).toEqual({
      key: "helix-01",
      label: "Sprite 1",
      url: "/assets/cogshambo/sprite-sheets/helix/frames/helix-01.png",
    });
  });

  it("removes opaque edge-connected backgrounds when normalizing source images", () => {
    if (!uvAvailable()) {
      return;
    }

    const directory = mkdtempSync(path.join(tmpdir(), "cogshambo-sprite-alpha-"));
    try {
      const specPath = path.join(directory, "alpha-test.md");
      const sourcePath = path.join(directory, "source.ppm");
      const outputDir = path.join(directory, "out");
      writeFileSync(
        specPath,
        [
          "---",
          "name: alpha-test",
          "category: cogs",
          "model: rd-plus",
          "style: topdown_asset",
          "size: 8x8",
          "frame_width: 8",
          "frame_height: 8",
          "columns: 1",
          "rows: 1",
          "variants: 1",
          "append_defaults: false",
          "---",
          "",
          "## Prompt",
          "",
          "Alpha test sprite.",
          "",
        ].join("\n"),
      );
      writeFileSync(sourcePath, ppmWithOpaqueBackground());

      execFileSync(
        "uv",
        [
          "run",
          "--with",
          "pillow",
          "python",
          "tools/generate_sprite_sheet.py",
          specPath,
          "--output-dir",
          outputDir,
          "--source-image",
          sourcePath,
        ],
        { cwd: process.cwd(), stdio: "pipe" },
      );

      const framePath = path.join(outputDir, "frames", "alpha-test-01.png");
      const alphaStats = JSON.parse(
        execFileSync(
          "uv",
          [
            "run",
            "--with",
            "pillow",
            "python",
            "-c",
            [
              "from PIL import Image",
              "import json, sys",
              "frame = Image.open(sys.argv[1]).convert('RGBA')",
              "print(json.dumps({",
              "  'corner': frame.getpixel((0, 0))[3],",
              "  'edge': frame.getpixel((1, 1))[3],",
              "  'body': frame.getpixel((4, 4))[3],",
              "  'enclosed_highlight': frame.getpixel((3, 3))[3],",
              "}))",
            ].join("\n"),
            framePath,
          ],
          { cwd: process.cwd(), encoding: "utf8", stdio: "pipe" },
        ),
      ) as Record<string, number>;

      expect(alphaStats).toEqual({
        corner: 0,
        edge: 0,
        body: 255,
        enclosed_highlight: 255,
      });
    } finally {
      rmSync(directory, { force: true, recursive: true });
    }
  });
});

function geminiRequestParts(body: unknown): Array<Record<string, unknown>> {
  if (typeof body !== "object" || body === null) {
    return [];
  }
  const contents = (body as { contents?: unknown }).contents;
  if (!Array.isArray(contents)) {
    return [];
  }
  const firstContent = contents[0];
  if (typeof firstContent !== "object" || firstContent === null) {
    return [];
  }
  const parts = (firstContent as { parts?: unknown }).parts;
  return Array.isArray(parts) ? parts as Array<Record<string, unknown>> : [];
}

function uvAvailable(): boolean {
  try {
    execFileSync("uv", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

function ppmWithOpaqueBackground(): string {
  const background = [250, 252, 250];
  const outline = [70, 40, 30];
  const body = [180, 60, 60];
  const pixels: number[][] = [];
  for (let y = 0; y < 8; y += 1) {
    for (let x = 0; x < 8; x += 1) {
      const inBody = x >= 2 && x <= 5 && y >= 2 && y <= 5;
      const isOutline = inBody && (x === 2 || x === 5 || y === 2 || y === 5);
      const isHighlight = x === 3 && y === 3;
      pixels.push(isHighlight ? background : isOutline ? outline : inBody ? body : background);
    }
  }

  return ["P3", "8 8", "255", ...pixels.map((pixel) => pixel.join(" "))].join("\n");
}
