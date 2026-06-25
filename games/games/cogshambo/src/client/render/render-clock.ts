import type { ServerStatus } from "../../shared/types";
import type { RenderOptions } from "./webgpu-board-renderer";

export function renderOptionsForFrame({
  frameTimeMs,
  selectedCogId,
  serverStatus,
}: {
  frameTimeMs: number;
  selectedCogId: string | undefined;
  serverStatus: Pick<ServerStatus, "discoMode"> | undefined;
}): RenderOptions {
  return {
    discoLightTimeMs: frameTimeMs,
    discoMode: serverStatus?.discoMode ?? false,
    selectedCogId,
  };
}
