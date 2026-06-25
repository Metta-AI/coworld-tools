import { describe, expect, it } from "vitest";

import { legacyHalfSecondTicksToSimulationTicks } from "../../src/shared/timing";
import type { WorldEvent, WorldSnapshot } from "../../src/shared/types";
import type { DiaryRoomEntry } from "../../src/client/ui/hud";
import {
  buildDiaryRoomEntries,
  DIARY_INITIAL_ROOM_LIMIT,
  renderDebateTacticLegend,
  renderDiaryRoomFeed,
  renderGameFlowPanel,
  renderGameTicker,
  renderTeamsGauge,
} from "../../src/client/ui/hud";

describe("profile diary event rendering", () => {
  it("groups diary activity into room stays and starts a new entry after changing rooms", () => {
    const entries = buildDiaryRoomEntries(cog("ada", "Ada", "stage"), snapshotWithDiaryEvents());

    expect(entries).toHaveLength(2);
    expect(entries[0]).toMatchObject({
      roomLabel: "Stage",
      enterTick: 8,
      leaveTick: undefined,
      flips: [expect.objectContaining({ message: "Ada converted from blue to red" })],
      debateResults: [],
      witnessedDebates: [],
    });
    expect(entries[1]).toMatchObject({
      roomLabel: "Bar",
      enterTick: 1,
      leaveTick: 7,
      flips: [expect.objectContaining({ message: "Babbage converted from blue to red" })],
      debateResults: [expect.objectContaining({ message: "Ada's reason shook Babbage's certainty" })],
      witnessedDebates: [expect.objectContaining({ message: "Mira's spin shook Turing's certainty" })],
      people: [
        expect.objectContaining({ message: "Ada arrived at Bar - stool" }),
        expect.objectContaining({ message: "Babbage arrived at Bar - booth" }),
        expect.objectContaining({ message: "Babbage started moving to Stage - right" }),
        expect.objectContaining({ message: "Ada started moving to Stage - left" }),
      ],
    });
    expect(entries[1]?.events.map((item) => item.event.message)).toEqual([
      "Ada arrived at Bar - stool",
      "Babbage arrived at Bar - booth",
      "Ada's reason shook Babbage's certainty",
      "Mira's spin shook Turing's certainty",
      "Babbage converted from blue to red",
      "Babbage started moving to Stage - right",
      "Ada started moving to Stage - left",
    ]);
    expect(entries[1]?.events.map((item) => item.kind)).toEqual([
      "person",
      "person",
      "debate",
      "witness",
      "flip",
      "person",
      "person",
    ]);
  });

  it("keeps same-room spot changes inside the current room entry", () => {
    const entries = buildDiaryRoomEntries(cog("ada", "Ada", "stage"), snapshotWithSameRoomMove());

    expect(entries).toHaveLength(2);
    expect(entries[0]).toMatchObject({ roomLabel: "Stage", enterTick: 5, leaveTick: undefined });
    expect(entries[1]).toMatchObject({
      roomLabel: "Bar",
      enterTick: 1,
      leaveTick: 4,
      people: [
        expect.objectContaining({ message: "Ada arrived at Bar - stool" }),
        expect.objectContaining({ message: "Ada started moving to Bar - booth" }),
        expect.objectContaining({ message: "Ada arrived at Bar - booth" }),
        expect.objectContaining({ message: "Ada started moving to Stage - left" }),
      ],
    });
  });

  it("keeps debate results from the persistent debate log after exchange events age out", () => {
    const snapshot = snapshotWithDiaryEvents();
    snapshot.recentEvents = snapshot.recentEvents.filter((event) => event.type !== "debateExchange");
    snapshot.debateLog = [
      debateLogEntry("ada-log", 3, "ada", "Ada", "babbage", "Babbage", "ada", "reason", "spin"),
      debateLogEntry("witness-log", 4, "mira", "Mira", "turing", "Turing", "mira", "spin", "passion", ["ada"]),
    ];

    const entries = buildDiaryRoomEntries(cog("ada", "Ada", "stage"), snapshot);

    const bar = entries.find((entry) => entry.roomLabel === "Bar");
    expect(bar?.debateResults).toEqual([
      expect.objectContaining({
        id: "diary-debate-ada-log",
        message: "Ada's Reason beat Babbage's Spin.",
      }),
    ]);
    expect(bar?.witnessedDebates).toEqual([
      expect.objectContaining({
        id: "diary-debate-witness-log",
        message: "Mira's Spin beat Turing's Passion.",
      }),
    ]);
    expect(bar?.events.map((item) => item.kind)).toContain("debate");
    expect(bar?.events.map((item) => item.kind)).toContain("witness");
  });

  it("does not render a synthetic debates room for unmapped debate log entries", () => {
    const snapshot = snapshotWithDiaryEvents();
    snapshot.recentEvents = [move("ada-enter-stage", 8, "ada", "Ada arrived at Stage - left", { x: 8, y: 1 })];
    snapshot.debateLog = [
      debateLogEntry("old-debate", 3, "ada", "Ada", "babbage", "Babbage", "ada", "reason", "spin"),
    ];

    const entries = buildDiaryRoomEntries(cog("ada", "Ada", "stage"), snapshot);
    const html = renderDiaryRoomFeed(entries, { cogId: "ada", currentRoomId: "stage", visibleRoomCount: 4 });

    expect(entries.map((entry) => entry.roomLabel)).toEqual(["Stage"]);
    expect(html).not.toContain('data-room-id="debates"');
    expect(html).not.toContain("<strong>Debates</strong>");
    expect(html).not.toContain("old-debate");
  });

  it("keeps the current room plus five previous rooms from persistent room history", () => {
    const selectedCog = cog("ada", "Ada", "room-0") as ReturnType<typeof cog> & {
      roomHistory: Array<{ roomId: string; spotId: string; enteredTick: number; leftTick?: number }>;
    };
    selectedCog.roomHistory = Array.from({ length: 6 }, (_, index) => ({
      roomId: `room-${index}`,
      spotId: `spot-${index}`,
      enteredTick: 100 - index * 10,
      leftTick: index === 0 ? undefined : 105 - index * 10,
    }));
    const snapshot = snapshotWithDiaryEvents();
    snapshot.cogs = [selectedCog];
    snapshot.recentEvents = [];
    snapshot.venue = {
      rooms: selectedCog.roomHistory.map((entry, index) => ({
        id: entry.roomId,
        label: index === 0 ? "Current Room" : `Past Room ${index}`,
        kind: "lounge",
        spotIds: [entry.spotId],
        neighborIds: [],
      })),
      spots: selectedCog.roomHistory.map((entry) => ({
        id: entry.spotId,
        roomId: entry.roomId,
        label: entry.spotId,
        position: { x: 1, y: 1 },
      })),
      spotLinks: [],
      roomPaths: [],
    };

    const entries = buildDiaryRoomEntries(selectedCog, snapshot);

    expect(entries.map((entry) => entry.roomLabel)).toEqual([
      "Current Room",
      "Past Room 1",
      "Past Room 2",
      "Past Room 3",
      "Past Room 4",
      "Past Room 5",
    ]);
    expect(entries[0]).toMatchObject({ roomId: "room-0", leaveTick: undefined });
    expect(entries.slice(1).every((entry) => entry.leaveTick !== undefined)).toBe(true);
  });

  it("keeps achievement events on entries built from persistent room history", () => {
    const selectedCog = cog("ada", "Ada", "stage") as ReturnType<typeof cog> & {
      roomHistory: Array<{ roomId: string; spotId: string; enteredTick: number; leftTick?: number }>;
    };
    selectedCog.roomHistory = [{ roomId: "stage", spotId: "stage-a", enteredTick: 1 }];
    const snapshot = snapshotWithDiaryEvents();
    snapshot.cogs = [selectedCog];
    snapshot.recentEvents = [
      {
        actorId: "ada",
        id: "ada-achievement",
        message: "Ada completed Win Round in Stage for 10 points",
        position: { x: 8, y: 1 },
        tick: 2,
        type: "score",
      },
    ];

    const entries = buildDiaryRoomEntries(selectedCog, snapshot);
    const html = renderDiaryRoomFeed(entries, { cogId: "ada", currentRoomId: "stage", visibleRoomCount: 4 });

    expect(entries[0]?.achievements).toHaveLength(1);
    expect(html).toContain('data-event-kind="achievement"');
    expect(html).toContain("Ada completed Win Round in Stage");
  });

  it("renders the current room expanded and pages older room sections", () => {
    const entries = Array.from({ length: 8 }, (_, index) =>
      diaryEntry({
        id: `ada-room-${index}`,
        roomId: `room-${index}`,
        roomLabel: index === 0 ? "Current Room" : `Past Room ${index}`,
        enterTick: 100 - index,
        leaveTick: index === 0 ? undefined : 100 - index,
      }),
    );

    const html = renderDiaryRoomFeed(entries, { cogId: "ada", currentRoomId: "room-0", visibleRoomCount: 6 });
    const currentOpenTag = openingTagFor(html, 'data-diary-entry-id="ada-room-0"');
    const previousOpenTag = openingTagFor(html, 'data-diary-entry-id="ada-room-1"');

    expect(currentOpenTag).toContain("open");
    expect(previousOpenTag).not.toContain("open");
    expect(html).toContain("Current");
    expect(html).toContain('data-event-kind="person"');
    expect(html).toContain("Load 2 more rooms");
    expect(html).toContain("2 hidden");
    expect(html).toContain("Past Room 5");
    expect(html).not.toContain("Past Room 6");
  });

  it("renders diary events newest first within each room", () => {
    const entry = diaryEntry({ id: "ada-bar", roomId: "bar", roomLabel: "Bar", enterTick: 1, leaveTick: undefined });
    entry.events = [
      {
        actor: { id: "ada", name: "Ada", color: "red", spriteSheetKey: "cog-default" },
        event: move("ada-arrive", 1, "ada", "Ada arrived at Bar - stool", { x: 1, y: 1 }),
        kind: "person",
      },
      {
        event: debateExchange("ada-debate", 3, "ada", "babbage", "Ada's reason shook Babbage's certainty", { x: 1, y: 1 }),
        kind: "debate",
      },
      {
        event: colorChange("ada-flip", 5, "ada", "Ada converted from blue to red", { x: 1, y: 1 }),
        kind: "flip",
      },
    ];

    const html = renderDiaryRoomFeed([entry], { cogId: "ada", currentRoomId: "bar", visibleRoomCount: 4 });

    expect(html.indexOf('data-event-kind="flip"')).toBeLessThan(html.indexOf('data-event-kind="debate"'));
    expect(html.indexOf('data-event-kind="debate"')).toBeLessThan(html.indexOf("Ada entered Bar"));
  });

  it("renders diary movement rows as IRC-style lines with neutral cog sprite icons", () => {
    const snapshot = snapshotWithDiaryEvents();
    snapshot.cogs = [
      {
        ...cog("ada", "Ada", "bar"),
        color: "red",
        spriteUrl: "/sprites/ada-base.png",
        spriteUrls: { red: "/sprites/ada-red.png", blue: "/sprites/ada-blue.png" },
      },
      {
        ...cog("babbage", "Babbage", "bar"),
        color: "blue",
        spriteUrl: "/sprites/babbage-base.png",
        spriteUrls: { red: "/sprites/babbage-red.png", blue: "/sprites/babbage-blue.png" },
      },
    ];
    const entries = buildDiaryRoomEntries(snapshot.cogs[0]!, snapshot);

    const html = renderDiaryRoomFeed(entries, { cogId: "ada", currentRoomId: "bar", visibleRoomCount: 4 });

    expect(html).toContain("profile-diary-event-person");
    expect(html).toContain("profile-diary-direction");
    expect(html).toContain("profile-diary-direction-enter");
    expect(html).toContain("profile-diary-direction-exit");
    expect(html).not.toContain("-&gt;");
    expect(html).toContain('class="profile-diary-cog-avatar" data-color="red"');
    expect(html).toContain('class="profile-diary-cog-avatar" data-color="blue"');
    expect(html).toContain('src="/sprites/ada-base.png"');
    expect(html).toContain('src="/sprites/babbage-base.png"');
    expect(html).toContain(">1 debates</span>");
    expect(html).toContain(">1 witnessed</span>");
    expect(html).toContain("profile-diary-chat-meta");
    expect(html).not.toContain("profile-diary-room-meta");
    expect(html).not.toContain(">People</span>");
    expect(html).not.toContain(">people</span>");
  });

  it("shows the current room plus the previous five rooms collapsed by default", () => {
    const entries = Array.from({ length: 7 }, (_, index) =>
      diaryEntry({
        id: `ada-room-${index}`,
        roomId: `room-${index}`,
        roomLabel: index === 0 ? "Current Room" : `Past Room ${index}`,
        enterTick: 100 - index,
        leaveTick: index === 0 ? undefined : 100 - index,
      }),
    );

    const html = renderDiaryRoomFeed(entries, {
      cogId: "ada",
      currentRoomId: "room-0",
      visibleRoomCount: DIARY_INITIAL_ROOM_LIMIT,
    });

    expect(openingTagFor(html, 'data-diary-entry-id="ada-room-0"')).toContain("open");
    expect(openingTagFor(html, 'data-diary-entry-id="ada-room-1"')).not.toContain("open");
    expect(openingTagFor(html, 'data-diary-entry-id="ada-room-2"')).not.toContain("open");
    expect(openingTagFor(html, 'data-diary-entry-id="ada-room-3"')).not.toContain("open");
    expect(openingTagFor(html, 'data-diary-entry-id="ada-room-4"')).not.toContain("open");
    expect(openingTagFor(html, 'data-diary-entry-id="ada-room-5"')).not.toContain("open");
    expect(html).toContain("Past Room 5");
    expect(html).not.toContain("Past Room 6");
  });

  it("renders diary debate rows as the played tactic icons with the winner outlined", () => {
    const debate = debateExchange("ada-debate", 3, "ada", "babbage", "Ada's reason shook Babbage's certainty", { x: 1, y: 1 });
    const entry = diaryEntry({ id: "ada-room", roomId: "bar", roomLabel: "Bar", enterTick: 1, leaveTick: undefined });
    entry.events = [{ event: debate, kind: "debate" }];
    entry.debateResults = [debate];

    const html = renderDiaryRoomFeed([entry], { cogId: "ada", currentRoomId: "bar", visibleRoomCount: 4 });

    expect(html).toContain("profile-diary-event-tactics");
    expect(html).toMatch(/profile-diary-tactic-icon profile-diary-tactic-winner" data-tactic="reason"/);
    expect(html).toMatch(/profile-diary-tactic-icon" data-tactic="spin"/);
    expect(html).not.toContain(">Debate</span>");
  });

  it("renders diary debate rows as colored certainty changes when the debate log is available", () => {
    const snapshot = snapshotWithDiaryEvents();
    snapshot.cogs = [cog("you", "Cog 20", "bar")];
    snapshot.recentEvents = [
      debateExchange("recent-debate", 3, "cog18", "cog19", "Cog 18's passion shook Cog 19's certainty", { x: 1, y: 1 }, [
        "you",
      ]),
    ];
    snapshot.debateLog = [
      {
        id: "recent-debate-log",
        tick: 3,
        round: 1,
        outcome: "win",
        winnerCogId: "cog18",
        winnerColor: "red",
        actions: [
          { cogId: "cog18", cogName: "Cog 18", color: "red", tactic: "reason" },
          { cogId: "cog19", cogName: "Cog 19", color: "blue", tactic: "spin" },
        ],
        changes: [
          {
            cogId: "cog18",
            cogName: "Cog 18",
            role: "participant",
            colorBefore: "red",
            colorAfter: "red",
            certaintyBefore: 80,
            certaintyAfter: 80,
            certaintyDelta: 0,
          },
          {
            cogId: "cog19",
            cogName: "Cog 19",
            role: "participant",
            colorBefore: "blue",
            colorAfter: "blue",
            certaintyBefore: 30,
            certaintyAfter: 35,
            certaintyDelta: 5,
          },
          {
            cogId: "you",
            cogName: "Cog 20",
            role: "witness",
            colorBefore: "red",
            colorAfter: "red",
            certaintyBefore: 45,
            certaintyAfter: 35,
            certaintyDelta: -10,
          },
        ],
        conversions: [],
      },
    ];

    const entries = buildDiaryRoomEntries(snapshot.cogs[0]!, snapshot);
    const html = renderDiaryRoomFeed(entries, { cogId: "you", currentRoomId: "bar", visibleRoomCount: 4 });

    expect(html).toMatch(
      /data-color="blue">Cog 19<\/strong>\s*<span class="profile-diary-certainty-change">\(30-&gt;35\)<\/span>[\s\S]*data-color="red">You<\/strong>\s*<span class="profile-diary-certainty-change">\(45-&gt;35\)<\/span>/,
    );
    expect(html).not.toContain("Cog 18's passion shook Cog 19's certainty");
    expect(html).not.toContain("Cog 18 (80-&gt;80)");
  });

  it("renders diary flip rows as the new team color circle", () => {
    const flip = colorChange("ada-flip", 9, "ada", "Ada converted from blue to red", { x: 8, y: 1 });
    const entry = diaryEntry({ id: "ada-room", roomId: "stage", roomLabel: "Stage", enterTick: 8, leaveTick: undefined });
    entry.events = [{ event: flip, kind: "flip" }];
    entry.flips = [flip];

    const html = renderDiaryRoomFeed([entry], { cogId: "ada", currentRoomId: "stage", visibleRoomCount: 4 });

    expect(html).toContain("profile-diary-color-circle");
    expect(html).toContain('data-color="red"');
    expect(html).not.toContain("🔁");
  });

  it("expands the newest room section when the cog is between rooms", () => {
    const entries = [
      diaryEntry({
        id: "ada-room-latest",
        roomId: "latest-room",
        roomLabel: "Latest Room",
        enterTick: 10,
        leaveTick: 11,
      }),
      diaryEntry({
        id: "ada-room-older",
        roomId: "older-room",
        roomLabel: "Older Room",
        enterTick: 1,
        leaveTick: 2,
      }),
    ];

    const html = renderDiaryRoomFeed(entries, { cogId: "ada", currentRoomId: undefined, visibleRoomCount: 6 });

    expect(openingTagFor(html, 'data-diary-entry-id="ada-room-latest"')).toContain("open");
    expect(openingTagFor(html, 'data-diary-entry-id="ada-room-older"')).not.toContain("open");
  });

  it("renders a bottom game flow panel from game flow events only", () => {
    const html = renderGameFlowPanel([
      {
        id: "move-1",
        tick: 1,
        type: "move",
        actorId: "cog-1",
        message: "Ada moved west",
      },
      {
        id: "flow-2",
        tick: 2,
        type: "gameFlow",
        actorId: "cog-1",
        targetId: "cog-2",
        message: "starting debate between Ada and Babbage",
      },
      {
        id: "flow-3",
        tick: 3,
        type: "gameFlow",
        actorId: "cog-1",
        message: "asking Ada to move",
      },
    ]);

    expect(html).toContain("game-flow-panel");
    expect(html).toContain("starting debate between Ada and Babbage");
    expect(html).toContain("asking Ada to move");
    expect(html).not.toContain("Ada moved west");
  });

  it("renders a bottom ticker for conversions, completed achievements, and teams reaching majority", () => {
    const html = renderGameTicker({
      ...snapshotWithDiaryEvents(),
      tick: 25,
      cogs: [
        { ...cog("shear", "E.Shear", "stage"), color: "red" },
        {
          ...cog("bloomn", "D.Bloomn", "bar"),
          color: "red",
          completedAchievements: [
            {
              achievementId: "winInRoom",
              assignedTick: 1,
              assignmentId: "win-bar-fight",
              completedTick: 23,
              parameters: { roomKind: "bar" },
              points: 10,
              timeoutTick: 40,
            },
          ],
        },
        { ...cog("blue", "Blue Holdout", "bar"), color: "blue" },
      ],
      recentEvents: [
        move("move-1", 20, "blue", "Blue Holdout arrived at Bar - booth", { x: 2, y: 1 }),
        colorChange("shear-flip", 22, "shear", "E.Shear converted from blue to red", { x: 8, y: 1 }),
      ],
    });

    expect(html).toContain("game-ticker-panel");
    expect(html).toContain('data-ticker-kind="conversion"');
    expect(html).toContain('data-ticker-kind="achievement"');
    expect(html).toContain('data-ticker-kind="majority"');
    expect(html).toContain('class="game-ticker-name" data-color="red">E.Shear</span>');
    expect(html).toContain('class="game-ticker-name" data-color="red">D.Bloomn</span>');
    expect(html).toContain(">flipped to<");
    expect(html).toContain(">achieves<");
    expect(html).toContain("Win Round in Bar");
    expect(html).toContain(">reaches majority<");
    expect(html).toContain('class="game-ticker-team" data-color="red">Red</span>');
    expect(html).not.toContain("Blue Holdout arrived");
  });

  it("renders new cog arrivals in the bottom ticker from spawn events", () => {
    const html = renderGameTicker({
      ...snapshotWithDiaryEvents(),
      tick: 25,
      cogs: [{ ...cog("ada", "Ada", "bar"), color: "red" }],
      recentEvents: [
        {
          actorId: "ada",
          id: "ada-spawn",
          message: "Ada arrived!",
          position: { x: 1, y: 1 },
          tick: 24,
          type: "spawn",
        },
      ],
    });

    expect(html).toContain("game-ticker-panel");
    expect(html).toContain('data-ticker-kind="arrival"');
    expect(html).toContain('class="game-ticker-name" data-color="red">Ada</span>');
    expect(html).toContain(">arrived!<");
  });

  it("renders each ticker event only once", () => {
    const html = renderGameTicker({
      ...snapshotWithDiaryEvents(),
      tick: 25,
      cogs: [{ ...cog("ada", "Ada", "bar"), color: "red" }],
      recentEvents: [
        {
          actorId: "ada",
          id: "ada-spawn",
          message: "Ada arrived!",
          position: { x: 1, y: 1 },
          tick: 24,
          type: "spawn",
        },
      ],
    });

    expect(html.match(/class="game-ticker-name" data-color="red">Ada<\/span>/g)).toHaveLength(1);
    expect(html.match(/data-ticker-kind="arrival"/g)).toHaveLength(1);
  });

  it("renders a triangle debate tactic legend", () => {
    const html = renderDebateTacticLegend();

    expect(html).toContain("tactic-legend-panel");
    expect(html).toContain("reason beats spin; spin beats passion; passion beats reason");
    expect(html).toContain('data-tactic="reason"');
    expect(html).toContain('data-tactic="passion"');
    expect(html).toContain('data-tactic="spin"');
    expect(html).toContain("🧠");
    expect(html).toContain("🔥");
    expect(html).toContain("🌀");
    expect(html).toContain("tactic-marker-reason-spin");
    expect(html).toContain("tactic-marker-spin-passion");
    expect(html).toContain("tactic-marker-passion-reason");
    expect(html).toContain('d="M42 65 C45 57 49 50 54 44"');
    expect(html).not.toContain("tactic-arrow ");
    expect(html).not.toContain("tactic-arrowhead");
  });

  it("renders per-team counts inside the top teams bar", () => {
    const html = renderTeamsGauge([
      { id: "red-1", name: "Red 1", color: "red" },
      { id: "red-2", name: "Red 2", color: "red" },
      { id: "blue-1", name: "Blue 1", color: "blue" },
    ] as WorldSnapshot["cogs"]);

    expect(html).not.toContain(">Teams<");
    expect(html).not.toContain(">red<");
    expect(html).not.toContain(">blue<");
    expect(html).toContain('class="team-segment-count">2</span>');
    expect(html).toContain('class="team-segment-count">1</span>');
    expect(html).not.toContain("3 cogs");
  });

  it("shows recent conversion impact on the affected team counts", () => {
    const html = renderTeamsGauge(
      [
        { id: "red-1", name: "Red 1", color: "red" },
        { id: "red-2", name: "Red 2", color: "red" },
        { id: "blue-1", name: "Blue 1", color: "blue" },
      ] as WorldSnapshot["cogs"],
      false,
      [
        {
          id: "flip-1",
          tick: 10,
          type: "colorChange",
          actorId: "red-2",
          message: "Red 2 converted from blue to red",
        },
      ],
      10 + legacyHalfSecondTicksToSimulationTicks(2),
    );

    expect(html).toContain('aria-label="red 2, blue 1"');
    expect(html).toContain("--team-impact-age-ms: -1000ms");
    expect(html).toContain('class="team-segment-arrow" data-direction="up"');
    expect(html).toContain('class="team-segment-arrow" data-direction="down"');
    expect(html).not.toContain(">+1<");
    expect(html).not.toContain(">-1<");
  });

});

function snapshotWithDiaryEvents(): WorldSnapshot {
  return {
    tick: 9,
    dimensions: { width: 10, height: 10 },
    venue: {
      rooms: [
        { id: "bar", label: "Bar", kind: "bar", spotIds: ["bar-a", "bar-b"], neighborIds: ["stage"] },
        { id: "stage", label: "Stage", kind: "stage", spotIds: ["stage-a", "stage-b"], neighborIds: ["bar"] },
      ],
      spots: [
        { id: "bar-a", roomId: "bar", label: "stool", position: { x: 1, y: 1 } },
        { id: "bar-b", roomId: "bar", label: "booth", position: { x: 2, y: 1 } },
        { id: "stage-a", roomId: "stage", label: "left", position: { x: 8, y: 1 } },
        { id: "stage-b", roomId: "stage", label: "right", position: { x: 9, y: 1 } },
      ],
      spotLinks: [],
      roomPaths: [],
    },
    cogs: [cog("ada", "Ada", "stage"), cog("babbage", "Babbage", "bar")],
    objects: [],
    terrain: [],
    achievementCounts: [],
    recentEvents: [
      move("ada-enter-bar", 1, "ada", "Ada arrived at Bar - stool", { x: 1, y: 1 }),
      move("babbage-enter-bar", 2, "babbage", "Babbage arrived at Bar - booth", { x: 2, y: 1 }),
      debateExchange("ada-debate", 3, "ada", "babbage", "Ada's reason shook Babbage's certainty", { x: 1, y: 1 }),
      debateExchange("witnessed-debate", 4, "mira", "turing", "Mira's spin shook Turing's certainty", { x: 1, y: 1 }, ["ada"]),
      colorChange("babbage-flip", 5, "babbage", "Babbage converted from blue to red", { x: 2, y: 1 }),
      move("babbage-leave-bar", 6, "babbage", "Babbage started moving to Stage - right", { x: 2, y: 1 }),
      move("ada-leave-bar", 7, "ada", "Ada started moving to Stage - left", { x: 1, y: 1 }),
      move("ada-enter-stage", 8, "ada", "Ada arrived at Stage - left", { x: 8, y: 1 }),
      colorChange("ada-flip", 9, "ada", "Ada converted from blue to red", { x: 8, y: 1 }),
    ],
  };
}

function snapshotWithSameRoomMove(): WorldSnapshot {
  const snapshot = snapshotWithDiaryEvents();
  snapshot.tick = 5;
  snapshot.recentEvents = [
    { id: "ada-gameflow", tick: 0, type: "gameFlow", actorId: "ada", message: "asking Ada to move", position: { x: 1, y: 1 } },
    move("ada-enter-bar", 1, "ada", "Ada arrived at Bar - stool", { x: 1, y: 1 }),
    move("ada-move-bar", 2, "ada", "Ada started moving to Bar - booth", { x: 1, y: 1 }),
    move("ada-arrive-bar", 3, "ada", "Ada arrived at Bar - booth", { x: 2, y: 1 }),
    move("ada-leave-bar", 4, "ada", "Ada started moving to Stage - left", { x: 2, y: 1 }),
    move("ada-enter-stage", 5, "ada", "Ada arrived at Stage - left", { x: 8, y: 1 }),
  ];
  return snapshot;
}

function cog(id: string, name: string, roomId: string): WorldSnapshot["cogs"][number] {
  return {
    id,
    name,
    behaviorPrompt: "",
    position: roomId === "bar" ? { x: 1, y: 1 } : { x: 8, y: 1 },
    location: { roomId, spotId: roomId === "bar" ? "bar-a" : "stage-a" },
    spriteSheetKey: "cog-default",
    attributes: {},
    color: "red",
    defensiveTrait: "stubborn",
    activeTrait: "forceful",
    personalGoal: "majority",
    activity: "idle",
    personalScore: 0,
    achievements: [],
    completedAchievements: [],
    goalScores: [],
    stats: { argumentsWon: 0, argumentsLost: 0, teamFlips: 0 },
    certainty: 100,
    controllerId: "stub",
    movementCooldown: 0,
    conversationLog: [],
  };
}

function move(id: string, tick: number, actorId: string, message: string, position: { x: number; y: number }): WorldEvent {
  return { id, tick, type: "move", actorId, message, position };
}

function colorChange(id: string, tick: number, actorId: string, message: string, position: { x: number; y: number }): WorldEvent {
  return { id, tick, type: "colorChange", actorId, message, position };
}

function debateExchange(
  id: string,
  tick: number,
  actorId: string,
  targetId: string,
  message: string,
  position: { x: number; y: number },
  witnessCogIds: string[] = [],
): WorldEvent {
  return {
    id,
    tick,
    type: "debateExchange",
    actorId,
    targetId,
    message,
    position,
    debate: {
      actions: [
        { cogId: actorId, action: "reason" },
        { cogId: targetId, action: "spin" },
      ],
      choicesRevealedAtTick: tick,
      resultRevealedAtTick: tick,
      expiresAtTick: tick + 1,
      outcome: "win",
      round: 1,
      winnerCogId: actorId,
      winnerColor: "red",
      witnessCogIds,
    },
  };
}

function debateLogEntry(
  id: string,
  tick: number,
  firstCogId: string,
  firstCogName: string,
  secondCogId: string,
  secondCogName: string,
  winnerCogId: string,
  firstTactic: "reason" | "spin" | "passion",
  secondTactic: "reason" | "spin" | "passion",
  witnessCogIds: string[] = [],
): NonNullable<WorldSnapshot["debateLog"]>[number] {
  return {
    id,
    tick,
    round: 1,
    outcome: "win",
    winnerCogId,
    winnerColor: "red",
    actions: [
      { cogId: firstCogId, cogName: firstCogName, color: "red", tactic: firstTactic },
      { cogId: secondCogId, cogName: secondCogName, color: "blue", tactic: secondTactic },
    ],
    changes: [
      { cogId: firstCogId, cogName: firstCogName, role: "participant", colorBefore: "red", colorAfter: "red", certaintyBefore: 50, certaintyAfter: 74, certaintyDelta: 24 },
      { cogId: secondCogId, cogName: secondCogName, role: "participant", colorBefore: "blue", colorAfter: "blue", certaintyBefore: 50, certaintyAfter: 26, certaintyDelta: -24 },
      ...witnessCogIds.map((cogId) => ({
        cogId,
        cogName: cogId === "ada" ? "Ada" : cogId,
        role: "witness" as const,
        colorBefore: "red" as const,
        colorAfter: "red" as const,
        certaintyBefore: 50,
        certaintyAfter: 54,
        certaintyDelta: 4,
      })),
    ],
    conversions: [],
  };
}

function diaryEntry(input: {
  id: string;
  roomId: string;
  roomLabel: string;
  enterTick: number;
  leaveTick: number | undefined;
}): DiaryRoomEntry {
  const event = move(`${input.id}-event`, input.enterTick, "ada", `Ada arrived at ${input.roomLabel}`, { x: 1, y: 1 });
  return {
    ...input,
    events: [{ event, kind: "person" }],
    achievements: [],
    flips: [],
    debateResults: [],
    witnessedDebates: [],
    people: [event],
    roomCogs: [],
  };
}

function openingTagFor(html: string, marker: string): string {
  const markerIndex = html.indexOf(marker);
  expect(markerIndex).toBeGreaterThanOrEqual(0);
  const tagStart = html.lastIndexOf("<details", markerIndex);
  const tagEnd = html.indexOf(">", markerIndex);
  return html.slice(tagStart, tagEnd);
}
