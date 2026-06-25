export type AtlasEntry = {
  key: string;
  color: [number, number, number, number];
  spriteUrl?: string;
};

export const BOARD_BACKGROUND_KEY = "board-background";

export const atlasEntries: AtlasEntry[] = [
  {
    key: BOARD_BACKGROUND_KEY,
    color: [1, 1, 1, 1],
    spriteUrl: "/assets/cogshambo/venue/gray-area-floor-plan.png",
  },
  { key: "tile", color: [0.08, 0.13, 0.14, 1] },
  { key: "tile-alt", color: [0.1, 0.16, 0.17, 1] },
  { key: "terrain-wall", color: [0.28, 0.31, 0.33, 1] },
  { key: "terrain-sand", color: [0.54, 0.46, 0.24, 1] },
  { key: "team-red", color: [0.94, 0.25, 0.28, 1] },
  { key: "team-blue", color: [0.26, 0.5, 0.96, 1] },
  {
    key: "cog-default",
    color: [0.24, 0.88, 0.68, 1],
    spriteUrl: "/assets/cogshambo/sprite-sheets/cog-default/frames/cog-default-01.png",
  },
  {
    key: "cog-ada",
    color: [0.45, 0.66, 1, 1],
    spriteUrl: "/assets/cogshambo/sprite-sheets/cog-ada/frames/cog-ada-01.png",
  },
  {
    key: "cog-babbage",
    color: [0.96, 0.74, 0.28, 1],
    spriteUrl: "/assets/cogshambo/sprite-sheets/cog-babbage/frames/cog-babbage-01.png",
  },
  {
    key: "cog-mira",
    color: [0.86, 0.47, 1, 1],
    spriteUrl: "/assets/cogshambo/sprite-sheets/cog-mira/frames/cog-mira-01.png",
  },
  { key: "debate", color: [1, 1, 1, 0.46] },
  { key: "shadow", color: [0.01, 0.015, 0.014, 0.34] },
  { key: "spawn-halo", color: [0.82, 1, 0.42, 0.5] },
  { key: "selection-halo", color: [0.82, 0.97, 0.35, 0.78] },
  { key: "selection", color: [1, 1, 1, 0.3] },
];

const fallbackColor = atlasEntries.find((entry) => entry.key === "cog-default")?.color ?? [1, 1, 1, 1];

export function colorForKey(key: string): [number, number, number, number] {
  return atlasEntries.find((entry) => entry.key === key)?.color ?? fallbackColor;
}

export function spriteEntries(): Required<Pick<AtlasEntry, "key" | "spriteUrl">>[] {
  return atlasEntries.flatMap((entry) =>
    entry.spriteUrl ? [{ key: entry.key, spriteUrl: entry.spriteUrl }] : [],
  );
}
