import type { Position, WorldDimensions } from "../../shared/types";

export type BoardCamera = {
  zoom: number;
  offsetX: number;
  offsetY: number;
};

export function createBoardCamera(): BoardCamera {
  return {
    zoom: 28,
    offsetX: 0,
    offsetY: 0,
  };
}

export function centerCameraOnBoard(
  camera: BoardCamera,
  dimensions: WorldDimensions,
  canvas: HTMLCanvasElement,
): void {
  camera.offsetX = canvas.width / 2 - (dimensions.width * camera.zoom) / 2;
  camera.offsetY = canvas.height / 2 - (dimensions.height * camera.zoom) / 2;
}

export function boardToClip(
  position: Position,
  camera: BoardCamera,
  canvas: HTMLCanvasElement,
): [number, number] {
  const pixelX = camera.offsetX + position.x * camera.zoom;
  const pixelY = camera.offsetY + position.y * camera.zoom;
  return [(pixelX / canvas.width) * 2 - 1, 1 - (pixelY / canvas.height) * 2];
}
