import type { Cog, Position, WorldObject, WorldSnapshot } from "../../shared/types";
import { BOARD_BACKGROUND_KEY, colorForKey, spriteEntries } from "./atlas";
import {
  COG_SPAWN_HALO_TICKS,
  cogPositionForRender,
  cogTicksAliveForRender,
} from "./cog-render-position";
import { spriteKeyForCog, spriteUrlForCog } from "./cog-sprite-ref";
import { discoLightSpots } from "./disco-lights";
import type { RenderOptions } from "./webgpu-board-renderer";

type SpriteMap = Map<string, HTMLImageElement>;

type BoardLayout = {
  offsetX: number;
  offsetY: number;
  tileSize: number;
  tileWidth: number;
  tileHeight: number;
  boardWidth: number;
  boardHeight: number;
};

const COG_SIZE_MULTIPLIER = 1;
const COG_SPRITE_SCALE = 1.35 * COG_SIZE_MULTIPLIER;
const OBJECT_SPRITE_SCALE = 1.8;
const COG_SHADOW_WIDTH = 1.48 * COG_SIZE_MULTIPLIER;
const COG_SHADOW_HEIGHT = 0.34 * COG_SIZE_MULTIPLIER;
const COG_DEBATE_HALO_SCALE = 2.24 * COG_SIZE_MULTIPLIER;
const COG_SELECTION_GLOW_SCALE = 1.92 * COG_SIZE_MULTIPLIER;
const COG_SPAWN_HALO_SCALE = 2.32 * COG_SIZE_MULTIPLIER;
const OBJECT_SHADOW_WIDTH = 1.08;
const OBJECT_SHADOW_HEIGHT = 0.26;

export class CanvasBoardRenderer {
  private readonly context: CanvasRenderingContext2D;
  private readonly sprites: SpriteMap = new Map();
  private readonly loadingSprites = new Set<string>();
  private readonly failedSprites = new Set<string>();

  constructor(private readonly canvas: HTMLCanvasElement) {
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Could not create 2D canvas context");
    }
    this.context = context;
  }

  async initialize(): Promise<void> {
    const sprites = await Promise.all(spriteEntries().map(loadSprite));
    for (const sprite of sprites) {
      if (sprite) {
        this.sprites.set(sprite.key, sprite.image);
      }
    }
  }

  render(snapshot: WorldSnapshot | undefined, options: RenderOptions): void {
    if (!snapshot) {
      return;
    }

    this.queueDynamicSprites(snapshot);
    this.resize();

    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = this.canvas.width / ratio;
    const height = this.canvas.height / ratio;
    const layout = fitBoard(width, height, snapshot.dimensions.width, snapshot.dimensions.height);
    const frameTimeMs = options.discoLightTimeMs ?? performance.now();

    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.context.clearRect(0, 0, width, height);
    this.drawBackground(width, height, snapshot);

    if (options.discoMode && snapshot.venue) {
      this.drawDiscoLights(layout, frameTimeMs);
    }

    for (const object of [...snapshot.objects].sort(depthSort)) {
      this.drawObject(object, layout);
    }

    for (const cog of [...snapshot.cogs].sort(depthSort)) {
      this.drawCog(cog, snapshot, options, layout, frameTimeMs);
    }
  }

  private resize(): void {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.floor(this.canvas.clientWidth * ratio));
    const height = Math.max(1, Math.floor(this.canvas.clientHeight * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
  }

  private drawBackground(width: number, height: number, snapshot: WorldSnapshot): void {
    const background = this.sprites.get(BOARD_BACKGROUND_KEY);
    if (background) {
      this.context.imageSmoothingEnabled = true;
      drawImageCover(this.context, background, 0, 0, width, height);
      this.context.imageSmoothingEnabled = false;
      return;
    }

    const gradient = this.context.createLinearGradient(0, 0, width, height);
    gradient.addColorStop(0, "#181413");
    gradient.addColorStop(0.48, "#221b19");
    gradient.addColorStop(1, "#0f1110");
    this.context.fillStyle = gradient;
    this.context.fillRect(0, 0, width, height);

    const layout = fitBoard(width, height, snapshot.dimensions.width, snapshot.dimensions.height);
    for (let y = 0; y < snapshot.dimensions.height; y += 1) {
      for (let x = 0; x < snapshot.dimensions.width; x += 1) {
        this.fillCell(x, y, layout, colorForKey((x + y) % 2 === 0 ? "tile" : "tile-alt"));
      }
    }
  }

  private fillCell(
    x: number,
    y: number,
    layout: BoardLayout,
    color: [number, number, number, number],
    scale = 0.92,
  ): void {
    const [centerX, centerY] = cellCenter(x, y, layout);
    const halfWidth = (layout.tileWidth * scale) / 2;
    const halfHeight = (layout.tileHeight * scale) / 2;
    this.context.fillStyle = rgba(color);
    this.context.fillRect(centerX - halfWidth, centerY - halfHeight, halfWidth * 2, halfHeight * 2);
  }

  private drawObject(object: WorldObject, layout: BoardLayout): void {
    if (isMapObjectMarker(object)) {
      return;
    }

    const [centerX, centerY] = cellCenter(object.position.x, object.position.y, layout);
    this.drawGroundShadow(centerX, centerY, layout, OBJECT_SHADOW_WIDTH, OBJECT_SHADOW_HEIGHT, 0.42);

    const sprite = this.sprites.get(object.spriteKey);
    if (!sprite) {
      this.fillCell(object.position.x, object.position.y, layout, colorForKey(object.spriteKey), 0.72);
      return;
    }

    const size = layout.tileSize * OBJECT_SPRITE_SCALE;
    this.context.drawImage(sprite, centerX - size / 2, centerY - size / 2, size, size);
  }

  private drawCog(
    cog: Cog,
    snapshot: WorldSnapshot,
    options: RenderOptions,
    layout: BoardLayout,
    frameTimeMs: number,
  ): void {
    const position = cogPositionForRender(cog, snapshot, frameTimeMs, options.renderTiming);
    const [centerX, centerY] = cellCenter(position.x, position.y, layout);
    const spawnTicksAlive = cogTicksAliveForRender(cog, options.renderTiming, frameTimeMs);
    const spriteKey = spriteKeyForCog(cog);
    const spriteUrl = spriteUrlForCog(cog);

    if (spriteUrl && !this.sprites.has(spriteKey) && !this.failedSprites.has(spriteKey)) {
      this.loadDynamicSprite(spriteKey, spriteUrl);
    }

    this.drawGroundShadow(centerX, centerY, layout, COG_SHADOW_WIDTH, COG_SHADOW_HEIGHT, 0.52);

    if (spawnTicksAlive < COG_SPAWN_HALO_TICKS) {
      this.drawHalo(centerX, centerY, layout, COG_SPAWN_HALO_SCALE, colorForKey("spawn-halo"));
    }
    if (cog.debate) {
      this.drawHalo(centerX, centerY, layout, COG_DEBATE_HALO_SCALE, colorForKey("debate"));
    }
    if (cog.id === options.selectedCogId) {
      this.drawHalo(centerX, centerY, layout, COG_SELECTION_GLOW_SCALE, colorForKey("selection-halo"));
    }

    const sprite = this.sprites.get(spriteKey) ?? this.sprites.get(cog.spriteSheetKey) ?? this.sprites.get("cog-default");
    if (sprite) {
      const size = layout.tileSize * COG_SPRITE_SCALE;
      this.context.drawImage(sprite, centerX - size / 2, centerY - size / 2, size, size);
    } else {
      this.context.fillStyle = rgba(colorForKey(`team-${cog.color}`));
      this.context.beginPath();
      this.context.ellipse(
        centerX,
        centerY,
        layout.tileSize * 0.7 * COG_SIZE_MULTIPLIER,
        layout.tileSize * 0.7 * COG_SIZE_MULTIPLIER,
        0,
        0,
        Math.PI * 2,
      );
      this.context.fill();
    }

    this.drawTeamHat(cog, centerX, centerY, layout, options.discoMode ?? false);
  }

  private drawGroundShadow(
    centerX: number,
    centerY: number,
    layout: BoardLayout,
    widthScale: number,
    heightScale: number,
    yOffsetScale: number,
  ): void {
    this.context.save();
    this.context.fillStyle = rgba(colorForKey("shadow"));
    this.context.beginPath();
    this.context.ellipse(
      centerX + layout.tileSize * 0.08,
      centerY + layout.tileSize * yOffsetScale,
      layout.tileSize * widthScale * 0.5,
      layout.tileSize * heightScale * 0.5,
      0,
      0,
      Math.PI * 2,
    );
    this.context.fill();
    this.context.restore();
  }

  private drawHalo(
    centerX: number,
    centerY: number,
    layout: BoardLayout,
    scale: number,
    color: [number, number, number, number],
  ): void {
    const radius = (layout.tileSize * scale) / 2;
    this.context.save();
    this.context.shadowColor = rgba(withAlpha(color, 0.7));
    this.context.shadowBlur = Math.max(8, layout.tileSize * 0.32);
    this.context.fillStyle = rgba(withAlpha(color, 0.22));
    this.context.beginPath();
    this.context.ellipse(centerX, centerY, radius, radius * 0.9, 0, 0, Math.PI * 2);
    this.context.fill();
    this.context.lineWidth = Math.max(2, layout.tileSize * 0.07);
    this.context.strokeStyle = rgba(withAlpha(color, 0.64));
    this.context.stroke();
    this.context.restore();
  }

  private drawTeamHat(cog: Cog, centerX: number, centerY: number, layout: BoardLayout, discoMode: boolean): void {
    const tileSize = layout.tileSize * COG_SIZE_MULTIPLIER;
    this.context.save();
    this.context.lineJoin = "round";
    this.context.lineWidth = Math.max(1, tileSize * 0.035);
    this.context.strokeStyle = "rgba(8, 12, 12, 0.72)";
    this.context.fillStyle = discoMode ? "#ffffff" : rgba(colorForKey(`team-${cog.color}`));

    if (discoMode) {
      const hatWidth = tileSize * 0.68;
      const baseY = centerY - tileSize * 0.29;
      const tipY = centerY - tileSize * 1.09;
      this.context.beginPath();
      this.context.moveTo(centerX, tipY);
      this.context.lineTo(centerX + hatWidth / 2, baseY);
      this.context.lineTo(centerX - hatWidth / 2, baseY);
      this.context.closePath();
      this.context.fill();
      this.context.stroke();
      this.context.restore();
      return;
    }

    const brimWidth = tileSize * 0.78;
    const brimHeight = Math.max(3, tileSize * 0.14);
    const capWidth = tileSize * 0.5;
    const capHeight = tileSize * 0.34;
    const brimY = centerY - tileSize * 0.42;
    const capTop = centerY - tileSize * 0.79;

    this.context.beginPath();
    this.context.moveTo(centerX - capWidth * 0.42, capTop);
    this.context.lineTo(centerX + capWidth * 0.42, capTop);
    this.context.lineTo(centerX + capWidth * 0.5, brimY);
    this.context.lineTo(centerX - capWidth * 0.5, brimY);
    this.context.closePath();
    this.context.fill();
    this.context.stroke();

    this.context.beginPath();
    this.context.rect(centerX - brimWidth / 2, brimY - brimHeight / 2, brimWidth, brimHeight);
    this.context.fill();
    this.context.stroke();

    this.context.fillStyle = "rgba(255, 255, 255, 0.24)";
    this.context.fillRect(centerX - capWidth * 0.27, capTop + capHeight * 0.22, capWidth * 0.18, capHeight * 0.58);
    this.context.restore();
  }

  private drawDiscoLights(layout: BoardLayout, timeMs: number): void {
    this.context.save();
    this.context.globalCompositeOperation = "screen";
    for (const spot of discoLightSpots(timeMs)) {
      const centerX = layout.offsetX + spot.x * layout.boardWidth;
      const centerY = layout.offsetY + spot.y * layout.boardHeight;
      const radiusX = Math.max(10, spot.radiusX * layout.boardWidth);
      const radiusY = Math.max(7, spot.radiusY * layout.boardHeight);

      this.context.save();
      this.context.translate(centerX, centerY);
      this.context.scale(radiusX, radiusY);
      const gradient = this.context.createRadialGradient(0, 0, 0, 0, 0, 1);
      gradient.addColorStop(0, rgba(withAlpha(spot.color, 0.48)));
      gradient.addColorStop(0.42, rgba(spot.color));
      gradient.addColorStop(1, rgba(withAlpha(spot.color, 0)));
      this.context.fillStyle = gradient;
      this.context.beginPath();
      this.context.arc(0, 0, 1, 0, Math.PI * 2);
      this.context.fill();
      this.context.restore();
    }
    this.context.restore();
  }

  private queueDynamicSprites(snapshot: WorldSnapshot): void {
    for (const cog of snapshot.cogs) {
      const spriteUrl = spriteUrlForCog(cog);
      const spriteKey = spriteKeyForCog(cog);
      if (spriteUrl && !this.sprites.has(spriteKey) && !this.failedSprites.has(spriteKey)) {
        this.loadDynamicSprite(spriteKey, spriteUrl);
      }
    }
  }

  private loadDynamicSprite(key: string, spriteUrl: string): void {
    if (this.loadingSprites.has(key)) {
      return;
    }

    this.loadingSprites.add(key);
    void loadSprite({ key, spriteUrl }).then((sprite) => {
      if (sprite) {
        this.sprites.set(sprite.key, sprite.image);
      } else {
        this.failedSprites.add(key);
      }
      this.loadingSprites.delete(key);
    });
  }
}

async function loadSprite(entry: { key: string; spriteUrl: string }): Promise<{ key: string; image: HTMLImageElement } | undefined> {
  const image = new Image();
  image.decoding = "async";
  image.src = entry.spriteUrl;

  try {
    await image.decode();
    return { key: entry.key, image };
  } catch (error) {
    console.warn(`Canvas sprite unavailable for ${entry.key}: ${compactLoadError(error)}`);
    return undefined;
  }
}

function fitBoard(width: number, height: number, columns: number, rows: number): BoardLayout {
  const boardRatio = columns / rows;
  const targetRatio = width / height;
  const boardWidth = targetRatio > boardRatio ? height * boardRatio : width;
  const boardHeight = targetRatio > boardRatio ? height : width / boardRatio;
  const tileWidth = boardWidth / columns;
  const tileHeight = boardHeight / rows;
  return {
    offsetX: (width - boardWidth) / 2,
    offsetY: (height - boardHeight) / 2,
    tileSize: Math.min(tileWidth, tileHeight),
    tileWidth,
    tileHeight,
    boardWidth,
    boardHeight,
  };
}

function cellCenter(x: number, y: number, layout: BoardLayout): [number, number] {
  return [layout.offsetX + (x + 0.5) * layout.tileWidth, layout.offsetY + (y + 0.5) * layout.tileHeight];
}

function drawImageCover(
  context: CanvasRenderingContext2D,
  image: CanvasImageSource,
  x: number,
  y: number,
  width: number,
  height: number,
): void {
  const sourceWidth = "naturalWidth" in image ? image.naturalWidth : Number(image.width);
  const sourceHeight = "naturalHeight" in image ? image.naturalHeight : Number(image.height);
  const scale = Math.max(width / sourceWidth, height / sourceHeight);
  const drawWidth = sourceWidth * scale;
  const drawHeight = sourceHeight * scale;
  context.drawImage(image, x + (width - drawWidth) / 2, y + (height - drawHeight) / 2, drawWidth, drawHeight);
}

function rgba(color: [number, number, number, number]): string {
  const [r, g, b, a] = color;
  return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
}

function withAlpha(color: [number, number, number, number], alpha: number): [number, number, number, number] {
  return [color[0], color[1], color[2], alpha];
}

function isMapObjectMarker(object: WorldObject): boolean {
  return (
    object.type === "picknick" ||
    object.type === "bench" ||
    object.type === "stairs" ||
    object.type === "tree" ||
    object.type === "block"
  );
}

function depthSort(a: { position: Position }, b: { position: Position }): number {
  return a.position.y - b.position.y || a.position.x - b.position.x;
}

function compactLoadError(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "unknown error";
}
