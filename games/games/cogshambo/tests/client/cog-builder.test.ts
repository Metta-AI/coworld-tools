import { describe, expect, it, vi } from "vitest";

import {
  BUILDER_STRATEGY_MAX_LENGTH,
  BUILDER_STRATEGY_PROMPTS,
  cogBuilderSteps,
  createBuilderPreviewDraft,
  createInitialBuilderDraft,
  renderCogBuilderPage,
} from "../../src/client/ui/cog-builder";
import { LatestRequestGuard } from "../../src/client/ui/hud";

function builderProfileAside(markup: string): string {
  return markup.match(/<aside class="builder-profile-aside"[\s\S]*?<\/aside>/)?.[0] ?? "";
}

describe("cog builder", () => {
  it("creates an autofilled initial draft with starter avatars and preselected traits", () => {
    const draft = createInitialBuilderDraft();

    expect(draft.name).toMatch(/^\S+$/);
    expect(draft.behaviorPrompt).not.toBe("");
    expect(draft.appearanceDescription).not.toBe("");
    expect(draft.attributes).toEqual({ energy: 5, focus: 5 });
    expect(draft.defensiveTrait).toBeTruthy();
    expect(draft.activeTrait).toBeTruthy();
    expect(draft.personalGoal).toBeUndefined();
    expect(draft.color).toBeUndefined();
    expect(draft.sprites).toHaveLength(10);
    expect(draft.selectedSpriteIndex).toBeGreaterThanOrEqual(0);
    expect(draft.selectedSpriteIndex).toBeLessThan(draft.sprites.length);
    expect(draft.sprites[0]?.spriteUrls).toBeUndefined();
  });

  it("randomly selects one of the ten starter avatars", () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0.99);

    try {
      const draft = createInitialBuilderDraft();

      expect(draft.sprites).toHaveLength(10);
      expect(draft.selectedSpriteIndex).toBe(9);
    } finally {
      random.mockRestore();
    }
  });

  it("pregenerates tactic-and-room main strategy prompts", () => {
    expect(BUILDER_STRATEGY_PROMPTS).toHaveLength(10);
    expect(new Set(BUILDER_STRATEGY_PROMPTS).size).toBe(BUILDER_STRATEGY_PROMPTS.length);
    expect(BUILDER_STRATEGY_PROMPTS.every((prompt) => prompt.length <= BUILDER_STRATEGY_MAX_LENGTH)).toBe(true);
    expect(BUILDER_STRATEGY_PROMPTS).toContain(
      "Prefer to use Reason unless the opponent keeps resorting to Passion. Hang out near the Main Stage.",
    );
    expect(BUILDER_STRATEGY_PROMPTS.every((prompt) => /Reason|Spin|Passion/.test(prompt))).toBe(true);
    expect(BUILDER_STRATEGY_PROMPTS.every((prompt) => /near the/.test(prompt))).toBe(true);
  });

  it("randomly selects one pregenerated main strategy", () => {
    const random = vi
      .spyOn(Math, "random")
      .mockReturnValueOnce(0)
      .mockReturnValueOnce(0.99)
      .mockReturnValue(0);

    try {
      const draft = createInitialBuilderDraft();

      expect(draft.behaviorPrompt).toBe(BUILDER_STRATEGY_PROMPTS[BUILDER_STRATEGY_PROMPTS.length - 1]);
    } finally {
      random.mockRestore();
    }
  });

  it("creates a staged preview draft with selected traits but no live text", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      activeTrait: "passionate" as const,
      appearanceDescription: "A live animated sentence",
      behaviorPrompt: "A live strategy sentence",
      color: "red" as const,
      defensiveTrait: "stubborn" as const,
      name: "Ada",
    };

    const previewDraft = createBuilderPreviewDraft(draft);

    expect(previewDraft).not.toBe(draft);
    expect(previewDraft.attributes).not.toBe(draft.attributes);
    expect(previewDraft.sprites).not.toBe(draft.sprites);
    expect(previewDraft.name).toBe("Ada");
    expect(previewDraft.defensiveTrait).toBe("stubborn");
    expect(previewDraft.activeTrait).toBe("passionate");
    expect(previewDraft.color).toBe("red");
    expect(previewDraft.appearanceDescription).toBe("");
    expect(previewDraft.behaviorPrompt).toBe("");
  });

  it("does not include a majority or underdog goal step", () => {
    const draft = createInitialBuilderDraft();
    const renderedSteps = cogBuilderSteps.map((step) => renderCogBuilderPage(draft, false, false, undefined, step)).join("");

    expect(cogBuilderSteps).not.toContain("personalGoal");
    expect(cogBuilderSteps).not.toContain("review");
    expect(draft.personalGoal).toBeUndefined();
    expect(renderedSteps).not.toContain('data-trait-kind="personalGoal"');
    expect(renderedSteps).not.toContain("Majority");
    expect(renderedSteps).not.toContain("Underdog");
    expect(renderedSteps).not.toContain("Trait 3");
    expect(renderedSteps).not.toContain("Cog review");
    expect(renderedSteps).not.toContain("Submit");
  });

  it("uses Pick a Side as the final confirmation step", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      color: undefined,
    };
    const markup = renderCogBuilderPage(draft, false, false, undefined, "side");

    expect(cogBuilderSteps.at(-1)).toBe("side");
    expect(markup).toContain("Pick a Side");
    expect(markup).toContain("The Blue Team");
    expect(markup).toContain("Team Zander");
    expect(markup).toContain("The Red Team");
    expect(markup).toContain("Team Takedown");
    expect(markup).toContain('data-action="set-builder-side"');
    expect(markup).toContain('data-builder-color="blue"');
    expect(markup).toContain('data-builder-color="red"');
    expect(markup).toContain('aria-label="Join The Blue Team"');
    expect(markup).toContain('aria-label="Join The Red Team"');
    expect(markup).not.toContain('data-action="builder-next"');
    expect(markup).not.toContain("Submit");
    expect(markup).not.toContain("Review");
  });

  it("marks the selected side and disables side choices while creating", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      color: "blue" as const,
    };
    const sideMarkup = renderCogBuilderPage(draft, true, false, undefined, "side");

    expect(sideMarkup).toContain('data-builder-color="blue"');
    expect(sideMarkup).toContain('aria-pressed="true"');
    expect(sideMarkup).toContain('aria-label="Creating The Blue Team Cog"');
    expect(sideMarkup).toContain("builder-side-card is-selected");
    expect(sideMarkup).toContain("Creating...");
    expect(sideMarkup).toContain("disabled");
    expect(sideMarkup).not.toContain('data-action="builder-next"');
  });

  it("does not show wireframe placeholders on the appearance step", () => {
    const markup = renderCogBuilderPage(createInitialBuilderDraft(), false, false, undefined, "appearance");

    expect(markup).not.toContain("<p>Description</p>");
    expect(markup).toContain("Keep it broad: shell, lens face, shape, and overall vibe.");
    expect(markup.match(/data-action="select-builder-sprite"/g)).toHaveLength(10);
    expect(markup).not.toContain("<span>Ada</span>");
    expect(markup).not.toContain("<span>Babbage</span>");
    expect(markup).not.toContain("<span>Mira</span>");
    expect(markup).not.toContain("<span>Default</span>");
    expect(markup).toContain('data-action="open-builder-custom-sprite"');
    expect(markup).toContain('data-action="roll-builder-step"');
    expect(markup).not.toContain('data-builder-field="appearance"');
    expect(markup).not.toContain('data-action="regenerate-builder-sprites"');
  });

  it("shows the custom avatar prompt after choosing Custom", () => {
    const markup = renderCogBuilderPage(
      { ...createInitialBuilderDraft(), customSpriteOpen: true },
      false,
      false,
      undefined,
      "appearance",
    );

    expect(markup).toContain('aria-label="Custom"');
    expect(markup).toContain("builder-sprite-option-custom is-custom-open");
    expect(markup).toContain(
      'placeholder="A round sky-blue Cog with big eyes, side ear caps, and a bright chest speaker."',
    );
    expect(markup).toContain("Keep it broad: shell, lens face, shape, and overall vibe.");
    expect(markup).toContain('maxlength="112"');
    expect(markup).toContain('data-builder-field="appearance"');
    expect(markup).toContain('data-action="regenerate-builder-sprites"');
    expect(markup).toContain("Generate custom sprite");
  });

  it("keeps an existing appearance visible when returning to the appearance step", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      appearanceDescription: "A careful room reader with a brass shell and teal lens.",
      name: "Ada",
    };
    const markup = renderCogBuilderPage(draft, false, false, undefined, "appearance");

    expect(markup).toContain('aria-label="Current Cog draft"');
    expect(markup).toContain("<p>A careful room reader with a brass shell and teal lens.</p>");
  });

  it("does not mirror live appearance typing into the profile preview", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      appearanceDescription: "A live animated sentence",
      customSpriteOpen: true,
      name: "Ada",
    };
    const previewDraft = {
      ...createInitialBuilderDraft(),
      name: "Ada",
    };
    const markup = renderCogBuilderPage(draft, false, false, undefined, "appearance", undefined, "appearance", previewDraft);

    expect(markup).toContain("A live animated sentence");
    expect(markup).not.toContain("<p>A live animated sentence</p>");
  });

  it("breaks the intro helper copy after room display", () => {
    const markup = renderCogBuilderPage(createInitialBuilderDraft(), false);

    expect(markup).toContain("Create a social player for the room display<br />and control it from here.");
    expect(markup).not.toContain("keep the phone controls simple");
  });

  it("renders the step roll button to the right of continue", () => {
    const markup = renderCogBuilderPage(createInitialBuilderDraft(), false, false, undefined, "name");

    expect(markup).toContain('data-action="roll-builder-step"');
    expect(markup).toMatch(
      /data-action="builder-back"[\s\S]*data-action="builder-next"[\s\S]*data-action="roll-builder-step"/,
    );
  });

  it("mirrors selected traits to the right of the avatar without trait categories", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      activeTrait: "passionate" as const,
      appearanceDescription: "A careful argument cartographer with brass trim.",
      behaviorPrompt: "A careful argument cartographer.",
      defensiveTrait: "stubborn" as const,
      name: "Ada",
    };

    const markup = renderCogBuilderPage(draft, false, false, undefined, "appearance");

    expect(markup).toContain('class="builder-profile-traits"');
    expect(markup).toContain("<em>Trait 1</em>");
    expect(markup).toContain("<em>Trait 2</em>");
    expect(markup).toContain("<strong>Stubborn</strong>");
    expect(markup).toContain("<strong>Passionate</strong>");
    expect(markup).not.toContain("<em>Defense</em>");
    expect(markup).not.toContain("<em>Offense</em>");
  });

  it("uses the same trait pool for both builder trait slots", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      name: "Ada",
      behaviorPrompt: "A careful argument cartographer.",
      traitChoiceSeed: 0,
    };
    const firstTraitMarkup = renderCogBuilderPage(draft, false, false, undefined, "defensiveTrait");
    const secondTraitMarkup = renderCogBuilderPage(draft, false, false, undefined, "activeTrait");

    expect(firstTraitMarkup).toContain("Trait 1");
    expect(firstTraitMarkup).toContain("Forceful");
    expect(firstTraitMarkup).not.toContain("Defense");
    expect(firstTraitMarkup).not.toContain("Offense");
    expect(secondTraitMarkup).toContain("Trait 2");
    expect(secondTraitMarkup).toContain("Stubborn");
    expect(secondTraitMarkup).not.toContain("Defense");
    expect(secondTraitMarkup).not.toContain("Offense");
  });

  it("keeps top traits aligned with the selected draft traits without showing rolling frames", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      activeTrait: "passionate" as const,
      appearanceDescription: "A careful argument cartographer with brass trim.",
      behaviorPrompt: "A careful argument cartographer.",
      defensiveTrait: "stubborn" as const,
      name: "Ada",
    };
    const previewDraft = {
      ...createInitialBuilderDraft(),
      activeTrait: "bandwagoner" as const,
      defensiveTrait: "bandwagoner" as const,
      personalGoal: undefined,
      appearanceDescription: "A careful argument cartographer with brass trim.",
      behaviorPrompt: "A careful argument cartographer.",
      name: "Ada",
    };

    const markup = renderCogBuilderPage(
      draft,
      false,
      false,
      undefined,
      "defensiveTrait",
      { kind: "defensiveTrait", value: "insular" },
      undefined,
      previewDraft,
    );
    const aside = builderProfileAside(markup);

    expect(aside).toContain('class="builder-profile-traits"');
    expect(aside).toContain("<strong>Stubborn</strong>");
    expect(aside).toContain("<strong>Passionate</strong>");
    expect(aside).not.toContain("Bandwagoner");
    expect(aside).not.toContain('class="builder-profile-trait is-rolling"');
  });

  it("starts trait choice steps with an autofilled selected option", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      name: "Ada",
      appearanceDescription: "A careful argument cartographer with brass trim.",
      behaviorPrompt: "A careful argument cartographer.",
    };

    for (const step of ["defensiveTrait", "activeTrait"] as const) {
      const markup = renderCogBuilderPage(draft, false, false, undefined, step);

      expect(markup).toContain("builder-choice-button is-selected");
      expect(markup).toContain('aria-pressed="true"');
      expect(markup).toMatch(/data-action="builder-next" type="button">Continue/);
    }
  });

  it("renders starter avatar choices for the autofilled profile", () => {
    const spriteStep = renderCogBuilderPage(createInitialBuilderDraft(), false, false, undefined, "appearance");

    expect(spriteStep).not.toContain('data-action="regenerate-builder-sprites"');
    expect(spriteStep).not.toContain(">?</strong>");
    expect(spriteStep).toContain("Custom");
    expect(spriteStep).not.toContain("data:image");
    expect(spriteStep).toContain('class="builder-sprite-option is-selected"');
    expect(spriteStep.match(/data-action="select-builder-sprite"/g)).toHaveLength(10);
    expect(spriteStep).not.toMatch(/<span>(Ada|Babbage|Mira|Default|Sprocket|Toggle)<\/span>/);
  });

  it("shows specific avatar generation failure details in the builder", () => {
    const markup = renderCogBuilderPage(
      { ...createInitialBuilderDraft(), customSpriteOpen: true },
      false,
      false,
      "503 Service Unavailable Avatar generation failed",
      "appearance",
    );

    expect(markup).toContain("503 Service Unavailable Avatar generation failed");
    expect(markup).toContain('class="builder-sprite-status is-error"');
  });

  it("disables sprite regeneration while generation is running", () => {
    const markup = renderCogBuilderPage(
      { ...createInitialBuilderDraft(), customSpriteOpen: true },
      false,
      true,
      undefined,
      "appearance",
    );

    expect(markup).toContain('data-action="regenerate-builder-sprites"');
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("builder-sprite-option-custom is-custom-open is-generating");
    expect(markup).toContain("disabled");
    expect(markup).toContain("Generating...");
  });

  it("escapes builder markup while preserving builder trait actions", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      name: '<Cog & "One">',
      behaviorPrompt: "<script>alert(1)</script>",
      appearanceDescription: "<script>alert(2)</script>",
      sprites: [{ key: "sprite", label: "<sprite>", url: "/assets/cogshambo/sprite-sheets/test/frames/test-01.png" }],
    };

    const markup = renderCogBuilderPage(draft, false, false, undefined, "defensiveTrait");

    expect(markup).toContain("&lt;Cog &amp; &quot;One&quot;&gt;");
    expect(markup).toContain("&lt;script&gt;alert(2)&lt;/script&gt;");
    expect(markup).not.toContain("<script>alert(2)</script>");
    expect(markup).toContain('data-action="set-builder-trait"');
  });

  it("previews neutral sprites even when generated sprites include team variants", () => {
    const draft = {
      ...createInitialBuilderDraft(),
      sprites: [
        {
          key: "sprite",
          label: "Sprite",
          url: "/assets/cogshambo/sprite-sheets/test/frames/test-01.png",
          spriteUrls: {
            red: "/assets/cogshambo/sprite-sheets/test/frames/test-01-red.png",
            blue: "/assets/cogshambo/sprite-sheets/test/frames/test-01-blue.png",
          },
        },
      ],
    };

    const markup = renderCogBuilderPage(draft, false, false, undefined, "appearance");

    expect(markup).toContain('src="/assets/cogshambo/sprite-sheets/test/frames/test-01.png"');
    expect(markup).not.toContain('src="/assets/cogshambo/sprite-sheets/test/frames/test-01-red.png"');
    expect(markup).not.toContain('src="/assets/cogshambo/sprite-sheets/test/frames/test-01-blue.png"');
    expect(markup).toContain('data-action="open-builder-custom-sprite"');
    expect(markup).toContain("Custom");
  });

  it("marks older sprite generation requests as stale after a newer request starts", () => {
    const guard = new LatestRequestGuard();
    const first = guard.next();
    const second = guard.next();

    expect(guard.isCurrent(first)).toBe(false);
    expect(guard.isCurrent(second)).toBe(true);
  });
});
