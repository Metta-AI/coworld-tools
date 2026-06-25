export type DiscoLightSpot = {
  x: number;
  y: number;
  radiusX: number;
  radiusY: number;
  color: [number, number, number, number];
};

export const DISCO_LIGHT_SPOT_COUNT = 28;

const DISCO_LIGHT_COLORS: Array<[number, number, number]> = [
  [1, 0.3, 0.34],
  [1, 0.86, 0.32],
  [0.38, 0.9, 0.48],
  [0.26, 0.84, 1],
  [0.3, 0.56, 1],
  [0.74, 0.4, 1],
];

const TAU = Math.PI * 2;

export function discoLightSpots(timeMs: number, count = DISCO_LIGHT_SPOT_COUNT): DiscoLightSpot[] {
  const seconds = timeMs / 1000;
  return Array.from({ length: count }, (_, index) => {
    const color = DISCO_LIGHT_COLORS[index % DISCO_LIGHT_COLORS.length] ?? DISCO_LIGHT_COLORS[0];
    const angle = seconds * (0.42 + (index % 7) * 0.045) * TAU + index * 2.399963;
    const wobble = seconds * (0.68 + (index % 5) * 0.057) + index * 0.71;
    const orbitX = 0.12 + ((index * 37) % 15) / 100;
    const orbitY = 0.1 + ((index * 29) % 13) / 100;
    const radius = 0.034 + (index % 5) * 0.008;

    return {
      x: 0.5 + Math.cos(angle) * orbitX + Math.sin(wobble) * 0.1,
      y: 0.5 + Math.sin(angle * 0.91) * orbitY + Math.cos(wobble * 1.17) * 0.09,
      radiusX: radius * (1.4 + (index % 3) * 0.22),
      radiusY: radius * (0.72 + (index % 4) * 0.1),
      color: [color[0], color[1], color[2], 0.34],
    };
  });
}
