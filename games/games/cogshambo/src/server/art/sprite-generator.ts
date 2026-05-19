import { execFile } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import type { GeneratedCogSprite, GenerateCogSpritesRequest } from "../../shared/protocol.js";

export type CogSpriteGenerator = (request: GenerateCogSpritesRequest) => Promise<GeneratedCogSprite[]>;

const execFileAsync = promisify(execFile);
const MAX_GENERATION_MS = 180_000;
const NANO_BANANA_GENERATION_MS = 30_000;
const NANO_BANANA_MODEL = "gemini-2.5-flash-image";
const BUILDER_FRAME_SIZE = 192;
const NANO_BANANA_REFERENCE_SPRITES = [
  { label: "Ada starter sprite", path: "public/assets/cogshambo/sprite-sheets/cog-ada/frames/cog-ada-01.png" },
  { label: "Babbage starter sprite", path: "public/assets/cogshambo/sprite-sheets/cog-babbage/frames/cog-babbage-01.png" },
  { label: "Mira starter sprite", path: "public/assets/cogshambo/sprite-sheets/cog-mira/frames/cog-mira-01.png" },
  { label: "Default starter sprite", path: "public/assets/cogshambo/sprite-sheets/cog-default/frames/cog-default-01.png" },
  { label: "Kip starter sprite", path: "public/assets/cogshambo/sprite-sheets/cog-kip/frames/cog-kip-01.png" },
] as const;

type SpriteSheetManifest = {
  frames?: SpriteSheetManifestFrame[];
};

type SpriteSheetManifestFrame = {
  url?: unknown;
};

type NanoBananaImage = {
  data: Buffer;
  mimeType: string;
};

export type NanoBananaReferenceImage = {
  data: Buffer;
  label: string;
  mimeType: string;
};

type NanoBananaImageClient = (request: {
  apiKey: string;
  model: string;
  prompt: string;
  referenceImages: readonly NanoBananaReferenceImage[];
  timeoutMs: number;
}) => Promise<NanoBananaImage>;

type SourceImageNormalizer = (request: {
  baseName: string;
  env: NodeJS.ProcessEnv;
  outputDir: string;
  repoRoot: string;
  sourcePaths: string[];
}) => Promise<GeneratedCogSprite[]>;

type NanoBananaGeneratorOptions = {
  imageClient?: NanoBananaImageClient;
  model?: string;
  normalizeSourceImages?: SourceImageNormalizer;
  referenceImages?: readonly NanoBananaReferenceImage[];
  timeoutMs?: number;
};

export function createNanoBananaCogSpriteGenerator(options: NanoBananaGeneratorOptions = {}): CogSpriteGenerator {
  return async (request) => {
    const repoRoot = findRepoRoot();
    const env = loadEnv(repoRoot);
    if (env.COGSHAMBO_DISABLE_SPRITE_PIPELINE === "1") {
      throw new Error("Avatar pipeline disabled by COGSHAMBO_DISABLE_SPRITE_PIPELINE");
    }

    const apiKey = env.GEMINI_API_KEY ?? env.GOOGLE_API_KEY;
    if (!apiKey) {
      throw new Error("Nano Banana avatar generation requires GEMINI_API_KEY or GOOGLE_API_KEY");
    }

    const seed = spriteSeed(request);
    const baseName = `builder-${slugify(request.name || "cog")}-${seed.toString(36)}`;
    const outputDir = path.join(repoRoot, "public", "assets", "cogshambo", "sprite-sheets", baseName);
    const sourcesDir = path.join(outputDir, "sources");
    mkdirSync(sourcesDir, { recursive: true });

    const imageClient = options.imageClient ?? generateNanoBananaImage;
    const model = options.model ?? env.COGSHAMBO_NANO_BANANA_MODEL ?? NANO_BANANA_MODEL;
    const timeoutMs = options.timeoutMs ?? positiveNumber(env.COGSHAMBO_NANO_BANANA_TIMEOUT_MS, NANO_BANANA_GENERATION_MS);
    const referenceImages = options.referenceImages ?? loadNanoBananaSpriteExamples(repoRoot);
    const prompts = Array.from(
      { length: request.count },
      (_value, index) => nanoBananaSpritePrompt(request, index + 1, { hasReferenceImages: referenceImages.length > 0 }),
    );
    const images = await Promise.all(
      prompts.map((prompt) =>
        imageClient({
          apiKey,
          model,
          prompt,
          referenceImages,
          timeoutMs,
        }),
      ),
    );

    const sourcePaths = images.map((image, index) => {
      const sourcePath = path.join(sourcesDir, `${baseName}-source-${String(index + 1).padStart(2, "0")}${imageExtension(image.mimeType)}`);
      writeFileSync(sourcePath, image.data);
      return sourcePath;
    });

    const normalizeSourceImages = options.normalizeSourceImages ?? normalizeNanoBananaSourceImages;
    const sprites = await normalizeSourceImages({ baseName, env, outputDir, repoRoot, sourcePaths });
    if (sprites.length < request.count) {
      throw new Error(`Nano Banana manifest only included ${sprites.length} avatar option(s)`);
    }

    return sprites.slice(0, request.count);
  };
}

export function createArtGentCogSpriteGenerator(): CogSpriteGenerator {
  return async (request) => {
    const repoRoot = findRepoRoot();
    const seed = spriteSeed(request);
    const baseName = `builder-${slugify(request.name || "cog")}-${seed.toString(36)}`;
    const outputDir = path.join(repoRoot, "public", "assets", "cogshambo", "sprite-sheets", baseName);
    const env = loadEnv(repoRoot);
    if (env.COGSHAMBO_DISABLE_SPRITE_PIPELINE === "1") {
      throw new Error("Art pipeline disabled by COGSHAMBO_DISABLE_SPRITE_PIPELINE");
    }
    const specPath = writeSpriteSheetSpec(baseName, request, seed);

    await execFileAsync(
      npmCommand(),
      [
        "run",
        "art:sheet",
        "--",
        specPath,
        "--output-dir",
        outputDir,
      ],
      {
        cwd: repoRoot,
        env,
        maxBuffer: 1024 * 1024,
        timeout: MAX_GENERATION_MS,
      },
    );

    const manifestFile = path.join(outputDir, "manifest.json");
    if (!existsSync(manifestFile)) {
      throw new Error("Art sheet pipeline did not write a manifest");
    }

    const sprites = spritesFromManifest(JSON.parse(readFileSync(manifestFile, "utf8")), request.count);
    if (sprites.length < request.count) {
      throw new Error(`Art sheet manifest only included ${sprites.length} frame URL(s)`);
    }

    return sprites;
  };
}

export const createPipelineCogSpriteGenerator = createNanoBananaCogSpriteGenerator;

export function nanoBananaSpritePrompt(
  request: GenerateCogSpritesRequest,
  option: number,
  context: { hasReferenceImages?: boolean } = {},
): string {
  const name = request.name.trim() || "new cog";
  const description = visualAppearanceBrief(request.description);
  const referenceInstruction = context.hasReferenceImages
    ? "Use the attached existing Cogshambo starter sprite PNGs as visual examples for proportions, outline weight, glossy bevels, alpha transparency, highlights, shadow, and board-scale readability. Do not copy any one example exactly; create a new cog from the visual brief."
    : "Match the bundled Cogshambo starter sprites exactly: cute toy-like 3D mascot robot, one bold body shape, side ear caps, big readable eyes, a tiny smile, a single simple chest detail, and tiny hands and feet.";

  return [
    `Create one Cogshambo game avatar option ${option} for ${name}.`,
    referenceInstruction,
    "Starter reference set: a round sky-blue bot with a chest speaker, a yellow cog-headed bot with a lightning chest plate, a lavender square bot with a heart badge, and a mint gear-shaped bot with a pale belly plate.",
    "Use a centered solo character on a transparent background. No scenery, no text, no labels, no sprite sheet, no collage.",
    "Use actual PNG alpha transparency; do not draw a white, gray, checkerboard, or paper background.",
    "Keep the shape bold and readable at board-game scale, with smooth high-resolution edges, soft glossy highlights, and clean 3D shading rather than flat sticker art or chunky pixel art.",
    "Use the name only for flavor; do not render letters, numbers, signage, or initials anywhere in the image.",
    `Visual brief: ${description}`,
    `Overall vibe: defensive ${request.defensiveTrait}, active ${request.activeTrait}, goal ${request.personalGoal}.`,
    "Treat the visual brief as loose art direction. Combine only the 2 or 3 strongest cues into one clean mascot design.",
    "Do not literalize every noun into a separate accessory. Favor face, body shape, chest icon, ear caps, and overall color over props, effects, or costume pieces.",
  ].join(" ");
}

export function loadNanoBananaSpriteExamples(repoRoot = findRepoRoot()): NanoBananaReferenceImage[] {
  return NANO_BANANA_REFERENCE_SPRITES.flatMap((reference) => {
    const imagePath = path.join(repoRoot, reference.path);
    if (!existsSync(imagePath)) {
      return [];
    }
    return [{
      data: readFileSync(imagePath),
      label: reference.label,
      mimeType: mimeTypeForFile(imagePath),
    }];
  });
}

export function spritePrompt(request: GenerateCogSpritesRequest): string {
  const name = request.name.trim() || "new cog";
  const description = visualAppearanceBrief(request.description);

  return [
    `Cogshambo Cog builder avatar option for ${name}.`,
    `Visual brief: ${description}`,
    `Traits: defensive ${request.defensiveTrait}, active ${request.activeTrait}, TeamGoal ${request.personalGoal}.`,
    "Cute gear-shaped debate robot, readable board-scale game sprite, transparent background.",
    "Use actual PNG alpha transparency; do not draw a white, gray, checkerboard, or paper background.",
    "Match the bundled Cogshambo starter sprites exactly: glossy toy-like 3D, rounded volumes, chunky dark outline, top-left white shine spots, lower-right colored shadow, soft oval floor shadow, and cheerful lens-face details.",
    "High-detail 192px sprite with clean anti-aliased edges, bright metal highlights, tiny screws, bevels, and readable face details.",
    "Keep the cog body neutral with no shirt, jacket, torso panel, or team-colored uniform.",
    "Each generated image must contain exactly one solo cog character centered in the frame.",
    "No duplicate cogs inside a frame, no character lineup, no sprite sheet, no animation strip, no multi-view collage, no scenery, no labels, no poster composition.",
    "Crisp polished game asset, strong silhouette, expressive lens face, avoid flat 2D sticker art, chunky 8-bit blockiness, or upscaled low-resolution pixels; polished enough to hold up when displayed larger in the venue.",
  ].join(" ");
}

function visualAppearanceBrief(description: string): string {
  const trimmed = normalizeAppearanceLanguage(description.trim().replace(/\s+/g, " "));
  if (!trimmed) {
    return "A fresh Cogshambo avatar with a cute readable face, one bold body shape, and a simple chest detail.";
  }
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

function normalizeAppearanceLanguage(description: string): string {
  return description
    .replace(/\bsoft blue glow\b/gi, "soft blue highlights")
    .replace(/\bblue glow\b/gi, "blue highlights")
    .replace(/\bglowing\b/gi, "shining")
    .replace(/\bglow\b/gi, "highlight")
    .replace(/\blens face\b/gi, "cute face")
    .replace(/\bglass eye\b/gi, "big eye");
}

async function generateNanoBananaImage({
  apiKey,
  model,
  prompt,
  referenceImages,
  timeoutMs,
}: {
  apiKey: string;
  model: string;
  prompt: string;
  referenceImages: readonly NanoBananaReferenceImage[];
  timeoutMs: number;
}): Promise<NanoBananaImage> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const modelId = model.replace(/^models\//, "");
    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(modelId)}:generateContent`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": apiKey,
      },
      body: JSON.stringify({
        contents: [
          {
            parts: nanoBananaRequestParts(prompt, referenceImages),
          },
        ],
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Nano Banana ${response.status}: ${trimErrorDetail(await response.text())}`);
    }

    const body = (await response.json()) as GeminiGenerateContentResponse;
    const image = imageFromGeminiResponse(body);
    if (!image) {
      throw new Error(`Nano Banana returned no image: ${geminiText(body) || "empty response"}`);
    }

    return image;
  } catch (error) {
    if (isAbortError(error)) {
      throw new Error(`Nano Banana timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

type GeminiRequestPart =
  | { text: string }
  | { inline_data: { data: string; mime_type: string } };

function nanoBananaRequestParts(prompt: string, referenceImages: readonly NanoBananaReferenceImage[]): GeminiRequestPart[] {
  const parts: GeminiRequestPart[] = [{ text: prompt }];
  for (const image of referenceImages) {
    parts.push({
      text: `Existing Cogshambo sprite example: ${image.label}. Use this for visual style only.`,
    });
    parts.push({
      inline_data: {
        data: image.data.toString("base64"),
        mime_type: image.mimeType,
      },
    });
  }
  return parts;
}

type GeminiGenerateContentResponse = {
  candidates?: Array<{
    content?: {
      parts?: GeminiPart[];
    };
  }>;
};

type GeminiPart = {
  text?: unknown;
  inlineData?: {
    data?: unknown;
    mimeType?: unknown;
  };
  inline_data?: {
    data?: unknown;
    mime_type?: unknown;
  };
};

function imageFromGeminiResponse(body: GeminiGenerateContentResponse): NanoBananaImage | undefined {
  for (const part of geminiParts(body)) {
    const inlineData = part.inlineData ?? part.inline_data;
    const data = inlineData?.data;
    if (typeof data === "string" && data) {
      return {
        data: Buffer.from(data, "base64"),
        mimeType: mimeTypeFromInlineData(inlineData),
      };
    }
  }
  return undefined;
}

function geminiText(body: GeminiGenerateContentResponse): string {
  return geminiParts(body)
    .flatMap((part) => (typeof part.text === "string" ? [part.text] : []))
    .join(" ")
    .trim();
}

function geminiParts(body: GeminiGenerateContentResponse): GeminiPart[] {
  return body.candidates?.flatMap((candidate) => candidate.content?.parts ?? []) ?? [];
}

function mimeTypeFromInlineData(inlineData: GeminiPart["inlineData"] | GeminiPart["inline_data"] | undefined): string {
  if (!inlineData) {
    return "image/png";
  }

  const mimeType = "mimeType" in inlineData
    ? inlineData.mimeType
    : "mime_type" in inlineData
      ? inlineData.mime_type
      : undefined;
  return typeof mimeType === "string" && mimeType ? mimeType : "image/png";
}

async function normalizeNanoBananaSourceImages({
  baseName,
  env,
  outputDir,
  repoRoot,
  sourcePaths,
}: {
  baseName: string;
  env: NodeJS.ProcessEnv;
  outputDir: string;
  repoRoot: string;
  sourcePaths: string[];
}): Promise<GeneratedCogSprite[]> {
  const specPath = writeSpriteSheetSpec(baseName, {
    name: baseName,
    description: "Nano Banana generated builder avatar options",
    defensiveTrait: "stubborn",
    activeTrait: "passionate",
    personalGoal: "majority",
    spriteRoll: 0,
    count: sourcePaths.length,
  }, 0);

  await execFileAsync(
    uvCommand(),
    [
      "run",
      "--with",
      "pillow",
      "python",
      "tools/generate_sprite_sheet.py",
      specPath,
      "--output-dir",
      outputDir,
      ...sourcePaths.flatMap((sourcePath) => ["--source-image", sourcePath]),
    ],
    {
      cwd: repoRoot,
      env,
      maxBuffer: 1024 * 1024,
      timeout: 20_000,
    },
  );

  const manifestFile = path.join(outputDir, "manifest.json");
  if (!existsSync(manifestFile)) {
    throw new Error("Nano Banana normalizer did not write a manifest");
  }

  return spritesFromManifest(JSON.parse(readFileSync(manifestFile, "utf8")), sourcePaths.length);
}

export function spritesFromManifest(manifest: unknown, count: number): GeneratedCogSprite[] {
  const frames = isSpriteSheetManifest(manifest) ? manifest.frames ?? [] : [];
  return frames
    .flatMap((frame) => {
      const url = frame.url;
      return isAssetPngUrl(url) ? [{ frame, url }] : [];
    })
    .slice(0, count)
    .map(({ url }, index) => {
      return {
        key: path.basename(url, ".png"),
        label: `Sprite ${index + 1}`,
        url,
      };
    });
}

function isSpriteSheetManifest(value: unknown): value is SpriteSheetManifest {
  return typeof value === "object" && value !== null && Array.isArray((value as SpriteSheetManifest).frames);
}

function isAssetPngUrl(value: unknown): value is string {
  return typeof value === "string" && value.startsWith("/assets/cogshambo/") && value.endsWith(".png");
}

function writeSpriteSheetSpec(baseName: string, request: GenerateCogSpritesRequest, seed: number): string {
  const specsDir = path.join(tmpdir(), "cogshambo-art-specs");
  mkdirSync(specsDir, { recursive: true });
  const specPath = path.join(specsDir, `${baseName}.md`);
  writeFileSync(specPath, spriteSheetSpecText(baseName, request, seed), "utf8");
  return specPath;
}

export function spriteSheetSpecText(baseName: string, request: GenerateCogSpritesRequest, seed: number): string {
  return [
    "---",
    `name: ${baseName}`,
    "category: cogs",
    "model: rd-plus",
    "style: topdown_asset",
    `size: ${BUILDER_FRAME_SIZE}x${BUILDER_FRAME_SIZE}`,
    `frame_width: ${BUILDER_FRAME_SIZE}`,
    `frame_height: ${BUILDER_FRAME_SIZE}`,
    `columns: ${request.count}`,
    "rows: 1",
    `variants: ${request.count}`,
    `seed: ${seed}`,
    "append_defaults: true",
    "---",
    "",
    "## Prompt",
    "",
    spritePrompt(request),
    "",
  ].join("\n");
}

function loadEnv(repoRoot: string): NodeJS.ProcessEnv {
  const env = { ...process.env };
  const dotenvPath = path.join(repoRoot, ".env");
  if (!existsSync(dotenvPath)) {
    return env;
  }

  for (const rawLine of readFileSync(dotenvPath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) {
      continue;
    }

    const [rawKey, ...rawValue] = line.split("=");
    const key = rawKey.trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) || env[key]) {
      continue;
    }
    env[key] = rawValue.join("=").trim().replace(/^['"]|['"]$/g, "");
  }

  return env;
}

function findRepoRoot(): string {
  let current = path.dirname(fileURLToPath(import.meta.url));
  while (current !== path.dirname(current)) {
    if (
      existsSync(path.join(current, "package.json")) &&
      existsSync(path.join(current, "tools", "generate_sprite_sheet.py"))
    ) {
      return current;
    }
    current = path.dirname(current);
  }

  throw new Error("Unable to locate Cogshambo repo root");
}

function spriteSeed(request: GenerateCogSpritesRequest): number {
  const input = [
    request.name,
    request.description,
    request.defensiveTrait,
    request.activeTrait,
    String(request.spriteRoll),
  ].join("|");
  let hash = 2166136261;
  for (const character of input) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "")
    .slice(0, 32) || "cog";
}

function npmCommand(): string {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}

function uvCommand(): string {
  return process.platform === "win32" ? "uv.exe" : "uv";
}

function imageExtension(mimeType: string): string {
  const normalized = mimeType.toLowerCase();
  if (normalized.includes("jpeg") || normalized.includes("jpg")) {
    return ".jpg";
  }
  if (normalized.includes("webp")) {
    return ".webp";
  }
  return ".png";
}

function mimeTypeForFile(filePath: string): string {
  const extension = path.extname(filePath).toLowerCase();
  if (extension === ".jpg" || extension === ".jpeg") {
    return "image/jpeg";
  }
  if (extension === ".webp") {
    return "image/webp";
  }
  return "image/png";
}

function trimErrorDetail(value: string): string {
  return value.replace(/\s+/g, " ").trim().slice(0, 500) || "request failed";
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function positiveNumber(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
