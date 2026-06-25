import { SELECTABLE_TRAITS } from "../../shared/types.js";
import type { ControllerId, Trait, VenueLocation, WorldObject } from "../../shared/types.js";
import type { GameConfigInput } from "../../shared/rules.js";
import { readDefaultVenueGraphFile, venueLayoutFromEditorState } from "../venue-graph.js";
import { GridWorld } from "./world.js";

export type SeedWorldOptions = {
  cogCount?: number;
  controllerId?: ControllerId;
};

export function createSeedWorld(config: GameConfigInput = {}, options: SeedWorldOptions = {}): GridWorld {
  const venueGraph = readDefaultVenueGraphFile({
    assignSpotsToNearestRooms: false,
    deriveRoomRects: false,
  });
  const world = new GridWorld(venueGraph.dimensions, config, venueLayoutFromEditorState(venueGraph));
  const targetCogCount = normalizedCogCount(options.cogCount, seedCogs().length);
  const controllerId = options.controllerId ?? "llm";

  seedCogs().slice(0, targetCogCount).forEach((cog) => {
    world.addCog({
      ...cog,
      spriteUrl: `/assets/cogshambo/sprite-sheets/${cog.spriteSheetKey}/frames/${cog.spriteSheetKey}-01.png`,
      controllerId,
    });
  });

  seedMapObjects().forEach((object) => world.addObject(object));
  for (let index = seedCogs().length; index < targetCogCount; index += 1) {
    world.addCog({ ...generatedSeedCog(index), controllerId });
  }
  return world;
}

function normalizedCogCount(value: number | undefined, fallback: number): number {
  if (value === undefined) {
    return fallback;
  }

  return Math.max(0, Math.floor(value));
}

function generatedSeedCog(index: number): {
  name: string;
  behaviorPrompt: string;
  spriteSheetKey: string;
  attributes: Record<string, number>;
  color: "red" | "blue";
  defensiveTrait: Trait;
  activeTrait: Trait;
} {
  return {
    name: `Cog ${index + 1}`,
    behaviorPrompt: "Seek useful same-room debates, choose a matching tactic, and move when the room goes quiet.",
    spriteSheetKey: "cog-default",
    attributes: {
      energy: 5 + (index % 5),
      focus: 5 + ((index * 2) % 5),
    },
    color: index % 2 === 0 ? "red" : "blue",
    defensiveTrait: SELECTABLE_TRAITS[index % SELECTABLE_TRAITS.length] ?? "stubborn",
    activeTrait: SELECTABLE_TRAITS[(index + 1) % SELECTABLE_TRAITS.length] ?? "forceful",
  };
}

function seedCogs(): Array<{
  name: string;
  behaviorPrompt: string;
  spriteSheetKey: string;
  attributes: Record<string, number>;
  color: "red" | "blue";
    defensiveTrait: Trait;
    activeTrait: Trait;
  location: VenueLocation;
}> {
  return [
    {
      name: "Ada",
      behaviorPrompt: "Seek debates, prefer passion when certainty drops, and track same-room momentum.",
      spriteSheetKey: "cog-ada",
      attributes: { energy: 7, focus: 8 },
      color: "red",
      defensiveTrait: "zealot",
      activeTrait: "passionate",
      location: { roomId: "stage", spotId: "stage_host" },
    },
    {
      name: "Babbage",
      behaviorPrompt: "Contest same-room cogs, prefer reason, and pursue conversions.",
      spriteSheetKey: "cog-babbage",
      attributes: { energy: 8, focus: 5 },
      color: "blue",
      defensiveTrait: "zealot",
      activeTrait: "rationalist",
      location: { roomId: "stage", spotId: "stage_guest" },
    },
    {
      name: "Mira",
      behaviorPrompt: "Build local momentum, read local signals, and stay committed during debates.",
      spriteSheetKey: "cog-mira",
      attributes: { energy: 6, focus: 9 },
      color: "red",
      defensiveTrait: "insular",
      activeTrait: "charismatic",
      location: { roomId: "lounge_sofas", spotId: "sofa_left" },
    },
    {
      name: "Turing",
      behaviorPrompt: "Challenge confident opponents, prefer spin, and keep pressure on red cogs.",
      spriteSheetKey: "cog-default",
      attributes: { energy: 7, focus: 7 },
      color: "blue",
      defensiveTrait: "iconoclast",
      activeTrait: "spinner",
      location: { roomId: "lounge_sofas", spotId: "sofa_right" },
    },
    {
      name: "Noor",
      behaviorPrompt: "Work the bar crowd, ask direct questions, and convert undecided listeners.",
      spriteSheetKey: "cog-default",
      attributes: { energy: 8, focus: 6 },
      color: "red",
      defensiveTrait: "conformist",
      activeTrait: "forceful",
      location: { roomId: "concessions_left", spotId: "bar_left_a" },
    },
    {
      name: "Lin",
      behaviorPrompt: "Hold the bar line, use calm reason, and resist fast consensus.",
      spriteSheetKey: "cog-default",
      attributes: { energy: 6, focus: 8 },
      color: "blue",
      defensiveTrait: "stubborn",
      activeTrait: "rationalist",
      location: { roomId: "concessions_left", spotId: "bar_left_b" },
    },
    {
      name: "Sol",
      behaviorPrompt: "Make theatrical claims from the front row and pull neighbors into debate.",
      spriteSheetKey: "cog-default",
      attributes: { energy: 9, focus: 5 },
      color: "red",
      defensiveTrait: "stubborn",
      activeTrait: "charismatic",
      location: { roomId: "seat_front", spotId: "seat_front_left" },
    },
    {
      name: "Quinn",
      behaviorPrompt: "Counter stage energy from the front row with concise blue arguments.",
      spriteSheetKey: "cog-default",
      attributes: { energy: 7, focus: 7 },
      color: "blue",
      defensiveTrait: "insular",
      activeTrait: "contrarian",
      location: { roomId: "seat_front", spotId: "seat_front_right" },
    },
    {
      name: "Rhea",
      behaviorPrompt: "Build red momentum around the conference table through direct debate.",
      spriteSheetKey: "cog-default",
      attributes: { energy: 6, focus: 8 },
      color: "red",
      defensiveTrait: "iconoclast",
      activeTrait: "passionate",
      location: { roomId: "conference_corner", spotId: "conference_left" },
    },
    {
      name: "Voss",
      behaviorPrompt: "Defend blue positions around the conference table and seek conversions.",
      spriteSheetKey: "cog-default",
      attributes: { energy: 8, focus: 6 },
      color: "blue",
      defensiveTrait: "conformist",
      activeTrait: "spinner",
      location: { roomId: "conference_corner", spotId: "conference_right" },
    },
  ];
}

function seedMapObjects(): WorldObject[] {
  return [
    { id: "lobby_arch", type: "stairs", position: { x: 7, y: 12 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "concessions_counter", type: "block", position: { x: 15, y: 20 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "conference_table", type: "picknick", position: { x: 13, y: 8 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "lounge_sofa", type: "bench", position: { x: 23, y: 18 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "lounge_low_table", type: "picknick", position: { x: 24, y: 15 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "workshop_table", type: "picknick", position: { x: 35, y: 21 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "projection_wall", type: "block", position: { x: 32, y: 7 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "stage_screen", type: "block", position: { x: 48, y: 12 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "stage_step_left", type: "stairs", position: { x: 44, y: 9 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "stage_step_right", type: "stairs", position: { x: 44, y: 19 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "green_room_couch", type: "bench", position: { x: 47, y: 4 }, spriteKey: "map-object-marker", attributes: {} },
    { id: "foh_booth", type: "block", position: { x: 34, y: 24 }, spriteKey: "map-object-marker", attributes: {} },
  ];
}
