import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import { renderDebateBubbleContent } from "../../src/client/ui/debate-bubble";
import type { Cog, DebateLogEntry, WorldEvent } from "../../src/shared/types";

const styles = readFileSync(new URL("../../src/client/ui/styles.css", import.meta.url), "utf8");

const redCog = {
  id: "red-cog",
  name: "Ada",
  color: "red",
  certainty: 74,
} as Cog;

const blueCog = {
  id: "blue-cog",
  name: "Babbage",
  color: "blue",
  certainty: 39,
} as Cog;

describe("debate bubble rendering", () => {
  it("starts unresolved debates as two team-colored question circles", () => {
    const markup = renderDebateBubbleContent(redCog, blueCog, []);

    expect(markup.match(/data-debate-action="pending"/g)).toHaveLength(2);
    expect(markup.match(/class="debate-action-placeholder"/g)).toHaveLength(2);
    expect(markup).toContain("debate-action-red");
    expect(markup).toContain("debate-action-blue");
    expect(markup).not.toContain("debate-action-winner");
    expect(markup).not.toContain('class="debate-winner');
    expect(markup).not.toContain("Choices");
    expect(markup).not.toContain("Result");
  });

  it("shows red and blue certainty bars anchored from each action circle", () => {
    const markup = renderDebateBubbleContent(redCog, blueCog, []);

    expect(markup).toContain('class="debate-certainty-track debate-certainty-top debate-certainty-red debate-certainty-from-first"');
    expect(markup).toContain('class="debate-certainty-track debate-certainty-bottom debate-certainty-blue debate-certainty-from-second"');
    expect(markup).toContain('data-debate-certainty="red"');
    expect(markup).toContain('data-debate-certainty="blue"');
    expect(markup).toContain('style="--debate-certainty: 74%; --debate-certainty-fill: 74%;"');
    expect(markup).toContain('style="--debate-certainty: 39%; --debate-certainty-fill: 39%;"');
    expect(markup).toContain("red certainty 74%");
    expect(markup).toContain("blue certainty 39%");
  });

  it("scales certainty bars by the active conversion threshold", () => {
    const markup = renderDebateBubbleContent(redCog, blueCog, [], undefined, [], 200);

    expect(markup).toContain('style="--debate-certainty: 37%; --debate-certainty-fill: 37%;"');
    expect(markup).toContain('style="--debate-certainty: 20%; --debate-certainty-fill: 20%;"');
    expect(markup).toContain("red certainty 37%");
    expect(markup).toContain("blue certainty 20%");
  });

  it("keeps very low nonzero certainty visible as a flat sliver", () => {
    const fragileBlueCog = { ...blueCog, certainty: 1 } as Cog;
    const markup = renderDebateBubbleContent(redCog, fragileBlueCog, []);

    expect(markup).toContain('style="--debate-certainty: 1%; --debate-certainty-fill: 4%;"');
    expect(markup).toContain("blue certainty 1%");
    expect(markup).not.toContain("data-debate-certainty-locked");
    expect(markup).not.toContain("debate-certainty-lock");
  });

  it("marks zealots at the locked certainty floor", () => {
    const zealotRedCog = { ...redCog, defensiveTrait: "zealot", certainty: 1 } as Cog;
    const markup = renderDebateBubbleContent(zealotRedCog, blueCog, []);

    expect(markup).toContain('class="debate-zealot-badge"');
    expect(markup).toContain('class="debate-zealot-badge-lock"');
    expect(markup).toContain("ZEALOT</span>");
    expect(markup).toContain("Ada is a Zealot and cannot convert");
    expect(markup).toContain("debate-certainty-locked");
    expect(markup).toContain('data-debate-certainty-locked="true"');
    expect(markup).toContain('class="debate-certainty-lock"');
    expect(markup).toContain("red certainty 1%, Zealot conversion locked");
  });

  it("shows the matchup names with team-colored text", () => {
    const fredCog = { ...blueCog, name: "Fred" } as Cog;
    const markup = renderDebateBubbleContent(redCog, fredCog, []);

    expect(markup).toContain('class="debate-matchup"');
    expect(markup).toContain('class="debate-matchup-name debate-matchup-name-red">Ada</span>');
    expect(markup).toContain('class="debate-matchup-vs">vs</span>');
    expect(markup).toContain('class="debate-matchup-name debate-matchup-name-blue">Fred</span>');
  });

  it("keeps debate matchup names on one line with truncation fallback", () => {
    const bubbleBlock = cssBlock(".debate-bubble");
    const nameBlock = cssBlock(".debate-matchup-name");

    expect(bubbleBlock).toContain("--debate-side-width: 62px;");
    expect(bubbleBlock).toContain("width: 184px;");
    expect(nameBlock).toContain("overflow: hidden;");
    expect(nameBlock).toContain("text-overflow: ellipsis;");
    expect(nameBlock).toContain("white-space: nowrap;");
    expect(nameBlock).not.toContain("overflow-wrap: anywhere;");
  });

  it("renders resolved arguments as staged tactic circles and marks the winning circle", () => {
    const events: WorldEvent[] = [
      {
        id: "event-1",
        tick: 9,
        type: "debateExchange",
        actorId: redCog.id,
        targetId: blueCog.id,
        message: "Ada's reason shook Babbage's certainty",
        debate: {
          actions: [
            { cogId: redCog.id, action: "reason" },
            { cogId: blueCog.id, action: "spin" },
          ],
          choicesRevealedAtTick: 9,
          resultRevealedAtTick: 15,
          expiresAtTick: 49,
          outcome: "win",
          round: 1,
          winnerCogId: redCog.id,
          winnerColor: "red",
        },
      },
    ];

    const markup = renderDebateBubbleContent(redCog, blueCog, events);

    expect(markup).toContain('data-debate-action="reason"');
    expect(markup).toContain('data-debate-action="spin"');
    expect(markup).toContain("🧠");
    expect(markup).toContain("🌀");
    expect(markup).toContain("debate-action-red");
    expect(markup).toContain("debate-action-blue");
    expect(markup).toContain("debate-action-resolved");
    expect(markup).toContain("debate-result-fill-red");
    expect(markup).toContain("debate-result-fill-from-first");
    expect(markup).toContain('data-debate-outcome="win"');
    expect(markup).toContain("debate-action-winner");
    expect(markup).toContain("debate-action-loser");
    expect(markup).toContain("debate-action-side-first");
    expect(markup).toContain("debate-action-side-second");
    expect(markup).toContain("debate-action-result");
    expect(markup).toContain('data-debate-winner="true"');
    expect(markup).toContain('data-debate-winner="false"');
    expect(markup).toContain("Ada: reason, winner");
    expect(markup).not.toContain("debate-action-placeholder");
    expect(markup).not.toContain('class="debate-winner');
    expect(markup).not.toContain("Choices");
    expect(markup).not.toContain("Result");
  });

  it("shows choices before result and returns to prep after the result expires", () => {
    const events: WorldEvent[] = [
      {
        id: "event-1",
        tick: 9,
        type: "debateExchange",
        actorId: redCog.id,
        targetId: blueCog.id,
        message: "Ada's reason shook Babbage's certainty",
        debate: {
          actions: [
            { cogId: redCog.id, action: "reason" },
            { cogId: blueCog.id, action: "spin" },
          ],
          choicesRevealedAtTick: 9,
          resultRevealedAtTick: 15,
          expiresAtTick: 21,
          outcome: "win",
          round: 1,
          winnerCogId: redCog.id,
          winnerColor: "red",
        },
      },
    ];

    const choicesMarkup = renderDebateBubbleContent(redCog, blueCog, events, 12);
    expect(choicesMarkup).toContain('data-debate-phase="choices"');
    expect(choicesMarkup).toContain('data-debate-action="reason"');
    expect(choicesMarkup).not.toContain("debate-action-placeholder");
    expect(choicesMarkup).not.toContain("debate-action-result");
    expect(choicesMarkup).not.toContain("debate-action-winner");
    expect(choicesMarkup).not.toContain("debate-action-loser");

    const resultMarkup = renderDebateBubbleContent(redCog, blueCog, events, 16);
    expect(resultMarkup).toContain('data-debate-phase="result"');
    expect(resultMarkup).toContain('data-debate-outcome="win"');
    expect(resultMarkup).not.toContain("debate-action-placeholder");
    expect(resultMarkup).toContain("debate-action-result");
    expect(resultMarkup).toContain("debate-action-winner");
    expect(resultMarkup).toContain("debate-action-loser");

    const prepMarkup = renderDebateBubbleContent(redCog, blueCog, events, 21);
    expect(prepMarkup).toContain('data-debate-phase="prep"');
    expect(prepMarkup.match(/data-debate-action="pending"/g)).toHaveLength(2);
  });

  it("renders same-symbol results as a draw bounce without color fill", () => {
    const events: WorldEvent[] = [
      {
        id: "event-1",
        tick: 9,
        type: "debateExchange",
        actorId: redCog.id,
        targetId: blueCog.id,
        message: "Ada and Babbage both chose passion",
        debate: {
          actions: [
            { cogId: redCog.id, action: "passion" },
            { cogId: blueCog.id, action: "passion" },
          ],
          choicesRevealedAtTick: 9,
          resultRevealedAtTick: 15,
          expiresAtTick: 49,
          outcome: "draw",
          round: 1,
        },
      },
    ];

    const markup = renderDebateBubbleContent(redCog, blueCog, events, 16);

    expect(markup).toContain('data-debate-phase="result"');
    expect(markup).toContain('data-debate-outcome="draw"');
    expect(markup).toContain('--debate-result-age-ms: -500ms;');
    expect(markup.match(/data-debate-action="passion"/g)).toHaveLength(2);
    expect(markup).toContain("debate-action-draw");
    expect(markup).not.toContain("debate-result-fill");
    expect(markup).not.toContain("debate-action-winner");
    expect(markup).not.toContain("debate-action-loser");
    expect(markup).not.toContain("debate-action-placeholder");
  });

  it("offsets tied result animation by result age so rerenders do not replay the bounce", () => {
    const events: WorldEvent[] = [
      {
        id: "event-1",
        tick: 9,
        type: "debateExchange",
        actorId: redCog.id,
        targetId: blueCog.id,
        message: "Ada and Babbage both chose passion",
        debate: {
          actions: [
            { cogId: redCog.id, action: "passion" },
            { cogId: blueCog.id, action: "passion" },
          ],
          choicesRevealedAtTick: 9,
          resultRevealedAtTick: 15,
          expiresAtTick: 49,
          outcome: "draw",
          round: 1,
        },
      },
    ];

    const markup = renderDebateBubbleContent(redCog, blueCog, events, 18);

    expect(markup).toContain('data-debate-phase="result"');
    expect(markup).toContain('--debate-result-age-ms: -1500ms;');
    expect(markup).toContain("debate-action-draw");
    expect(markup).not.toContain("debate-action-placeholder");
  });

  it("shows the lost certainty segment as its own animated layer", () => {
    const events: WorldEvent[] = [
      {
        id: "event-1",
        tick: 9,
        type: "debateExchange",
        actorId: redCog.id,
        targetId: blueCog.id,
        message: "Ada's reason shook Babbage's certainty",
        debate: {
          actions: [
            { cogId: redCog.id, action: "reason" },
            { cogId: blueCog.id, action: "spin" },
          ],
          choicesRevealedAtTick: 9,
          resultRevealedAtTick: 15,
          expiresAtTick: 49,
          outcome: "win",
          round: 1,
          winnerCogId: redCog.id,
          winnerColor: "red",
        },
      },
    ];
    const debateLog: DebateLogEntry[] = [
      {
        id: "wrong-log",
        tick: 8,
        round: 1,
        outcome: "win",
        winnerCogId: redCog.id,
        winnerColor: "red",
        actions: [
          { cogId: redCog.id, cogName: redCog.name, color: redCog.color, tactic: "reason" },
          { cogId: blueCog.id, cogName: blueCog.name, color: blueCog.color, tactic: "spin" },
        ],
        changes: [
          {
            cogId: blueCog.id,
            cogName: blueCog.name,
            role: "participant",
            colorBefore: "blue",
            colorAfter: "blue",
            certaintyBefore: 99,
            certaintyAfter: 1,
            certaintyDelta: -98,
          },
        ],
        conversions: [],
      },
      {
        id: "log-1",
        tick: 9,
        round: 1,
        outcome: "win",
        winnerCogId: redCog.id,
        winnerColor: "red",
        actions: [
          { cogId: redCog.id, cogName: redCog.name, color: redCog.color, tactic: "reason" },
          { cogId: blueCog.id, cogName: blueCog.name, color: blueCog.color, tactic: "spin" },
        ],
        changes: [
          {
            cogId: redCog.id,
            cogName: redCog.name,
            role: "participant",
            colorBefore: "red",
            colorAfter: "red",
            certaintyBefore: 64,
            certaintyAfter: 74,
            certaintyDelta: 10,
          },
          {
            cogId: blueCog.id,
            cogName: blueCog.name,
            role: "participant",
            colorBefore: "blue",
            colorAfter: "blue",
            certaintyBefore: 62,
            certaintyAfter: 39,
            certaintyDelta: -23,
          },
        ],
        conversions: [],
      },
    ];

    const choicesMarkup = renderDebateBubbleContent(redCog, blueCog, events, 12, debateLog);
    expect(choicesMarkup).toContain("--debate-certainty: 62%;");
    expect(choicesMarkup).not.toContain("--debate-certainty-loss");
    expect(choicesMarkup).not.toContain('class="debate-certainty-loss"');

    const markup = renderDebateBubbleContent(redCog, blueCog, events, 16, debateLog);

    expect(markup).toContain("--debate-certainty: 39%; --debate-certainty-fill: 39%; --debate-certainty-before: 62%; --debate-certainty-fill-before: 62%; --debate-certainty-loss: 23%; --debate-result-age-ms: -500ms;");
    expect(markup).toContain('class="debate-certainty-loss"');
    expect(markup.match(/class="debate-certainty-loss"/g)).toHaveLength(1);
  });
});

function cssBlock(selector: string): string {
  const match = styles.match(new RegExp(`${escapeRegExp(selector)}\\s*\\{[\\s\\S]*?\\n\\s*\\}`));
  expect(match).toBeTruthy();
  return match?.[0] ?? "";
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
