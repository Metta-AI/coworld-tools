import { expect } from "vitest";

import { GridWorld } from "../../../src/server/simulation/world.js";
import { legacyHalfSecondTicksToSimulationTicks, secondsToSimulationTicks } from "../../../src/shared/timing.js";
import type {
  Cog,
  CogAction,
  DebateTactic,
  Trait,
  VenueLayout,
} from "../../../src/shared/types.js";

const FAST_DEBATE_CONFIG = {
  debatePrepTicks: 0,
  debateChoiceRevealTicks: 0,
  debateResultTicks: 0,
};

const TWO_ROOM_VENUE: VenueLayout = {
  rooms: [
    { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2", "a3", "a4"], neighborIds: ["room-b"] },
    { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2", "b3", "b4"], neighborIds: ["room-a"] },
  ],
  spots: [
    { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
    { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
    { id: "a3", roomId: "room-a", label: "A3", position: { x: 3, y: 1 } },
    { id: "a4", roomId: "room-a", label: "A4", position: { x: 4, y: 1 } },
    { id: "b1", roomId: "room-b", label: "B1", position: { x: 5, y: 1 } },
    { id: "b2", roomId: "room-b", label: "B2", position: { x: 6, y: 1 } },
    { id: "b3", roomId: "room-b", label: "B3", position: { x: 7, y: 1 } },
    { id: "b4", roomId: "room-b", label: "B4", position: { x: 8, y: 1 } },
  ],
  spotLinks: [],
  roomPaths: [{ id: "a-b", fromRoomId: "room-a", toRoomId: "room-b", points: [{ x: 4, y: 1 }] }],
};

export async function runTraitIntegration(traitId: Trait): Promise<void> {
  switch (traitId) {
    case "stubborn":
      return expectDirectLoss("stubborn", undefined, 95, { traitConfig: { stubborn: { directDoubtMultiplier: 0.5 } } });
    case "insular":
      return expectWitnessLoss({ defensiveTrait: "insular" }, 99, { traitConfig: { insular: { indirectDoubtMultiplier: 0.5 } } });
    case "iconoclast":
      return expectDominantPressureResistance();
    case "conformist":
      return expectFringePressureResistance();
    case "defector":
      return expectPassiveDefector();
    case "bandwagoner":
      return expectPassiveBandwagoner();
    case "martyr":
      return expectMartyrRecovery();
    case "doubter":
      return expectDrawDoubt();
    case "diplomat":
      return expectDiplomatWitnessDoubt();
    case "heretic":
      return expectHereticCrowdedRoomDoubt();
    case "zealot":
      return expectZealotBlocksConversion();
    case "forceful":
      return expectDirectLoss(undefined, "forceful", 80, { traitConfig: { forceful: { winDoubtMultiplier: 2 } } });
    case "charismatic":
      return expectWitnessLoss({ activeTrait: "charismatic" }, 91, { traitConfig: { charismatic: { witnessDoubt: 9 } } });
    case "contrarian":
      return expectContrarianDiscount();
    case "hippie":
      return expectHippieTacticTradeoffs();
    case "rationalist":
      return expectTacticAffinity("rationalist", "reason", "spin");
    case "spinner":
      return expectTacticAffinity("spinner", "spin", "passion");
    case "passionate":
      return expectTacticAffinity("passionate", "passion", "reason");
    case "avenger":
      return expectAvengerBoost();
    case "insurgent":
      return expectInsurgentWitnessDoubt();
    case "polarizer":
      return expectPolarizerWitnessDoubt();
    default:
      traitId satisfies never;
  }
}

async function expectDirectLoss(
  defensiveTrait: Trait | undefined,
  activeTrait: Trait | undefined,
  expectedCertainty: number,
  config = {},
): Promise<void> {
  const world = new GridWorld({ width: 6, height: 6 }, { ...FAST_DEBATE_CONFIG, debateDoubt: 10, ...config });
  const red = addGridCog(world, { name: "Red", color: "red", activeTrait: activeTrait ?? "avenger", defensiveTrait: "avenger", x: 2, y: 2 });
  const blue = addGridCog(world, {
    name: "Blue",
    color: "blue",
    activeTrait: "avenger",
    defensiveTrait: defensiveTrait ?? "avenger",
    x: 3,
    y: 2,
  });

  await world.step(new Map([[red.id, debate(blue.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [blue.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, blue.id).certainty).toBe(expectedCertainty);
}

async function expectWitnessLoss(
  trait: { defensiveTrait?: Trait; activeTrait?: Trait },
  expectedCertainty: number,
  config = {},
): Promise<void> {
  const world = new GridWorld({ width: 10, height: 4 }, { ...FAST_DEBATE_CONFIG, witnessDoubt: 2, ...config }, TWO_ROOM_VENUE);
  const red = addVenueCog(world, { name: "Red", color: "red", roomId: "room-a", spotId: "a1", activeTrait: trait.activeTrait ?? "avenger" });
  const blue = addVenueCog(world, { name: "Blue", color: "blue", roomId: "room-a", spotId: "a2" });
  const witness = addVenueCog(world, {
    name: "Witness",
    color: "blue",
    roomId: "room-a",
    spotId: "a3",
    defensiveTrait: trait.defensiveTrait,
  });

  await world.step(new Map([[red.id, debate(blue.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [blue.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, witness.id).certainty).toBe(expectedCertainty);
}

async function expectDominantPressureResistance(): Promise<void> {
  const world = new GridWorld({ width: 8, height: 8 }, FAST_DEBATE_CONFIG);
  const red = addGridCog(world, { name: "Red", color: "red", activeTrait: "avenger", defensiveTrait: "avenger", x: 2, y: 2 });
  world.addCog({ name: "Red Ally", color: "red", position: { x: 1, y: 5 }, activeTrait: "avenger", defensiveTrait: "avenger" });
  const blue = addGridCog(world, { name: "Blue", color: "blue", activeTrait: "avenger", defensiveTrait: "iconoclast", x: 3, y: 2 });

  await world.step(new Map([[red.id, debate(blue.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [blue.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, blue.id).certainty).toBe(92.5);
}

async function expectFringePressureResistance(): Promise<void> {
  const world = new GridWorld({ width: 8, height: 8 }, FAST_DEBATE_CONFIG);
  const red = addGridCog(world, { name: "Red", color: "red", activeTrait: "avenger", defensiveTrait: "avenger", x: 2, y: 2 });
  world.addCog({ name: "Blue Ally", color: "blue", position: { x: 1, y: 5 }, activeTrait: "avenger", defensiveTrait: "avenger" });
  const blue = addGridCog(world, { name: "Blue", color: "blue", activeTrait: "avenger", defensiveTrait: "conformist", x: 3, y: 2 });

  await world.step(new Map([[red.id, debate(blue.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [blue.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, blue.id).certainty).toBe(92.5);
}

async function expectPassiveDefector(): Promise<void> {
  const world = new GridWorld(
    { width: 10, height: 4 },
    { traitConfig: { defector: { majorityThreshold: 0.6, majorityDoubt: 10 } } },
    TWO_ROOM_VENUE,
  );
  const target = addVenueCog(world, { name: "Defector", color: "red", defensiveTrait: "defector", roomId: "room-a", spotId: "a1" });
  addVenueCog(world, { name: "Red Ally", color: "red", roomId: "room-a", spotId: "a2" });
  addVenueCog(world, { name: "Blue", color: "blue", roomId: "room-b", spotId: "b1" });

  const snapshot = await stepTicks(world, secondsToSimulationTicks(60));

  expect(cog(snapshot.cogs, target.id).certainty).toBeCloseTo(90);
}

async function expectPassiveBandwagoner(): Promise<void> {
  let world = new GridWorld(
    { width: 10, height: 4 },
    { traitConfig: { bandwagoner: { majorityThreshold: 0.6, majorityRecovery: 10 } } },
    TWO_ROOM_VENUE,
  );
  const target = addVenueCog(world, { name: "Bandwagoner", color: "red", defensiveTrait: "bandwagoner", roomId: "room-a", spotId: "a1" });
  addVenueCog(world, { name: "Red Ally", color: "red", roomId: "room-a", spotId: "a2" });
  addVenueCog(world, { name: "Blue", color: "blue", roomId: "room-b", spotId: "b1" });
  world = setCertainty(world, target.id, 80);

  const snapshot = await stepTicks(world, secondsToSimulationTicks(60));

  expect(cog(snapshot.cogs, target.id).certainty).toBeCloseTo(90);
}

async function expectMartyrRecovery(): Promise<void> {
  let world = new GridWorld(
    { width: 10, height: 4 },
    { ...FAST_DEBATE_CONFIG, debateDoubt: 10, traitConfig: { martyr: { teammateRecovery: 12 } } },
    TWO_ROOM_VENUE,
  );
  const red = addVenueCog(world, { name: "Red", color: "red", activeTrait: "avenger", defensiveTrait: "avenger", roomId: "room-a", spotId: "a1" });
  const martyr = addVenueCog(world, { name: "Martyr", color: "blue", defensiveTrait: "martyr", roomId: "room-a", spotId: "a2" });
  const witness = addVenueCog(world, { name: "Blue Witness", color: "blue", roomId: "room-a", spotId: "a3" });
  world = setCertainty(setCertainty(world, martyr.id, 5), witness.id, 80);

  await world.step(new Map([[red.id, debate(martyr.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [martyr.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, martyr.id).color).toBe("red");
  expect(cog(snapshot.cogs, witness.id).certainty).toBe(92);
}

async function expectDrawDoubt(): Promise<void> {
  const world = new GridWorld({ width: 6, height: 6 }, { ...FAST_DEBATE_CONFIG, traitConfig: { doubter: { drawDoubt: 6 } } });
  const red = addGridCog(world, { name: "Red", color: "red", defensiveTrait: "doubter", activeTrait: "avenger", x: 2, y: 2 });
  const blue = addGridCog(world, { name: "Blue", color: "blue", defensiveTrait: "doubter", activeTrait: "avenger", x: 3, y: 2 });

  await world.step(new Map([[red.id, debate(blue.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [blue.id, chooseTactic("reason")],
  ]));

  expect(cog(snapshot.cogs, red.id).certainty).toBe(94);
  expect(cog(snapshot.cogs, blue.id).certainty).toBe(94);
}

async function expectDiplomatWitnessDoubt(): Promise<void> {
  let world = new GridWorld(
    { width: 10, height: 4 },
    { ...FAST_DEBATE_CONFIG, traitConfig: { diplomat: { majorityWinDoubt: 6 } } },
    TWO_ROOM_VENUE,
  );
  const red = addVenueCog(world, { name: "Red", color: "red", roomId: "room-a", spotId: "a1" });
  const blue = addVenueCog(world, { name: "Blue", color: "blue", roomId: "room-a", spotId: "a2" });
  const diplomat = addVenueCog(world, { name: "Diplomat", color: "red", defensiveTrait: "diplomat", roomId: "room-a", spotId: "a3" });
  addVenueCog(world, { name: "Red Majority", color: "red", roomId: "room-b", spotId: "b1" });
  world = setCertainty(world, diplomat.id, 80);

  await world.step(new Map([[red.id, debate(blue.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [blue.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, diplomat.id).certainty).toBe(74);
}

async function expectRoomEntryDoubt(
  defensiveTrait: Trait | undefined,
  activeTrait: Trait | undefined,
  expectedCertainty: number,
  config = {},
): Promise<void> {
  const world = new GridWorld({ width: 10, height: 4 }, { roomMoveCooldownTicks: 0, ...config }, TWO_ROOM_VENUE);
  const target = addVenueCog(world, {
    name: "Walker",
    color: "red",
    defensiveTrait: defensiveTrait ?? "stubborn",
    activeTrait: activeTrait ?? "avenger",
    roomId: "room-a",
    spotId: "a1",
  });
  addVenueCog(world, { name: "Red Ally", color: "red", roomId: "room-b", spotId: "b1" });
  addVenueCog(world, { name: "Blue Bystander", color: "blue", roomId: "room-a", spotId: "a2" });

  await world.step(new Map([[target.id, { type: "move", roomId: "room-b" }]]));
  const snapshot = await stepUntilNotMoving(world, target.id);

  expect(cog(snapshot.cogs, target.id).certainty).toBe(expectedCertainty);
}

async function expectHereticCrowdedRoomDoubt(): Promise<void> {
  const world = new GridWorld(
    { width: 10, height: 4 },
    { roomMoveCooldownTicks: 0, traitConfig: { heretic: { crowdedRoomThreshold: 3, crowdedRoomDoubt: 8 } } },
    TWO_ROOM_VENUE,
  );
  const target = addVenueCog(world, {
    name: "Heretic",
    color: "red",
    defensiveTrait: "heretic",
    roomId: "room-a",
    spotId: "a1",
  });
  addVenueCog(world, { name: "Red Roommate", color: "red", roomId: "room-b", spotId: "b1" });
  addVenueCog(world, { name: "Blue Roommate 1", color: "blue", roomId: "room-b", spotId: "b2" });
  addVenueCog(world, { name: "Blue Roommate 2", color: "blue", roomId: "room-b", spotId: "b3" });

  await world.step(new Map([[target.id, { type: "move", roomId: "room-b" }]]));
  const snapshot = await stepUntilNotMoving(world, target.id);

  expect(cog(snapshot.cogs, target.id).certainty).toBe(92);
}

async function expectZealotBlocksConversion(): Promise<void> {
  let world = new GridWorld({ width: 6, height: 6 }, { ...FAST_DEBATE_CONFIG, debateDoubt: 200, conversionThreshold: 100 });
  const red = addGridCog(world, { name: "Red", color: "red", activeTrait: "avenger", defensiveTrait: "avenger", x: 2, y: 2 });
  const zealot = addGridCog(world, { name: "Zealot", color: "blue", activeTrait: "avenger", defensiveTrait: "zealot", x: 3, y: 2 });
  world = setCertainty(world, zealot.id, 5);

  await world.step(new Map([[red.id, debate(zealot.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [zealot.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, zealot.id).color).toBe("blue");
  expect(cog(snapshot.cogs, zealot.id).certainty).toBe(1);
}

async function expectContrarianDiscount(): Promise<void> {
  await expectContrarianMajorityFlip();

  const world = new GridWorld(
    { width: 10, height: 10 },
    {
      ...FAST_DEBATE_CONFIG,
      debateDoubt: 10,
      maxDebateRounds: 1,
      debateCooldownTicks: 20,
      traitConfig: { contrarian: { debateCooldownMultiplier: 0, majorityPressureDiscount: 0.5, unanimousRoomDoubt: 7 } },
    },
  );
  const red = addGridCog(world, { name: "Red", color: "red", activeTrait: "contrarian", defensiveTrait: "insular", x: 2, y: 2 });
  const blue = addGridCog(world, { name: "Blue", color: "blue", activeTrait: "contrarian", defensiveTrait: "insular", x: 3, y: 2 });
  world.addCog({ name: "Other Red 1", color: "red", position: { x: 1, y: 5 } });
  world.addCog({ name: "Other Red 2", color: "red", position: { x: 1, y: 6 } });

  await world.step(new Map([[red.id, debate(blue.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [blue.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, blue.id).certainty).toBe(92.5);
  expect(world.canStartDebate(red.id, blue.id)).toBe(true);

  await expectRoomEntryDoubt(undefined, "contrarian", 93, {
    traitConfig: { contrarian: { debateCooldownMultiplier: 0.5, majorityPressureDiscount: 0.5, unanimousRoomDoubt: 7 } },
  });
}

async function expectContrarianMajorityFlip(): Promise<void> {
  const flipWorld = new GridWorld(
    { width: 12, height: 2 },
    { traitConfig: { contrarian: { overwhelmingTeamThreshold: 0.9 } } },
  );
  const target = addGridCog(flipWorld, { name: "Contrarian", color: "red", activeTrait: "contrarian", x: 0, y: 0 });
  for (let index = 1; index < 10; index += 1) {
    addGridCog(flipWorld, { name: `Red ${index}`, color: "red", x: index, y: 0 });
  }
  addGridCog(flipWorld, { name: "Blue", color: "blue", x: 10, y: 0 });

  let snapshot = await flipWorld.step(new Map());

  expect(cog(snapshot.cogs, target.id).color).toBe("blue");
  expect(cog(snapshot.cogs, target.id).stats.teamFlips).toBe(1);

  const stableWorld = new GridWorld(
    { width: 12, height: 2 },
    { traitConfig: { contrarian: { overwhelmingTeamThreshold: 0.9 } } },
  );
  const stableTarget = addGridCog(stableWorld, { name: "Stable Contrarian", color: "red", activeTrait: "contrarian", x: 0, y: 0 });
  for (let index = 1; index < 9; index += 1) {
    addGridCog(stableWorld, { name: `Stable Red ${index}`, color: "red", x: index, y: 0 });
  }
  addGridCog(stableWorld, { name: "Stable Blue", color: "blue", x: 9, y: 0 });

  snapshot = await stableWorld.step(new Map());

  expect(cog(snapshot.cogs, stableTarget.id).color).toBe("red");
  expect(cog(snapshot.cogs, stableTarget.id).stats.teamFlips).toBe(0);
}

async function expectTacticAffinity(activeTrait: Trait, winningTactic: DebateTactic, losingTactic: DebateTactic): Promise<void> {
  const world = new GridWorld(
    { width: 6, height: 6 },
    { ...FAST_DEBATE_CONFIG, debateDoubt: 10, traitConfig: { [activeTrait]: { winDoubtMultiplier: 2 } } },
  );
  const red = addGridCog(world, { name: "Red", color: "red", activeTrait, defensiveTrait: "avenger", x: 2, y: 2 });
  const blue = addGridCog(world, { name: "Blue", color: "blue", activeTrait: "avenger", defensiveTrait: "avenger", x: 3, y: 2 });

  await world.step(new Map([[red.id, debate(blue.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic(winningTactic)],
    [blue.id, chooseTactic(losingTactic)],
  ]));

  expect(cog(snapshot.cogs, blue.id).certainty).toBe(80);
}

async function expectHippieTacticTradeoffs(): Promise<void> {
  await expectHippieRound({
    hippieTraitSlot: "source",
    winningTactic: "reason",
    losingTactic: "spin",
    expectedHippieCertainty: 100,
    expectedOpponentCertainty: 92.5,
  });
  await expectHippieRound({
    hippieTraitSlot: "source",
    winningTactic: "passion",
    losingTactic: "reason",
    expectedHippieCertainty: 100,
    expectedOpponentCertainty: 87.5,
  });
  await expectHippieRound({
    hippieTraitSlot: "target",
    winningTactic: "reason",
    losingTactic: "spin",
    expectedHippieCertainty: 87.5,
    expectedOpponentCertainty: 100,
  });
  await expectHippieRound({
    hippieTraitSlot: "target",
    winningTactic: "passion",
    losingTactic: "reason",
    expectedHippieCertainty: 92.5,
    expectedOpponentCertainty: 100,
  });
}

async function expectHippieRound(input: {
  hippieTraitSlot: "source" | "target";
  winningTactic: DebateTactic;
  losingTactic: DebateTactic;
  expectedHippieCertainty: number;
  expectedOpponentCertainty: number;
}): Promise<void> {
  const world = new GridWorld({ width: 6, height: 6 }, { ...FAST_DEBATE_CONFIG, debateDoubt: 10 });
  const hippieIsWinner = input.hippieTraitSlot === "source";
  const hippie = addGridCog(world, {
    name: "Hippie",
    color: hippieIsWinner ? "red" : "blue",
    activeTrait: "hippie",
    defensiveTrait: "avenger",
    x: hippieIsWinner ? 2 : 3,
    y: 2,
  });
  const opponent = addGridCog(world, {
    name: "Opponent",
    color: hippieIsWinner ? "blue" : "red",
    activeTrait: "avenger",
    defensiveTrait: "avenger",
    x: hippieIsWinner ? 3 : 2,
    y: 2,
  });
  const winner = hippieIsWinner ? hippie : opponent;
  const loser = hippieIsWinner ? opponent : hippie;

  await world.step(new Map([[winner.id, debate(loser.id)]]));
  const snapshot = await world.step(new Map([
    [winner.id, chooseTactic(input.winningTactic)],
    [loser.id, chooseTactic(input.losingTactic)],
  ]));

  expect(cog(snapshot.cogs, hippie.id).certainty).toBe(input.expectedHippieCertainty);
  expect(cog(snapshot.cogs, opponent.id).certainty).toBe(input.expectedOpponentCertainty);
}

async function expectAvengerBoost(): Promise<void> {
  let world = new GridWorld(
    { width: 10, height: 4 },
    { ...FAST_DEBATE_CONFIG, debateDoubt: 10, traitConfig: { avenger: { nextWinDoubtMultiplier: 1.5 } } },
    TWO_ROOM_VENUE,
  );
  const red = addVenueCog(world, { name: "Red", color: "red", activeTrait: "avenger", defensiveTrait: "avenger", roomId: "room-a", spotId: "a1" });
  const victim = addVenueCog(world, { name: "Victim", color: "blue", roomId: "room-a", spotId: "a2" });
  const avenger = addVenueCog(world, { name: "Avenger", color: "blue", activeTrait: "avenger", roomId: "room-a", spotId: "a3" });
  world = setCertainty(world, victim.id, 5);

  await world.step(new Map([[red.id, debate(victim.id)]]));
  await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [victim.id, chooseTactic("spin")],
  ]));
  await world.step(new Map([[avenger.id, debate(red.id)]]));
  const snapshot = await world.step(new Map([
    [avenger.id, chooseTactic("reason")],
    [red.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, red.id).certainty).toBe(85);
}

async function expectInsurgentWitnessDoubt(): Promise<void> {
  const world = new GridWorld(
    { width: 10, height: 4 },
    { ...FAST_DEBATE_CONFIG, witnessDoubt: 2, traitConfig: { insurgent: { minorityWitnessMultiplier: 2 } } },
    TWO_ROOM_VENUE,
  );
  const insurgent = addVenueCog(world, { name: "Insurgent", color: "red", activeTrait: "insurgent", roomId: "room-a", spotId: "a1" });
  const target = addVenueCog(world, { name: "Target", color: "blue", roomId: "room-a", spotId: "a2" });
  const witness = addVenueCog(world, { name: "Witness", color: "blue", roomId: "room-a", spotId: "a3" });
  addVenueCog(world, { name: "Blue Majority", color: "blue", roomId: "room-b", spotId: "b1" });

  await world.step(new Map([[insurgent.id, debate(target.id)]]));
  const snapshot = await world.step(new Map([
    [insurgent.id, chooseTactic("reason")],
    [target.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, witness.id).certainty).toBe(96);
}

async function expectPolarizerWitnessDoubt(): Promise<void> {
  let world = new GridWorld(
    { width: 10, height: 4 },
    { ...FAST_DEBATE_CONFIG, traitConfig: { polarizer: { lowCertaintyThreshold: 50, sameTeamDoubt: 5 } } },
    TWO_ROOM_VENUE,
  );
  const red = addVenueCog(world, { name: "Red", color: "red", activeTrait: "polarizer", roomId: "room-a", spotId: "a1" });
  const blue = addVenueCog(world, { name: "Blue", color: "blue", roomId: "room-a", spotId: "a2" });
  const witness = addVenueCog(world, { name: "Low Red", color: "red", roomId: "room-a", spotId: "a3" });
  world = setCertainty(world, witness.id, 40);

  await world.step(new Map([[red.id, debate(blue.id)]]));
  const snapshot = await world.step(new Map([
    [red.id, chooseTactic("reason")],
    [blue.id, chooseTactic("spin")],
  ]));

  expect(cog(snapshot.cogs, witness.id).certainty).toBe(35);
}

function addGridCog(
  world: GridWorld,
  input: {
    name: string;
    color: "red" | "blue";
    x: number;
    y: number;
    defensiveTrait?: Trait;
    activeTrait?: Trait;
  },
): Cog {
  return world.addCog({
    name: input.name,
    color: input.color,
    defensiveTrait: input.defensiveTrait ?? "avenger",
    activeTrait: input.activeTrait ?? "avenger",
    position: { x: input.x, y: input.y },
    controllerId: "stub",
  });
}

function addVenueCog(
  world: GridWorld,
  input: {
    name: string;
    color: "red" | "blue";
    roomId: string;
    spotId: string;
    defensiveTrait?: Trait;
    activeTrait?: Trait;
  },
): Cog {
  return world.addCog({
    name: input.name,
    color: input.color,
    defensiveTrait: input.defensiveTrait ?? "avenger",
    activeTrait: input.activeTrait ?? "avenger",
    location: { roomId: input.roomId, spotId: input.spotId },
    controllerId: "stub",
  });
}

function debate(targetId: string): CogAction {
  return { type: "debate", targetId };
}

function chooseTactic(tactic: DebateTactic): CogAction {
  return { type: "chooseTactic", tactic };
}

function setCertainty(world: GridWorld, cogId: string, certainty: number): GridWorld {
  const state = world.exportState();
  cog(state.cogs, cogId).certainty = certainty;
  return GridWorld.fromState(state);
}

async function stepUntilNotMoving(world: GridWorld, cogId: string) {
  let snapshot = world.snapshot();
  for (let index = 0; index < legacyHalfSecondTicksToSimulationTicks(80) && cog(snapshot.cogs, cogId).moving; index += 1) {
    snapshot = await world.step(new Map());
  }
  return snapshot;
}

async function stepTicks(world: GridWorld, ticks: number) {
  let snapshot = world.snapshot();
  for (let index = 0; index < ticks; index += 1) {
    snapshot = await world.step(new Map());
  }
  return snapshot;
}

function cog(cogs: Cog[], cogId: string): Cog {
  const found = cogs.find((candidate) => candidate.id === cogId);
  if (!found) {
    throw new Error(`Missing cog ${cogId}`);
  }
  return found;
}
