import type { Cog } from "../../shared/types";

type SpriteRefCog = Pick<Cog, "spriteSheetKey" | "spriteUrl">;

export type CogSpriteEntry = {
  key: string;
  spriteUrl: string;
};

export function spriteKeyForCog(cog: SpriteRefCog): string {
  return cog.spriteSheetKey;
}

export function spriteUrlForCog(cog: Pick<SpriteRefCog, "spriteUrl">): string | undefined {
  return cog.spriteUrl;
}

export function spriteEntriesForCog(cog: SpriteRefCog): CogSpriteEntry[] {
  return cog.spriteUrl ? [{ key: cog.spriteSheetKey, spriteUrl: cog.spriteUrl }] : [];
}
