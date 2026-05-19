import type { Cog, Position, WorldSnapshot } from "../../shared/types";
import { BOARD_BACKGROUND_KEY, colorForKey, spriteEntries } from "./atlas";
import { spriteEntriesForCog, spriteKeyForCog } from "./cog-sprite-ref";
import {
  COG_SPAWN_HALO_TICKS,
  cogPositionForRender,
  cogTicksAliveForRender,
  type CogRenderTiming,
} from "./cog-render-position";
import { discoLightSpots } from "./disco-lights";
import { boardShader } from "./shaders";

export type BoardRenderInstance = {
  center: [number, number];
  size: [number, number];
  color: [number, number, number, number];
  cogId?: string;
  role?: "debate-halo" | "disco-light" | "party-hat" | "spawn-halo" | "team-hat";
  uvRect: [number, number, number, number];
  textureMix: number;
};

type SpriteRegion = [number, number, number, number];

type LoadedSprite = {
  key: string;
  bitmap: ImageBitmap;
};

type SpriteEntry = {
  key: string;
  spriteUrl: string;
};

type PlacedSprite = LoadedSprite & {
  x: number;
  y: number;
};

type BoardLayout = {
  offsetX: number;
  offsetY: number;
  tileSize: number;
  width: number;
  height: number;
  boardWidth: number;
  boardHeight: number;
};

const FLOATS_PER_INSTANCE = 13;
const EMPTY_UV_RECT: SpriteRegion = [0, 0, 1, 1];
const TILE_FILL_SCALE = 0.92;
const COG_SIZE_MULTIPLIER = 1;
const COG_SPRITE_SCALE = 1.35 * COG_SIZE_MULTIPLIER;
const OBJECT_SPRITE_SCALE = 1.8;
const SOLID_QUAD_RENDER_MODE = 0;
const TEXTURE_RENDER_MODE = 1;
const ELLIPSE_RENDER_MODE = -1;
const HALO_RENDER_MODE = -2;
const TRIANGLE_RENDER_MODE = -3;
const RAINBOW_TRIANGLE_RENDER_MODE = -4;
const DISCO_PARTY_HAT_COLOR: [number, number, number, number] = [1, 1, 1, 1];
const COG_SHADOW_WIDTH = 1.48 * COG_SIZE_MULTIPLIER;
const COG_SHADOW_HEIGHT = 0.34 * COG_SIZE_MULTIPLIER;
const COG_DEBATE_HALO_SCALE = 2.24 * COG_SIZE_MULTIPLIER;
const COG_SELECTION_GLOW_SCALE = 1.92 * COG_SIZE_MULTIPLIER;
const COG_SPAWN_HALO_SCALE = 2.32 * COG_SIZE_MULTIPLIER;
const ZEALOT_HAT_CAP_WIDTH = 0.5 * COG_SIZE_MULTIPLIER;
const ZEALOT_HAT_CAP_HEIGHT = 0.34 * COG_SIZE_MULTIPLIER;
const ZEALOT_HAT_BRIM_WIDTH = 0.78 * COG_SIZE_MULTIPLIER;
const ZEALOT_HAT_BRIM_HEIGHT = 0.14 * COG_SIZE_MULTIPLIER;
const PARTY_HAT_WIDTH = 0.68 * COG_SIZE_MULTIPLIER;
const PARTY_HAT_HEIGHT = 0.8 * COG_SIZE_MULTIPLIER;
const PARTY_HAT_Y_OFFSET = 0.69 * COG_SIZE_MULTIPLIER;
const OBJECT_SHADOW_WIDTH = 1.08;
const OBJECT_SHADOW_HEIGHT = 0.26;

export type RenderOptions = {
  discoLightTimeMs?: number;
  discoMode?: boolean;
  renderTiming?: CogRenderTiming;
  selectedCogId: string | undefined;
};

export type WebGpuBoardRendererOptions = {
  onDeviceLost?: (message: string) => void;
};

export class WebGpuBoardRenderer {
  private device: GPUDevice | undefined;
  private context: GPUCanvasContext | undefined;
  private pipeline: GPURenderPipeline | undefined;
  private spriteBindGroup: GPUBindGroup | undefined;
  private spriteTexture: GPUTexture | undefined;
  private vertexBuffer: GPUBuffer | undefined;
  private instanceBuffer: GPUBuffer | undefined;
  private instanceBufferByteLength = 0;
  private format: GPUTextureFormat | undefined;
  private readonly spriteRegions = new Map<string, SpriteRegion>();
  private readonly dynamicSpriteEntries = new Map<string, string>();
  private atlasRebuild: Promise<void> | undefined;
  private atlasNeedsRebuild = false;
  private unusable = false;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly options: WebGpuBoardRendererOptions = {},
  ) {}

  async initialize(): Promise<void> {
    if (!navigator.gpu) {
      throw new Error("WebGPU is not available in this browser");
    }

    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) {
      throw new Error("No WebGPU adapter is available");
    }

    this.device = await adapter.requestDevice();
    this.watchDeviceLoss(this.device);
    this.context = this.canvas.getContext("webgpu") ?? undefined;
    if (!this.context) {
      throw new Error("Could not create WebGPU canvas context");
    }

    this.format = navigator.gpu.getPreferredCanvasFormat();
    this.resize();
    this.configureContext();

    const shader = this.device.createShaderModule({ code: boardShader });
    this.pipeline = this.device.createRenderPipeline({
      layout: "auto",
      vertex: {
        module: shader,
        entryPoint: "vertexMain",
        buffers: [
          {
            arrayStride: 8,
            attributes: [{ shaderLocation: 0, offset: 0, format: "float32x2" }],
          },
          {
            arrayStride: FLOATS_PER_INSTANCE * 4,
            stepMode: "instance",
            attributes: [
              { shaderLocation: 1, offset: 0, format: "float32x2" },
              { shaderLocation: 2, offset: 8, format: "float32x2" },
              { shaderLocation: 3, offset: 16, format: "float32x4" },
              { shaderLocation: 4, offset: 32, format: "float32x4" },
              { shaderLocation: 5, offset: 48, format: "float32" },
            ],
          },
        ],
      },
      fragment: {
        module: shader,
        entryPoint: "fragmentMain",
        targets: [
          {
            format: this.format,
            blend: {
              color: {
                operation: "add",
                srcFactor: "src-alpha",
                dstFactor: "one-minus-src-alpha",
              },
              alpha: {
                operation: "add",
                srcFactor: "one",
                dstFactor: "one-minus-src-alpha",
              },
            },
          },
        ],
      },
      primitive: {
        topology: "triangle-strip",
      },
    });

    await this.initializeSpriteAtlas(this.device, this.pipeline.getBindGroupLayout(0));

    this.vertexBuffer = this.device.createBuffer({
      size: 32,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    });
    this.device.queue.writeBuffer(
      this.vertexBuffer,
      0,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
    );
  }

  resize(): void {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.floor(this.canvas.clientWidth * ratio));
    const height = Math.max(1, Math.floor(this.canvas.clientHeight * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
      this.configureContext();
    }
  }

  render(snapshot: WorldSnapshot | undefined, options: RenderOptions): void {
    if (
      this.unusable ||
      !this.device ||
      !this.context ||
      !this.pipeline ||
      !this.spriteBindGroup ||
      !this.vertexBuffer ||
      !snapshot
    ) {
      return;
    }

    this.queueDynamicSprites(snapshot);
    this.resize();
    const frameOptions = { ...options, discoLightTimeMs: renderTimeMs(options) };
    const instances = this.createInstances(snapshot, frameOptions, frameOptions.renderTiming);
    const data = new Float32Array(instances.length * FLOATS_PER_INSTANCE);
    instances.forEach((instance, index) => {
      const offset = index * FLOATS_PER_INSTANCE;
      data.set(instance.center, offset);
      data.set(instance.size, offset + 2);
      data.set(instance.color, offset + 4);
      data.set(instance.uvRect, offset + 8);
      data[offset + 12] = instance.textureMix;
    });

    const requiredBytes = Math.max(data.byteLength, 32);
    if (!this.instanceBuffer || this.instanceBufferByteLength < requiredBytes) {
      this.instanceBuffer?.destroy();
      this.instanceBuffer = this.device.createBuffer({
        size: requiredBytes,
        usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
      });
      this.instanceBufferByteLength = requiredBytes;
    }

    this.device.queue.writeBuffer(this.instanceBuffer, 0, data);

    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: this.context.getCurrentTexture().createView(),
          loadOp: "clear",
          storeOp: "store",
          clearValue: { r: 0.04, g: 0.06, b: 0.065, a: 1 },
        },
      ],
    });

    pass.setPipeline(this.pipeline);
    pass.setBindGroup(0, this.spriteBindGroup);
    pass.setVertexBuffer(0, this.vertexBuffer);
    pass.setVertexBuffer(1, this.instanceBuffer);
    pass.draw(4, instances.length);
    pass.end();
    this.device.queue.submit([encoder.finish()]);
  }

  private createInstances(snapshot: WorldSnapshot, options: RenderOptions, timing: CogRenderTiming | undefined): BoardRenderInstance[] {
    return createBoardInstances(snapshot, options, this.spriteRegions, this.canvas.width, this.canvas.height, timing);
  }

  private configureContext(): void {
    if (!this.device || !this.context || !this.format) {
      return;
    }

    this.context.configure({
      device: this.device,
      format: this.format,
      alphaMode: "opaque",
    });
  }

  private async initializeSpriteAtlas(device: GPUDevice, layout: GPUBindGroupLayout): Promise<void> {
    const dynamicEntries = Array.from(this.dynamicSpriteEntries, ([key, spriteUrl]) => ({ key, spriteUrl }));
    const loadedSprites = await loadSprites([...spriteEntries(), ...dynamicEntries]);
    const atlas = buildAtlasCanvas(loadedSprites);
    this.spriteRegions.clear();
    atlas.regions.forEach((region, key) => this.spriteRegions.set(key, region));

    this.spriteTexture?.destroy();
    this.spriteTexture = device.createTexture({
      size: { width: atlas.width, height: atlas.height },
      format: "rgba8unorm",
      usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT,
    });
    device.queue.copyExternalImageToTexture(
      { source: atlas.source },
      { texture: this.spriteTexture },
      { width: atlas.width, height: atlas.height },
    );

    const sampler = device.createSampler({
      addressModeU: "clamp-to-edge",
      addressModeV: "clamp-to-edge",
      magFilter: "nearest",
      minFilter: "nearest",
    });
    this.spriteBindGroup = device.createBindGroup({
      layout,
      entries: [
        { binding: 0, resource: sampler },
        { binding: 1, resource: this.spriteTexture.createView() },
      ],
    });

    loadedSprites.forEach((sprite) => sprite.bitmap.close());
  }

  private queueDynamicSprites(snapshot: WorldSnapshot): void {
    let added = false;
    for (const cog of snapshot.cogs) {
      for (const entry of spriteEntriesForCog(cog)) {
        if (this.spriteRegions.has(entry.key) || this.dynamicSpriteEntries.has(entry.key)) {
          continue;
        }
        this.dynamicSpriteEntries.set(entry.key, entry.spriteUrl);
        added = true;
      }
    }

    if (added) {
      this.scheduleSpriteAtlasRebuild();
    }
  }

  private scheduleSpriteAtlasRebuild(): void {
    if (this.atlasRebuild) {
      this.atlasNeedsRebuild = true;
      return;
    }

    const device = this.device;
    const pipeline = this.pipeline;
    if (!device || !pipeline) {
      return;
    }

    this.atlasRebuild = this.initializeSpriteAtlas(device, pipeline.getBindGroupLayout(0))
      .catch((error) => {
        console.warn(`Sprite atlas refresh failed: ${compactLoadError(error)}`);
      })
      .finally(() => {
        this.atlasRebuild = undefined;
        if (this.atlasNeedsRebuild) {
          this.atlasNeedsRebuild = false;
          this.scheduleSpriteAtlasRebuild();
        }
      });
  }

  private watchDeviceLoss(device: GPUDevice): void {
    void device.lost.then((info) => {
      if (this.device !== device) {
        return;
      }

      this.unusable = true;
      this.instanceBuffer?.destroy();
      this.vertexBuffer?.destroy();
      this.spriteTexture?.destroy();
      this.device = undefined;
      this.context = undefined;
      this.pipeline = undefined;
      this.spriteBindGroup = undefined;
      this.spriteTexture = undefined;
      this.vertexBuffer = undefined;
      this.instanceBuffer = undefined;
      this.instanceBufferByteLength = 0;
      this.format = undefined;
      this.options.onDeviceLost?.(deviceLossMessage(info));
    });
  }
}

export function createBoardInstancesForTest(
  snapshot: WorldSnapshot,
  options: RenderOptions,
  timing?: CogRenderTiming,
): BoardRenderInstance[] {
  return createBoardInstances(snapshot, options, new Map(), 800, 450, timing);
}

function createBoardInstances(
  snapshot: WorldSnapshot,
  options: RenderOptions,
  spriteRegions: ReadonlyMap<string, SpriteRegion>,
  width: number,
  height: number,
  timing?: CogRenderTiming,
): BoardRenderInstance[] {
  const layout = fitBoard(width, height, snapshot.dimensions.width, snapshot.dimensions.height);
  const frameTimeMs = renderTimeMs(options);
  const instances: BoardRenderInstance[] = [];
  const backgroundUvRect = spriteRegions.get(BOARD_BACKGROUND_KEY);

  if (backgroundUvRect) {
    instances.push({
      center: [0, 0],
      size: [1, 1],
      color: colorForKey(BOARD_BACKGROUND_KEY),
      uvRect: coverUvRect(backgroundUvRect, 16 / 9, layout.width / layout.height),
      textureMix: TEXTURE_RENDER_MODE,
    });
  } else {
    for (let y = 0; y < snapshot.dimensions.height; y += 1) {
      for (let x = 0; x < snapshot.dimensions.width; x += 1) {
        instances.push({
          center: ndcCenter(x, y, layout),
          size: ndcSize(layout, TILE_FILL_SCALE),
          color: colorForKey((x + y) % 2 === 0 ? "tile" : "tile-alt"),
          uvRect: EMPTY_UV_RECT,
          textureMix: SOLID_QUAD_RENDER_MODE,
        });
      }
    }
  }

  for (const cell of snapshot.terrain) {
    instances.push({
      center: ndcCenter(cell.position.x, cell.position.y, layout),
      size: ndcSize(layout, TILE_FILL_SCALE),
      color: colorForKey(`terrain-${cell.terrain}`),
      uvRect: EMPTY_UV_RECT,
      textureMix: SOLID_QUAD_RENDER_MODE,
    });
  }

  if (options.discoMode && snapshot.venue) {
    pushDiscoLights(instances, layout, frameTimeMs);
  }

  for (const object of snapshot.objects) {
    if (isMapObjectMarker(object)) {
      continue;
    }

    pushShadow(instances, object.position, layout, OBJECT_SHADOW_WIDTH, OBJECT_SHADOW_HEIGHT, 0.42);

    instances.push({
      center: ndcCenter(object.position.x, object.position.y, layout),
      size: ndcSize(layout, OBJECT_SPRITE_SCALE),
      color: colorForKey(object.spriteKey),
      uvRect: spriteRegions.get(object.spriteKey) ?? EMPTY_UV_RECT,
      textureMix: spriteRegions.has(object.spriteKey) ? TEXTURE_RENDER_MODE : SOLID_QUAD_RENDER_MODE,
    });
  }

  for (const cog of snapshot.cogs) {
    const position = cogPositionForRender(cog, snapshot, frameTimeMs, timing);
    const spawnTicksAlive = cogTicksAliveForRender(cog, timing, frameTimeMs);
    const renderedCog = { ...cog, position };
    const selected = cog.id === options.selectedCogId;
    pushShadow(instances, position, layout, COG_SHADOW_WIDTH, COG_SHADOW_HEIGHT, 0.52 * COG_SIZE_MULTIPLIER);
    if (spawnTicksAlive < COG_SPAWN_HALO_TICKS) {
      instances.push({
        center: ndcCenter(position.x, position.y, layout),
        size: ndcSize(layout, COG_SPAWN_HALO_SCALE),
        color: colorForKey("spawn-halo"),
        cogId: cog.id,
        role: "spawn-halo",
        uvRect: EMPTY_UV_RECT,
        textureMix: HALO_RENDER_MODE,
      });
    }
    if (cog.debate) {
      instances.push({
        center: ndcCenter(position.x, position.y, layout),
        size: ndcSize(layout, COG_DEBATE_HALO_SCALE),
        color: colorForKey("debate"),
        cogId: cog.id,
        role: "debate-halo",
        uvRect: EMPTY_UV_RECT,
        textureMix: HALO_RENDER_MODE,
      });
    }
    if (selected) {
      instances.push({
        center: ndcCenter(position.x, position.y, layout),
        size: ndcSize(layout, COG_SELECTION_GLOW_SCALE),
        color: colorForKey("selection-halo"),
        uvRect: EMPTY_UV_RECT,
        textureMix: HALO_RENDER_MODE,
      });
    }

    const spriteKey = spriteKeyForCog(cog);
    const uvRect = spriteRegions.get(spriteKey);
    instances.push({
      center: ndcCenter(position.x, position.y, layout),
      size: ndcSize(layout, COG_SPRITE_SCALE),
      color: uvRect ? [1, 1, 1, 1] : colorForCog(cog, selected),
      uvRect: uvRect ?? EMPTY_UV_RECT,
      textureMix: uvRect ? TEXTURE_RENDER_MODE : ELLIPSE_RENDER_MODE,
    });

    pushTeamHat(instances, renderedCog, layout, options.discoMode ?? false);
  }

  return instances;
}

async function loadSprites(entries: SpriteEntry[]): Promise<LoadedSprite[]> {
  const results = await Promise.all(
    entries.map(async (entry): Promise<LoadedSprite | undefined> => {
      try {
        const response = await fetch(entry.spriteUrl);
        if (!response.ok) {
          throw new Error(`${response.status} ${response.statusText}`.trim());
        }

        return {
          key: entry.key,
          bitmap: await createImageBitmap(await response.blob()),
        };
      } catch (error) {
        console.warn(`Sprite unavailable for ${entry.key}: ${compactLoadError(error)}`);
        return undefined;
      }
    }),
  );

  return results.filter((sprite): sprite is LoadedSprite => Boolean(sprite));
}

function buildAtlasCanvas(sprites: LoadedSprite[]): {
  source: HTMLCanvasElement | OffscreenCanvas;
  width: number;
  height: number;
  regions: Map<string, SpriteRegion>;
} {
  const padding = 2;
  const maxWidth = 1024;
  const placed: PlacedSprite[] = [];
  let x = padding;
  let y = padding;
  let rowHeight = 0;
  let atlasWidth = padding;

  for (const sprite of sprites) {
    if (x + sprite.bitmap.width + padding > maxWidth && rowHeight > 0) {
      x = padding;
      y += rowHeight + padding;
      rowHeight = 0;
    }

    placed.push({ ...sprite, x, y });
    x += sprite.bitmap.width + padding;
    rowHeight = Math.max(rowHeight, sprite.bitmap.height);
    atlasWidth = Math.max(atlasWidth, x);
  }

  const width = Math.max(atlasWidth, 1);
  const height = Math.max(y + rowHeight + padding, 1);
  const source = createCanvas(width, height);
  const context = source.getContext("2d");
  if (!context) {
    throw new Error("Could not create sprite atlas canvas");
  }
  context.clearRect(0, 0, width, height);

  const regions = new Map<string, SpriteRegion>();
  for (const sprite of placed) {
    context.drawImage(sprite.bitmap, sprite.x, sprite.y);
    regions.set(sprite.key, [
      sprite.x / width,
      sprite.y / height,
      (sprite.x + sprite.bitmap.width) / width,
      (sprite.y + sprite.bitmap.height) / height,
    ]);
  }

  return { source, width, height, regions };
}

function createCanvas(width: number, height: number): HTMLCanvasElement | OffscreenCanvas {
  if (typeof OffscreenCanvas !== "undefined") {
    return new OffscreenCanvas(width, height);
  }

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

function colorForCog(cog: Cog, selected: boolean): [number, number, number, number] {
  if (selected) {
    return [1, 1, 1, 1];
  }

  return colorForKey(`team-${cog.color}`);
}

function pushTeamHat(instances: BoardRenderInstance[], cog: Cog, layout: BoardLayout, discoMode: boolean): void {
  if (discoMode) {
    instances.push({
      center: ndcCenter(cog.position.x, cog.position.y - PARTY_HAT_Y_OFFSET, layout),
      size: ndcRectSize(layout, PARTY_HAT_WIDTH, PARTY_HAT_HEIGHT),
      color: DISCO_PARTY_HAT_COLOR,
      cogId: cog.id,
      role: "party-hat",
      uvRect: EMPTY_UV_RECT,
      textureMix: RAINBOW_TRIANGLE_RENDER_MODE,
    });
    return;
  }

  const color = colorForKey(`team-${cog.color}`);
  const parts = [
    {
      centerY: cog.position.y - 0.62 * COG_SIZE_MULTIPLIER,
      size: ndcRectSize(layout, ZEALOT_HAT_CAP_WIDTH, ZEALOT_HAT_CAP_HEIGHT),
    },
    {
      centerY: cog.position.y - 0.42 * COG_SIZE_MULTIPLIER,
      size: ndcRectSize(layout, ZEALOT_HAT_BRIM_WIDTH, ZEALOT_HAT_BRIM_HEIGHT),
    },
  ];

  for (const part of parts) {
    instances.push({
      center: ndcCenter(cog.position.x, part.centerY, layout),
      size: part.size,
      color,
      cogId: cog.id,
      role: "team-hat",
      uvRect: EMPTY_UV_RECT,
      textureMix: SOLID_QUAD_RENDER_MODE,
    });
  }
}

function pushDiscoLights(instances: BoardRenderInstance[], layout: BoardLayout, timeMs: number): void {
  for (const spot of discoLightSpots(timeMs)) {
    instances.push({
      center: ndcCanvasPoint(
        layout.offsetX + spot.x * layout.boardWidth,
        layout.offsetY + spot.y * layout.boardHeight,
        layout,
      ),
      size: [
        (spot.radiusX * layout.boardWidth * 2) / layout.width,
        (spot.radiusY * layout.boardHeight * 2) / layout.height,
      ],
      color: spot.color,
      role: "disco-light",
      uvRect: EMPTY_UV_RECT,
      textureMix: ELLIPSE_RENDER_MODE,
    });
  }
}

function renderTimeMs(options: RenderOptions): number {
  if (typeof options.discoLightTimeMs === "number") {
    return options.discoLightTimeMs;
  }

  return typeof performance === "undefined" ? 0 : performance.now();
}

function fitBoard(width: number, height: number, columns: number, rows: number): BoardLayout {
  const tileSize = Math.min(width / columns, height / rows);
  return {
    offsetX: (width - columns * tileSize) / 2,
    offsetY: (height - rows * tileSize) / 2,
    tileSize,
    width,
    height,
    boardWidth: columns * tileSize,
    boardHeight: rows * tileSize,
  };
}

function ndcCenter(x: number, y: number, layout: BoardLayout): [number, number] {
  const centerX = layout.offsetX + x * layout.tileSize + layout.tileSize / 2;
  const centerY = layout.offsetY + y * layout.tileSize + layout.tileSize / 2;
  return ndcCanvasPoint(centerX, centerY, layout);
}

function ndcCanvasPoint(centerX: number, centerY: number, layout: BoardLayout): [number, number] {
  return [(centerX / layout.width) * 2 - 1, 1 - (centerY / layout.height) * 2];
}

function pushShadow(
  instances: BoardRenderInstance[],
  position: Position,
  layout: BoardLayout,
  widthScale: number,
  heightScale: number,
  yOffsetScale: number,
): void {
  instances.push({
    center: ndcCenter(position.x, position.y + yOffsetScale, layout),
    size: ndcRectSize(layout, widthScale, heightScale),
    color: colorForKey("shadow"),
    uvRect: EMPTY_UV_RECT,
    textureMix: ELLIPSE_RENDER_MODE,
  });
}

function isMapObjectMarker(object: { type: string }): boolean {
  return (
    object.type === "picknick" ||
    object.type === "bench" ||
    object.type === "stairs" ||
    object.type === "tree" ||
    object.type === "block"
  );
}

function coverUvRect(uvRect: SpriteRegion, sourceRatio: number, targetRatio: number): SpriteRegion {
  const [u0, v0, u1, v1] = uvRect;
  if (sourceRatio > targetRatio) {
    const visibleWidth = targetRatio / sourceRatio;
    const crop = (1 - visibleWidth) / 2;
    return [lerp(u0, u1, crop), v0, lerp(u0, u1, 1 - crop), v1];
  }

  const visibleHeight = sourceRatio / targetRatio;
  const crop = (1 - visibleHeight) / 2;
  return [u0, lerp(v0, v1, crop), u1, lerp(v0, v1, 1 - crop)];
}

function lerp(start: number, end: number, amount: number): number {
  return start + (end - start) * amount;
}

function ndcSize(layout: BoardLayout, scale: number): [number, number] {
  return [(layout.tileSize / layout.width) * scale, (layout.tileSize / layout.height) * scale];
}

function ndcRectSize(layout: BoardLayout, scaleX: number, scaleY: number): [number, number] {
  return [(layout.tileSize / layout.width) * scaleX, (layout.tileSize / layout.height) * scaleY];
}

function deviceLossMessage(info: GPUDeviceLostInfo): string {
  const detail = info.message || info.reason || "unknown reason";
  return `WebGPU device lost: ${detail}`;
}

function compactLoadError(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "unknown error";
}
