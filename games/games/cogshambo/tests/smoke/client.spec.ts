import { expect, type Locator, type Page, test } from "@playwright/test";

type SmokePosition = {
  x: number;
  y: number;
};

type SmokeSnapshot = {
  tick: number;
  dimensions: { width: number; height: number };
  venue?: {
    rooms: Array<{
      id: string;
      label: string;
      spotIds: string[];
      neighborIds: string[];
    }>;
    spots: Array<{
      id: string;
      roomId: string;
      label: string;
      position: SmokePosition;
      role?: "speaker" | "audience";
    }>;
  };
  cogs: Array<{
    id: string;
    name: string;
    position: SmokePosition;
    conversationLog?: unknown[];
    location?: {
      roomId: string;
      spotId: string;
    };
    debate?: unknown;
    moving?: {
      from: {
        roomId: string;
        spotId: string;
      };
      to: {
        roomId: string;
        spotId: string;
      };
    };
  }>;
  objects: Array<{
    type: string;
    position: SmokePosition;
  }>;
  terrain: Array<{
    terrain: string;
    position: SmokePosition;
  }>;
};

type KeyboardMoveTarget = {
  cog: SmokeSnapshot["cogs"][number];
  expectedPosition: SmokePosition;
  key: string;
};

type ExpandedRosterCog = {
  cogId: string;
  panel: Locator;
};

test("boots the client shell and receives server snapshots", async ({ page }) => {
  await installWebGpuDrawProbe(page);
  await page.goto("/");

  const canvas = page.locator("#world-canvas");
  const bubbles = page.locator("#world-bubbles");
  const hud = page.locator("#hud");
  const roster = page.locator(".cogs-panel");

  await expect(canvas).toBeVisible();
  await expect(bubbles).toBeVisible();
  await expectServerFedHud(hud);
  await expect(page.locator(".hud-panel")).toHaveCount(0);
  await expectDedicatedRightPanel(canvas, roster);
  await expectBoardRendererDraws(page);
});

test("secondary screens mount as standalone routes without the main HUD socket", async ({ page }) => {
  const websocketUrls = collectWebSocketUrls(page);
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  const cog = snapshot.cogs[0];
  if (!cog) {
    throw new Error("Expected at least one cog in the smoke world");
  }

  await page.goto("/builder");
  await expectStandaloneRoute(page);
  await expect(page.locator(".cog-builder-page")).toBeVisible();

  await page.goto("/config");
  await expectStandaloneRoute(page);
  await expect(page.locator(".config-page")).toBeVisible();

  await page.goto(`/profile/${encodeURIComponent(cog.id)}`);
  await expectStandaloneRoute(page);
  await expect(page.locator(`.cog-profile-page[data-cog-id="${cog.id}"]`)).toBeVisible();
  expect(websocketUrls).toEqual([]);
});

test("pulls the standalone profile down to refresh", async ({ page }) => {
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  const cog = snapshot.cogs[0];
  if (!cog) {
    throw new Error("Expected at least one cog in the smoke world");
  }

  let worldRequests = 0;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/world" && request.method() === "GET") {
      worldRequests += 1;
    }
  });

  await page.goto(`/profile/${encodeURIComponent(cog.id)}`);
  await expectStandaloneRoute(page);
  const profile = page.locator(`.cog-profile-page[data-cog-id="${cog.id}"]`);
  const scroll = profile.locator(".cog-profile-scroll");
  await expect(profile).toBeVisible();
  await expect(profile.locator(".profile-pull-refresh")).toBeAttached();
  await scroll.evaluate((element) => {
    element.scrollTop = 0;
  });
  const loadedWorldRequests = worldRequests;
  const box = await scroll.boundingBox();
  if (!box) {
    throw new Error("Expected profile scroll bounds");
  }

  const x = box.x + box.width / 2;
  const startY = box.y + 18;
  await page.dispatchEvent(".cog-profile-scroll", "pointerdown", {
    bubbles: true,
    button: 0,
    buttons: 1,
    cancelable: true,
    clientX: x,
    clientY: startY,
    isPrimary: true,
    pointerId: 13,
    pointerType: "touch",
  });
  await page.dispatchEvent(".cog-profile-scroll", "pointermove", {
    bubbles: true,
    buttons: 1,
    cancelable: true,
    clientX: x,
    clientY: startY + 130,
    isPrimary: true,
    pointerId: 13,
    pointerType: "touch",
  });
  await expect(profile).toHaveAttribute("data-pull-refresh-state", "ready");

  const refreshed = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/world" &&
      response.request().method() === "GET" &&
      response.ok(),
  );
  await page.dispatchEvent(".cog-profile-scroll", "pointerup", {
    bubbles: true,
    button: 0,
    buttons: 0,
    cancelable: true,
    clientX: x,
    clientY: startY + 130,
    isPrimary: true,
    pointerId: 13,
    pointerType: "touch",
  });

  await refreshed;
  await expect.poll(() => worldRequests).toBeGreaterThan(loadedWorldRequests);
  await expect(profile).toBeVisible();
  await expect.poll(async () => profile.getAttribute("data-pull-refresh-state")).toBeNull();
});

test("builder barcode redirects returning devices to their cog profile", async ({ page }) => {
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  const cog = snapshot.cogs[0];
  if (!cog) {
    throw new Error("Expected at least one cog in the smoke world");
  }

  await page.goto("/");
  await page.evaluate((cogId) => {
    document.cookie = `cogshambo_cog_id=${encodeURIComponent(cogId)}; path=/; SameSite=Lax`;
  }, cog.id);

  await page.goto("/builder");
  await expectStandaloneRoute(page);
  await expect(page.locator(`.cog-profile-page[data-cog-id="${cog.id}"]`)).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(`/profile/${encodeURIComponent(cog.id)}`);
});

test("profile abandon clears the returning-device cookie and returns to the creator without kicking the cog", async ({ page }) => {
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  const cog = snapshot.cogs[0];
  if (!cog) {
    throw new Error("Expected at least one cog in the smoke world");
  }

  await page.goto("/");
  await page.evaluate((cogId) => {
    document.cookie = `cogshambo_cog_id=${encodeURIComponent(cogId)}; path=/; SameSite=Lax`;
  }, cog.id);

  await page.goto(`/profile/${encodeURIComponent(cog.id)}`);
  await expectStandaloneRoute(page);
  const profile = page.locator(`.cog-profile-page[data-cog-id="${cog.id}"]`);
  await expect(profile).toBeVisible();

  await profile.getByRole("button", { name: "Abandon" }).click();

  await expect(page).toHaveURL("/builder");
  await expect(page.locator(".cog-builder-page")).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.cookie)).not.toContain("cogshambo_cog_id=");
  const after = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  expect(after.cogs.some((candidate) => candidate.id === cog.id)).toBe(true);
});

test("shows action bubbles over debating cogs", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const roster = page.locator(".cogs-panel");
  const bubbles = page.locator("[data-debate-bubble]");

  await expect(hud).toBeVisible();
  await expect(roster).toBeVisible();
  await expect.poll(() => roster.locator(".cog-row").count(), { timeout: 10_000 }).toBeGreaterThan(0);
  await expect.poll(() => bubbles.count(), { timeout: 15_000 }).toBeGreaterThanOrEqual(1);
  await expect(bubbles.first().locator(".debate-action-circle")).toHaveCount(2);
  await expect(bubbles.first().locator(".debate-action-placeholder")).toHaveCount(2);
  await expect(bubbles.first().locator(".debate-action-circle").first()).toHaveAttribute(
    "data-debate-action",
    /pending|reason|spin|passion/,
  );
  await expect(bubbles.first().locator("[data-debate-bubble-halo]")).toHaveCount(0);
  await expect(page.locator("[data-debate-bubble-links]").first().locator("[data-debate-bubble-link]")).toHaveCount(2);
  await expect(bubbles.first().locator(".debate-winner")).toHaveCount(0);
  await expectOverlayItemOverMap(page.locator("#world-canvas"), bubbles.first());
});

test("renders cog name labels over the map", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const labels = page.locator("[data-cog-name-label]");

  await expectServerFedHud(hud);
  await expect.poll(() => labels.count(), { timeout: 10_000 }).toBeGreaterThan(0);
  await expect(labels.filter({ hasText: "Ada" })).toBeVisible();
  await expect(labels.filter({ hasText: "Babbage" })).toBeVisible();
  await expectOverlayItemOverMap(page.locator("#world-canvas"), labels.first());
});

test("conversion team flip animation can resume from the conversion event age", async ({ page }) => {
  await page.goto("/");

  const bubbles = page.locator("#world-bubbles");
  await expect(bubbles).toBeVisible();
  await bubbles.evaluate((element) => {
    element.innerHTML = `
      <div class="conversion-bubble conversion-bubble-from-blue conversion-bubble-to-red" data-conversion-bubble style="--conversion-age-ms: -1000ms;">
        <span class="conversion-team-wave" aria-hidden="true"></span>
        <span class="conversion-token" aria-hidden="true">
          <span class="conversion-old-color"></span>
          <span class="conversion-new-color"></span>
          <span class="conversion-split-line"></span>
        </span>
        <span class="conversion-team-stamp" aria-hidden="true">RED</span>
      </div>
    `;
  });

  await expect.poll(() => page.locator(".conversion-token").evaluate((element) => getComputedStyle(element).animationDelay)).toBe("-1s");
  await expect(page.locator(".conversion-impact-row")).toHaveCount(0);
});

test("settings page separates params traits and achievements into tabs", async ({ page }) => {
  await page.goto("/config");

  await expectStandaloneRoute(page);
  await expect(page.locator("[data-settings-preset-select]")).toHaveCount(0);
  await expect(page.locator("[data-settings-preset-choice]").first()).toBeVisible();
  await expect(page.locator(".builder-qr-card")).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Params" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Timing" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Traits" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Achievements" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Venue" })).toBeVisible();

  await expect(page.getByRole("tabpanel", { name: "Params" })).toBeVisible();
  await expect(page.getByRole("tabpanel", { name: "Traits" })).toBeHidden();
  await expect(page.getByRole("tabpanel", { name: "Achievements" })).toBeHidden();

  await page.getByRole("tab", { name: "Traits" }).click();
  await expect(page.getByRole("tabpanel", { name: "Params" })).toBeHidden();
  await expect(page.getByRole("tabpanel", { name: "Traits" })).toBeVisible();
  await expect(page.getByRole("tabpanel", { name: "Traits" })).toContainText("Stubborn");

  await page.getByRole("tab", { name: "Achievements" }).click();
  await expect(page.getByRole("tabpanel", { name: "Traits" })).toBeHidden();
  await expect(page.getByRole("tabpanel", { name: "Achievements" })).toBeVisible();
  await expect(page.getByRole("tabpanel", { name: "Achievements" })).toContainText("Debate Three Opponents");

  await page.getByRole("tab", { name: "Venue" }).click();
  await expect(page.getByRole("tabpanel", { name: "Venue" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Venue Editor" })).toBeVisible();
  await expect(page.locator(".venue-editor-image")).toBeVisible();

  const startingTick = await readWorldTick(page);
  const stageRoom = page.locator("[data-room-id='stage']");
  await stageRoom.click();
  await expect(page.locator(".venue-editor")).toContainText("1 room selected");
  await expect.poll(async () => readWorldTick(page), { timeout: 5_000 }).toBeGreaterThan(startingTick);
  await expect(stageRoom).toHaveClass(/is-selected/);
  await expect(page.locator("[data-spot-id='stage_host']")).toBeVisible();
});

test("keeps settings control focus while standalone config saves", async ({ page }) => {
  await page.goto("/config");

  await expectStandaloneRoute(page);

  await page.getByRole("tab", { name: "Traits" }).click();
  const traitInput = page.locator("[data-trait-config-id='contrarian'][data-trait-config-key='overwhelmingTeamThreshold']");
  await traitInput.fill("0.95");
  await expect(traitInput).toBeFocused();

  const saveResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/config") && response.request().method() === "PATCH",
  );
  await traitInput.evaluate((element) => element.dispatchEvent(new Event("change", { bubbles: true })));
  await expect((await saveResponse).ok()).toBe(true);
  await expect(traitInput).toBeFocused();
  await expect(traitInput).toHaveValue("0.35");
});

test("keeps every settings tab scroll, state, and focus on the standalone route", async ({ page }) => {
  await page.setViewportSize({ width: 1180, height: 520 });
  await page.goto("/config");

  await expectStandaloneRoute(page);
  const settingsScroll = page.locator(".config-page-scroll");
  await expect(settingsScroll).toBeVisible();

  for (const target of [
    { name: "Params", focusSelector: "[data-config-key='debateDoubt']", value: "37" },
    { name: "Timing", focusSelector: "[data-config-seconds-key='debatePrepTicks']", value: "1.5" },
    {
      name: "Traits",
      focusSelector: "[data-trait-config-id='contrarian'][data-trait-config-key='overwhelmingTeamThreshold']",
      value: "0.85",
    },
    { name: "Achievements", focusSelector: "[data-config-tab='achievements']" },
    { name: "Debates", focusSelector: "[data-config-tab='debates']" },
    { name: "Venue", focusSelector: "[data-config-tab='venue']" },
  ]) {
    await page.getByRole("tab", { name: target.name }).click();
    await expect(page.getByRole("tabpanel", { name: target.name })).toBeVisible();

    const focused = page.locator(target.focusSelector);
    if (target.value) {
      await focused.fill(target.value);
      await expect(focused).toHaveValue(target.value);
    } else {
      await focused.focus();
    }
    await expect(focused).toBeFocused();

    const scrollBefore = await settingsScroll.evaluate((element) => {
      element.scrollTop = Math.min(180, Math.max(0, element.scrollHeight - element.clientHeight));
      element.scrollLeft = 0;
      return element.scrollTop;
    });
    const startingTick = await readWorldTick(page);

    await expect.poll(async () => readWorldTick(page), { timeout: 5_000 }).toBeGreaterThan(startingTick);

    await expect(page.getByRole("tabpanel", { name: target.name })).toBeVisible();
    await expect(focused).toBeFocused();
    if (target.value) {
      await expect(focused).toHaveValue(target.value);
    }
    await expect.poll(() => settingsScroll.evaluate((element) => element.scrollTop), { timeout: 5_000 }).toBeGreaterThanOrEqual(
      scrollBefore - 1,
    );
  }
});

test("edits spots inside a room editor and autosaves the editor state", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  await expect(editor).toBeVisible();
  await expect(page.getByRole("heading", { name: "Venue Editor" })).toBeVisible();
  await expect(page.locator(".venue-editor-image")).toBeVisible();

  await expect(page.locator("[data-room-id='stage']")).toBeVisible();
  await expect(page.locator("[data-spot-id='stage_host']")).toHaveCount(0);
  await page.locator("[data-room-id='stage']").dblclick();
  await expect(page.getByRole("heading", { name: "Room Editor" })).toBeVisible();
  await expect(editor).toContainText("Main Stage");
  await expect(page.getByRole("button", { name: "Save", exact: true })).toHaveCount(0);

  const stageHost = page.locator("[data-spot-id='stage_host']");
  const stageGuest = page.locator("[data-spot-id='stage_guest']");
  await expect(stageHost).toBeVisible();
  await expect(stageGuest).toBeVisible();

  await stageHost.click();
  await stageGuest.click({ modifiers: ["Shift"] });
  await expect(editor).toContainText("2 spots selected");

  await page.keyboard.press("Meta+C");
  const copiedHosts = page.locator("[data-spot-id^='stage_host_copy_']");
  const copiedHostCount = await copiedHosts.count();
  const pasteAutosave = waitForVenueEditorAutosave(page);
  await page.keyboard.press("Meta+V");
  await expect((await pasteAutosave).ok()).toBe(true);
  await expect(editor).toContainText("Saved");
  await expect.poll(() => copiedHosts.count()).toBeGreaterThan(copiedHostCount);
  const copiedHost = copiedHosts.nth(copiedHostCount);
  await expect(copiedHost).toBeVisible();

  const beforeDrag = await copiedHost.getAttribute("data-position");
  const beforeDragPosition = parseSpotPosition(beforeDrag);
  const venueState = await (await page.request.get("/api/venue-editor")).json() as {
    state: { dimensions: { width: number; height: number } };
  };
  const copiedHostBox = await copiedHost.boundingBox();
  if (!copiedHostBox) {
    throw new Error("Expected copied spot bounding box");
  }
  await page.mouse.move(copiedHostBox.x + copiedHostBox.width / 2, copiedHostBox.y + copiedHostBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(copiedHostBox.x + copiedHostBox.width / 2 - 70, copiedHostBox.y + copiedHostBox.height / 2 + 40, {
    steps: 5,
  });
  const dragAutosave = waitForVenueEditorAutosave(page);
  await page.mouse.up();
  await expect((await dragAutosave).ok()).toBe(true);
  await expect.poll(() => copiedHost.getAttribute("data-position")).not.toBe(beforeDrag);
  const afterDragPosition = parseSpotPosition(await copiedHost.getAttribute("data-position"));
  expect(afterDragPosition.x).toBeLessThan(beforeDragPosition.x);
  expect(afterDragPosition.y).toBeGreaterThan(beforeDragPosition.y);
  expect(afterDragPosition.x).toBeGreaterThan(0);
  expect(afterDragPosition.x).toBeLessThan(venueState.state.dimensions.width - 1);
  expect(afterDragPosition.y).toBeLessThan(venueState.state.dimensions.height - 1);
  await expect(editor).toContainText("Saved");
});

test("uses the full venue editor window without a right inspector pane", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  const shell = page.locator("[data-board-shell]");
  await expect(editor).toBeVisible();
  await expect(shell).toBeVisible();
  await expect(page.locator(".venue-editor-inspector")).toHaveCount(0);
  await expect(page.locator("[data-room-id='stage']")).toBeVisible();
  await expect(page.locator("[data-spot-id='stage_host']")).toHaveCount(0);
  await expect(page.locator("[data-room-path]")).not.toHaveCount(0);

  const viewport = page.viewportSize();
  const shellBox = await shell.boundingBox();
  if (!viewport || !shellBox) {
    throw new Error("Expected venue editor viewport and board shell boxes");
  }

  expect(shellBox.width).toBeGreaterThan(viewport.width - 80);
});

test("toggles venue editor spot mode and drags all spots", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  const roomMode = page.getByRole("button", { name: "Room Mode" });
  const spotMode = page.getByRole("button", { name: "Spot Mode" });
  const stageHost = page.locator("[data-spot-id='stage_host']");
  const greenRoomSofa = page.locator("[data-spot-id='green_room_sofa']");

  await expect(editor).toBeVisible();
  await expect(roomMode).toHaveAttribute("aria-pressed", "true");
  await expect(spotMode).toHaveAttribute("aria-pressed", "false");
  await expect(stageHost).toHaveCount(0);

  await spotMode.click();

  await expect(spotMode).toHaveAttribute("aria-pressed", "true");
  await expect(roomMode).toHaveAttribute("aria-pressed", "false");
  await expect(stageHost).toBeVisible();
  await expect(greenRoomSofa).toBeVisible();

  const beforeDrag = await stageHost.getAttribute("data-position");
  const spotBox = await stageHost.boundingBox();
  if (!spotBox) {
    throw new Error("Expected stage host spot bounding box");
  }

  await page.mouse.move(spotBox.x + spotBox.width / 2, spotBox.y + spotBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(spotBox.x + spotBox.width / 2 + 24, spotBox.y + spotBox.height / 2 - 18, { steps: 5 });
  const autosaveResponse = waitForVenueEditorAutosave(page);
  await page.mouse.up();
  await expect((await autosaveResponse).ok()).toBe(true);
  await expect.poll(() => stageHost.getAttribute("data-position")).not.toBe(beforeDrag);
  await expect(editor).toContainText("Saved");
  await expect(page.getByRole("heading", { name: "Venue Editor" })).toBeVisible();

  await roomMode.click();

  await expect(roomMode).toHaveAttribute("aria-pressed", "true");
  await expect(stageHost).toHaveCount(0);
});

test("toggles venue editor path mode and prioritizes room paths", async ({ page }) => {
  await page.goto("/venue-editor");

  const roomMode = page.getByRole("button", { name: "Room Mode" });
  const spotMode = page.getByRole("button", { name: "Spot Mode" });
  const pathMode = page.getByRole("button", { name: "Path Mode" });
  const stageRoom = page.locator("[data-room-id='stage']");
  const stageHost = page.locator("[data-spot-id='stage_host']");
  const stageConnectHandle = page.locator("[data-path-connect-room-id='stage']");
  const pathHitTarget = page.locator("[data-room-path-hit='green_room__stage']");
  const selectedPathPanel = page.locator("[data-selected-path-panel]");

  await expect(roomMode).toHaveAttribute("aria-pressed", "true");
  await expect(spotMode).toHaveAttribute("aria-pressed", "false");
  await expect(pathMode).toHaveAttribute("aria-pressed", "false");

  await pathMode.click();

  await expect(pathMode).toHaveAttribute("aria-pressed", "true");
  await expect(roomMode).toHaveAttribute("aria-pressed", "false");
  await expect(spotMode).toHaveAttribute("aria-pressed", "false");
  await expect(stageHost).toHaveCount(0);
  await expect(stageConnectHandle).toBeVisible();

  await stageRoom.click();
  await expect(page.locator("[data-selected-room-panel]")).toHaveCount(0);

  await pathHitTarget.click();
  await expect(selectedPathPanel).toBeVisible();
  await expect(selectedPathPanel).toContainText("Green Room");
  await expect(selectedPathPanel).toContainText("Main Stage");
  await expect(page.locator("[data-selected-room-panel]")).toHaveCount(0);
});

test("colors spot mode spots outside their assigned room red", async ({ page }) => {
  await page.goto("/venue-editor");

  const response = await page.request.get("/api/venue-editor");
  const body = await response.json() as {
    state: {
      updatedAt?: string;
      dimensions: { width: number; height: number };
      rooms: Array<{ id: string; rect?: { x: number; y: number; width: number; height: number } }>;
      spots: Array<{ id: string; roomId: string; label: string; position: SmokePosition }>;
      links: Array<{ id: string; fromSpotId: string; toSpotId: string }>;
      paths: Array<{ id: string; fromRoomId: string; toRoomId: string; points: SmokePosition[] }>;
    };
  };
  const outsidePosition = findPositionOutsideRoomRects(body.state.rooms, body.state.dimensions);
  const { updatedAt: _updatedAt, ...state } = body.state;
  const saveResponse = await page.request.put("/api/venue-editor", {
    data: {
      ...state,
      spots: state.spots.map((spot) =>
        spot.id === "stage_host"
          ? { ...spot, position: outsidePosition }
          : spot,
      ),
    },
  });
  expect(saveResponse.ok()).toBe(true);

  await page.reload();
  await page.getByRole("button", { name: "Spot Mode" }).click();

  const stageHost = page.locator("[data-spot-id='stage_host']");
  const stageGuest = page.locator("[data-spot-id='stage_guest']");
  await expect(stageHost).toBeVisible();
  await expect(stageHost).toHaveClass(/is-room-mismatch/);
  await expect(stageHost).toHaveCSS("background-color", "rgb(194, 36, 36)");
  await expect(stageGuest).not.toHaveClass(/is-room-mismatch/);

  const restoreResponse = await page.request.put("/api/venue-editor", { data: state });
  expect(restoreResponse.ok()).toBe(true);
});

test("enters and exits a room editor with escape", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  await page.locator("[data-room-id='green_room']").dblclick();
  await expect(page.getByRole("heading", { name: "Room Editor" })).toBeVisible();
  await expect(editor).toContainText("Green Room");
  await expect(page.locator("[data-spot-id='green_room_sofa']")).toBeVisible();
  await expect(page.locator("[data-spot-id='stage_host']")).toHaveCount(0);

  await page.keyboard.press("Escape");

  await expect(page.getByRole("heading", { name: "Venue Editor" })).toBeVisible();
  await expect(editor).toContainText("No room selected");
  await expect(page.locator("[data-room-id='green_room']")).toBeVisible();
  await expect(page.locator("[data-selected-room-panel]")).toHaveCount(0);
  await expect(page.locator("[data-spot-id='green_room_sofa']")).toHaveCount(0);
  await expect(page.locator("[data-room-path]")).not.toHaveCount(0);
});

test("escape clears selected venue items back to room view", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  const stageRoom = page.locator("[data-room-id='stage']");
  const stageHost = page.locator("[data-spot-id='stage_host']");
  const path = page.locator("[data-room-path='green_room__stage']");
  await expect(stageRoom).toBeVisible();
  await stageRoom.click();
  await expect(stageRoom).toHaveClass(/is-selected/);
  await expect(page.locator("[data-selected-room-panel]")).toBeVisible();
  await expect(stageHost).toBeVisible();

  await page.keyboard.press("Escape");

  await expect(editor).toContainText("No room selected");
  await expect(stageRoom).not.toHaveClass(/is-selected/);
  await expect(page.locator("[data-selected-room-panel]")).toHaveCount(0);
  await expect(stageHost).toHaveCount(0);
  await expect(page.locator("[data-room-path]")).not.toHaveCount(0);

  await page.locator("[data-room-path-hit='green_room__stage']").click();
  await expect(path).toHaveClass(/is-editing/);

  await page.keyboard.press("Escape");

  await expect(editor).toContainText("No room selected");
  await expect(path).not.toHaveClass(/is-editing/);
  await expect(page.locator("[data-path-point-index]")).toHaveCount(0);
  await expect(page.locator("[data-room-path]")).not.toHaveCount(0);
});

test("creates a new room from room mode", async ({ page }) => {
  await page.goto("/venue-editor");

  const createRoomButton = page.getByRole("button", { name: "Create Room" });
  const roomMode = page.getByRole("button", { name: "Room Mode" });
  const spotMode = page.getByRole("button", { name: "Spot Mode" });
  const roomCountBefore = await page.locator("[data-room-id]").count();

  await expect(roomMode).toHaveAttribute("aria-pressed", "true");
  await expect(createRoomButton).toBeVisible();

  const autosaveResponse = waitForVenueEditorAutosave(page);
  await createRoomButton.click();
  await expect((await autosaveResponse).ok()).toBe(true);

  const createdRoom = page.locator("[data-room-id='new_room']");
  const panel = page.locator("[data-selected-room-panel]");
  await expect(createdRoom).toBeVisible();
  await expect(createdRoom).toHaveClass(/is-selected/);
  await expect(page.locator("[data-room-id]")).toHaveCount(roomCountBefore + 1);
  await expect(panel).toBeVisible();
  await expect(panel.locator("[data-room-name-input]")).toHaveValue("New Room");
  await expect(panel).toContainText("0 spots");
  await expect(panel.getByRole("button", { name: "Add Spot" })).toBeVisible();

  const venueState = await (await page.request.get("/api/venue-editor")).json() as {
    state: { rooms: NonNullable<SmokeSnapshot["venue"]>["rooms"] };
  };
  expect(venueState.state.rooms).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ id: "new_room", label: "New Room", spotIds: [], neighborIds: [] }),
    ]),
  );

  await spotMode.click();
  await expect(createRoomButton).toHaveCount(0);
});

test("creates a new room at the current mouse pointer with command-n", async ({ page }) => {
  await page.goto("/venue-editor");

  const boardPosition = { x: 18, y: 6 };
  const beforeState = await (await page.request.get("/api/venue-editor")).json() as {
    state: {
      dimensions: { width: number; height: number };
      rooms: Array<{ id: string; rect?: { x: number; y: number; width: number; height: number } }>;
    };
  };
  const roomCountBefore = beforeState.state.rooms.length;
  await moveVenueBoardPosition(page, boardPosition, beforeState.state.dimensions);

  const autosaveResponse = waitForVenueEditorAutosave(page);
  await page.keyboard.press("Meta+N");
  await expect((await autosaveResponse).ok()).toBe(true);

  const createdRoom = page.locator("[data-room-id='new_room']");
  await expect(createdRoom).toBeVisible();
  await expect(createdRoom).toHaveClass(/is-selected/);
  await expect(createdRoom).toHaveAttribute("data-rect", "14,3.5,8,5");
  await expect(page.locator("[data-selected-room-panel] [data-connected-room-id]")).toHaveCount(4);
  await expect(page.locator("[data-spot-id^='new_room_spot_']")).toHaveCount(3);
  await expect(page.locator("[data-spot-id^='new_room_spot_'][data-spot-role='speaker']")).toHaveCount(3);
  await expect(page.locator("[data-selected-room-panel]")).toContainText("3 spots");
  await expect(page.locator("[data-selected-room-panel]")).toContainText("3 participants");

  const venueState = await (await page.request.get("/api/venue-editor")).json() as {
    state: {
      rooms: Array<{
        id: string;
        neighborIds: string[];
        spotIds: string[];
        rect?: { x: number; y: number; width: number; height: number };
      }>;
      spots: Array<{ id: string; roomId: string; role?: "speaker" | "audience" }>;
      paths: Array<{ fromRoomId: string; toRoomId: string }>;
    };
  };
  const newRoom = venueState.state.rooms.find((room) => room.id === "new_room");
  const newRoomSpots = venueState.state.spots.filter((spot) => spot.roomId === "new_room");
  expect(venueState.state.rooms).toHaveLength(roomCountBefore + 1);
  expect(newRoom?.rect).toEqual({
    x: 14,
    y: 3.5,
    width: 8,
    height: 5,
  });
  expect(newRoom?.spotIds).toEqual(["new_room_spot_1", "new_room_spot_2", "new_room_spot_3"]);
  expect(newRoomSpots.map((spot) => spot.role)).toEqual(["speaker", "speaker", "speaker"]);
  expect(newRoom?.neighborIds).toHaveLength(4);
  expect(venueState.state.paths.filter((path) => path.fromRoomId === "new_room" || path.toRoomId === "new_room")).toHaveLength(4);
});

test("toggles selected room spots between Participant and Audience with command-s", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  await page.locator("[data-room-id='stage']").dblclick();
  const stageHost = page.locator("[data-spot-id='stage_host']");
  const stageGuest = page.locator("[data-spot-id='stage_guest']");

  await stageHost.click();
  await stageGuest.click({ modifiers: ["Shift"] });
  await expect(editor).toContainText("2 spots selected");

  const audienceAutosave = waitForVenueEditorAutosave(page);
  await page.keyboard.press("Meta+S");
  await expect((await audienceAutosave).ok()).toBe(true);
  await expect(stageHost).toHaveAttribute("data-spot-role", "audience");
  await expect(stageGuest).toHaveAttribute("data-spot-role", "audience");
  await expect(stageHost).toHaveText("A");
  await expect(stageGuest).toHaveText("A");

  const audienceState = await (await page.request.get("/api/venue-editor")).json() as {
    state: { spots: NonNullable<SmokeSnapshot["venue"]>["spots"]; links: Array<{ id: string }> };
  };
  expect(audienceState.state.links).toEqual([]);
  expect(audienceState.state.spots.find((spot) => spot.id === "stage_host")?.role).toBe("audience");
  expect(audienceState.state.spots.find((spot) => spot.id === "stage_guest")?.role).toBe("audience");

  const speakerAutosave = waitForVenueEditorAutosave(page);
  await page.keyboard.press("Meta+S");
  await expect((await speakerAutosave).ok()).toBe(true);
  await expect(stageHost).toHaveAttribute("data-spot-role", "speaker");
  await expect(stageGuest).toHaveAttribute("data-spot-role", "speaker");
  await expect(stageHost).toHaveText("");
  await expect(stageGuest).toHaveText("");
});

test("double-click toggles the clicked room spot between Participant and Audience", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  await page.locator("[data-room-id='stage']").dblclick();
  const stageHost = page.locator("[data-spot-id='stage_host']");
  const stageGuest = page.locator("[data-spot-id='stage_guest']");
  await expect(stageHost).toBeVisible();
  await expect(stageGuest).toBeVisible();

  const audienceAutosave = waitForVenueEditorAutosave(page);
  await stageHost.dblclick();
  await expect((await audienceAutosave).ok()).toBe(true);

  await expect(editor).toContainText("1 spot selected");
  await expect(stageHost).toHaveClass(/is-selected/);
  await expect(stageHost).toHaveAttribute("data-spot-role", "audience");
  await expect(stageHost).toHaveAttribute("aria-label", "stage_host Audience");
  await expect(stageHost).toHaveAttribute("title", "stage_host (Audience)");
  await expect(stageHost).toHaveText("A");
  await expect(stageGuest).toHaveAttribute("data-spot-role", "speaker");
  await expect(stageGuest).not.toHaveClass(/is-selected/);

  const participantAutosave = waitForVenueEditorAutosave(page);
  await stageHost.dblclick();
  await expect((await participantAutosave).ok()).toBe(true);
  await expect(stageHost).toHaveAttribute("data-spot-role", "speaker");
  await expect(stageHost).toHaveAttribute("aria-label", "stage_host Participant");
  await expect(stageHost).toHaveAttribute("title", "stage_host (Participant)");
  await expect(stageHost).toHaveText("");
  const participantState = await (await page.request.get("/api/venue-editor")).json() as {
    state: { spots: NonNullable<SmokeSnapshot["venue"]>["spots"] };
  };
  expect(participantState.state.spots.find((spot) => spot.id === "stage_host")?.role).toBe("speaker");
});

test("shows venue editor shortcuts and cuts selected spots with command-x", async ({ page }) => {
  await page.goto("/venue-editor");

  const shortcuts = page.locator("[aria-label='Venue editor shortcuts']");
  await expect(shortcuts).toContainText("Cmd-N");
  await expect(shortcuts).toContainText("Cmd-X");
  await expect(shortcuts).toContainText("Double-click on spot");
  await expect(shortcuts).toContainText("Participant/Audience");
  await expect(shortcuts).toContainText("Delete selection");

  await page.locator("[data-room-id='stage']").dblclick();
  const stageHost = page.locator("[data-spot-id='stage_host']");
  await stageHost.click();

  const cutAutosave = waitForVenueEditorAutosave(page);
  await page.keyboard.press("Meta+X");
  await expect((await cutAutosave).ok()).toBe(true);
  await expect(stageHost).toHaveCount(0);

  const pastedHosts = page.locator("[data-spot-id^='stage_host_copy_']");
  const pasteAutosave = waitForVenueEditorAutosave(page);
  await page.keyboard.press("Meta+V");
  await expect((await pasteAutosave).ok()).toBe(true);
  await expect(pastedHosts).toHaveCount(1);
});

test("moves and resizes venue room rectangles", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  const stageRoom = page.locator("[data-room-id='stage']");
  await expect(stageRoom).toBeVisible();
  await stageRoom.click();
  await expect(editor).toContainText("1 room selected");

  const rectBeforeDrag = await stageRoom.getAttribute("data-rect");
  const roomBox = await stageRoom.boundingBox();
  if (!roomBox) {
    throw new Error("Expected room rectangle bounding box");
  }
  await page.mouse.move(roomBox.x + roomBox.width / 2, roomBox.y + roomBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(roomBox.x + roomBox.width / 2 - 40, roomBox.y + roomBox.height / 2 + 30, { steps: 5 });
  const dragAutosave = waitForVenueEditorAutosave(page);
  await page.mouse.up();
  await expect((await dragAutosave).ok()).toBe(true);
  await expect.poll(() => stageRoom.getAttribute("data-rect")).not.toBe(rectBeforeDrag);
  await expect(editor).toContainText("Saved");

  const rectBeforeResize = await stageRoom.getAttribute("data-rect");
  const resizeHandle = page.locator("[data-room-resize-room-id='stage']");
  await expect(resizeHandle).toBeVisible();
  const handleBox = await resizeHandle.boundingBox();
  if (!handleBox) {
    throw new Error("Expected room resize handle");
  }
  await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(handleBox.x + handleBox.width / 2 + 35, handleBox.y + handleBox.height / 2 + 24, { steps: 5 });
  const resizeAutosave = waitForVenueEditorAutosave(page);
  await page.mouse.up();
  await expect((await resizeAutosave).ok()).toBe(true);
  await expect.poll(() => stageRoom.getAttribute("data-rect")).not.toBe(rectBeforeResize);
  await expect(editor).toContainText("Saved");
});

test("shows selected room controls and autosaves room edits", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  const stageRoom = page.locator("[data-room-id='stage']");
  await expect(stageRoom).toBeVisible();
  await stageRoom.click();

  const panel = page.locator("[data-selected-room-panel]");
  await expect(panel).toBeVisible();
  await expect(panel.locator("[data-room-name-input]")).toHaveValue("Main Stage");
  await expect(panel.getByRole("button", { name: "Edit Room" })).toHaveCount(0);
  await expect(panel.getByRole("button", { name: "Clear" })).toHaveCount(0);
  await expect(page.locator(".venue-editor-toolbar").getByRole("button", { name: "Clear" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toHaveCount(0);

  const rectBeforeDrag = await stageRoom.getAttribute("data-rect");
  const roomBox = await stageRoom.boundingBox();
  if (!roomBox) {
    throw new Error("Expected room rectangle bounding box");
  }
  await page.mouse.move(roomBox.x + 8, roomBox.y + 8);
  await page.mouse.down();
  await page.mouse.move(roomBox.x - 17, roomBox.y + 26, { steps: 5 });
  const autosaveResponse = waitForVenueEditorAutosave(page);
  await page.mouse.up();
  await expect((await autosaveResponse).ok()).toBe(true);
  await expect.poll(() => stageRoom.getAttribute("data-rect")).not.toBe(rectBeforeDrag);
  await expect(editor).toContainText("Saved");
});

test("edits selected room info and spots from the room panel", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  const stageRoom = page.locator("[data-room-id='stage']");
  const stageHost = page.locator("[data-spot-id='stage_host']");
  const stageGuest = page.locator("[data-spot-id='stage_guest']");
  await expect(stageRoom).toBeVisible();
  await stageRoom.click();

  const panel = page.locator("[data-selected-room-panel]");
  const roomName = panel.locator("[data-room-name-input]");
  await expect(panel).toBeVisible();
  await expect(roomName).toHaveValue("Main Stage");
  await expect(panel.locator("[data-room-panel-spots]")).toHaveCount(0);
  await expect(panel.locator("[data-room-panel-spot-id]")).toHaveCount(0);
  await expect(panel).not.toContainText("host mic");
  await expect(panel).not.toContainText("guest mic");
  await expect(stageHost).toBeVisible();
  await expect(stageGuest).toBeVisible();

  const renameAutosave = waitForVenueEditorAutosave(page);
  await roomName.fill("Main Stage Test");
  await expect(roomName).toBeFocused();
  await roomName.evaluate((element) => element.dispatchEvent(new Event("change", { bubbles: true })));
  await expect((await renameAutosave).ok()).toBe(true);
  await expect(roomName).toBeFocused();
  await expect(roomName).toHaveValue("Main Stage Test");

  const hostPositionBeforeDrag = await stageHost.getAttribute("data-position");
  const hostBox = await stageHost.boundingBox();
  if (!hostBox) {
    throw new Error("Expected stage host spot bounding box");
  }
  await page.mouse.move(hostBox.x + hostBox.width / 2, hostBox.y + hostBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(hostBox.x + hostBox.width / 2 + 22, hostBox.y + hostBox.height / 2 + 12, { steps: 5 });
  const dragAutosave = waitForVenueEditorAutosave(page);
  await page.mouse.up();
  await expect((await dragAutosave).ok()).toBe(true);
  await expect.poll(() => stageHost.getAttribute("data-position")).not.toBe(hostPositionBeforeDrag);

  const boardSpotCountBeforeAdd = await page.locator("[data-spot-id]").count();
  const addAutosave = waitForVenueEditorAutosave(page);
  await panel.getByRole("button", { name: "Add Spot" }).click();
  await expect((await addAutosave).ok()).toBe(true);
  await expect.poll(() => page.locator("[data-spot-id]").count()).toBeGreaterThan(boardSpotCountBeforeAdd);
  const addedSpot = page.locator("[data-spot-id^='stage_spot_']").first();
  await expect(addedSpot).toBeVisible();
  const addedSpotId = await addedSpot.getAttribute("data-spot-id");
  expect(addedSpotId).toBeTruthy();
  await expect(addedSpot).toHaveAttribute("aria-label", `${addedSpotId!} Participant`);
  await expect(addedSpot).toHaveAttribute("title", `${addedSpotId!} (Participant)`);
  await expect(addedSpot).toHaveText("");
  const venueStateAfterAdd = await (await page.request.get("/api/venue-editor")).json() as {
    state: { spots: NonNullable<SmokeSnapshot["venue"]>["spots"] };
  };
  const addedStateSpot = venueStateAfterAdd.state.spots.find((spot) => spot.id === addedSpotId);
  expect(addedStateSpot?.label).toBe(addedSpotId);

  await stageHost.click();
  await stageGuest.click({ modifiers: ["Shift"] });
  await expect(editor).toContainText("2 spots selected");

  await expect(panel).toContainText("2 selected");
  await expect(panel.getByRole("button", { name: "Link" })).toHaveCount(0);

  await panel.getByRole("button", { name: "Copy", exact: true }).click();
  const pastedHosts = page.locator("[data-spot-id^='stage_host_copy_']");
  const pastedHostCount = await pastedHosts.count();
  const pasteAutosave = waitForVenueEditorAutosave(page);
  await panel.getByRole("button", { name: "Paste", exact: true }).click();
  await expect((await pasteAutosave).ok()).toBe(true);
  await expect.poll(() => pastedHosts.count()).toBeGreaterThan(pastedHostCount);
  const pastedHost = pastedHosts.nth(pastedHostCount);
  const pastedHostId = await pastedHost.getAttribute("data-spot-id");
  expect(pastedHostId).toBeTruthy();
  await expect(pastedHost).toHaveAttribute("aria-label", `${pastedHostId!} Participant`);
  await expect(pastedHost).toHaveAttribute("title", `${pastedHostId!} (Participant)`);
  await expect(pastedHost).toHaveText("");
  const venueStateAfterPaste = await (await page.request.get("/api/venue-editor")).json() as {
    state: { spots: NonNullable<SmokeSnapshot["venue"]>["spots"] };
  };
  const pastedStateSpot = venueStateAfterPaste.state.spots.find((spot) => spot.id === pastedHostId);
  expect(pastedStateSpot?.label).toBe(pastedHostId);

  const deleteAutosave = waitForVenueEditorAutosave(page);
  await panel.getByRole("button", { name: "Delete", exact: true }).click();
  await expect((await deleteAutosave).ok()).toBe(true);
  await expect.poll(() => pastedHosts.count()).toBe(pastedHostCount);
  await expect(editor).toContainText("Saved");
});

test("connects rooms and edits room path waypoints", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  const stageRoom = page.locator("[data-room-id='stage']");
  const greenRoom = page.locator("[data-room-id='green_room']");
  const greenRoomPath = page.locator("[data-room-path='green_room__stage']");
  const workshopRight = page.locator("[data-room-id='workshop_right']");
  const path = page.locator("[data-room-path='stage__workshop_right']");
  await expect(stageRoom).toBeVisible();
  await expect(workshopRight).toBeVisible();
  await expect(page.locator("[data-room-path]")).not.toHaveCount(0);
  await stageRoom.click();
  await expect(page.locator("[data-spot-id='stage_host']")).toBeVisible();
  await expect(page.locator("[data-connected-rooms-list]")).toContainText("Green Room");
  await expect(page.locator("[data-connected-room-id='green_room']")).toContainText("Green Room");
  await expect(greenRoomPath).toHaveClass(/is-room-connected/);
  const greenRoomRow = page.locator("[data-connected-room-id='green_room']");
  await greenRoomRow.hover();
  await expect(greenRoomPath).toHaveClass(/is-hovered/);
  await expect(greenRoomRow).toHaveClass(/is-path-hovered/);
  await stageRoom.hover();
  await expect(greenRoomPath).not.toHaveClass(/is-hovered/);
  await greenRoom.hover();
  await expect(greenRoomPath).toHaveClass(/is-hovered/);
  await stageRoom.hover();
  await expect(greenRoomPath).not.toHaveClass(/is-hovered/);
  await expect(workshopRight.getByRole("button", { name: "Connect" })).toHaveCount(0);

  await workshopRight.hover();
  await expect(workshopRight.getByRole("button", { name: "Connect" })).toHaveCount(0);
  await workshopRight.click();
  await expect(workshopRight).toHaveClass(/is-connect-target/);
  const connectButton = page.locator("[data-selected-room-panel]").getByRole("button", { name: "Create Path" });
  await expect(connectButton).toBeVisible();
  const connectAutosave = waitForVenueEditorAutosave(page);
  await connectButton.click();
  await expect((await connectAutosave).ok()).toBe(true);
  await expect(path).toHaveClass(/is-editing/);

  const venueResponse = await page.request.get("/api/venue-editor");
  const venueBody = await venueResponse.json() as {
    state: {
      dimensions: { width: number; height: number };
      rooms: Array<{ rect?: { x: number; y: number; width: number; height: number } }>;
    };
  };
  const waypointPosition = findPositionOutsideRoomRects(venueBody.state.rooms, venueBody.state.dimensions);
  const addPointAutosave = waitForVenueEditorAutosave(page);
  await clickVenueBoardPosition(page, waypointPosition, venueBody.state.dimensions);
  await expect((await addPointAutosave).ok()).toBe(true);
  const waypoint = page.locator("[data-path-id='stage__workshop_right'][data-path-point-index='0']");
  await expect(waypoint).toBeVisible();
  const beforeDrag = await waypoint.getAttribute("data-position");
  const waypointBox = await waypoint.boundingBox();
  if (!waypointBox) {
    throw new Error("Expected room path waypoint");
  }
  await page.mouse.move(waypointBox.x + waypointBox.width / 2, waypointBox.y + waypointBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(waypointBox.x + waypointBox.width / 2 + 25, waypointBox.y + waypointBox.height / 2 + 20, { steps: 5 });
  const dragPointAutosave = waitForVenueEditorAutosave(page);
  await page.mouse.up();
  await expect((await dragPointAutosave).ok()).toBe(true);
  await expect.poll(() => waypoint.getAttribute("data-position")).not.toBe(beforeDrag);
  await expect(editor).toContainText("Saved");
});

test("selects existing room paths to edit and delete them", async ({ page }) => {
  await page.goto("/venue-editor");

  const path = page.locator("[data-room-path='green_room__stage']");
  const pathHitTarget = page.locator("[data-room-path-hit='green_room__stage']");
  await expect(path).toBeVisible();
  await expect(pathHitTarget).toHaveCount(1);
  await pathHitTarget.click();
  await expect(path).toHaveClass(/is-editing/);
  const selectedPathPanel = page.locator("[data-selected-path-panel]");
  await expect(selectedPathPanel).toBeVisible();
  await expect(selectedPathPanel).toContainText("Green Room");
  await expect(selectedPathPanel).toContainText("Main Stage");

  const board = page.locator("[data-board]");
  const boardBox = await board.boundingBox();
  if (!boardBox) {
    throw new Error("Expected venue board bounding box");
  }

  const addPointAutosave = waitForVenueEditorAutosave(page);
  await page.mouse.click(boardBox.x + boardBox.width * 0.74, boardBox.y + boardBox.height * 0.24);
  await expect((await addPointAutosave).ok()).toBe(true);

  const waypoint = page.locator("[data-path-id='green_room__stage'][data-path-point-index='0']");
  await expect(waypoint).toBeVisible();
  const beforeDrag = await waypoint.getAttribute("data-position");
  const waypointBox = await waypoint.boundingBox();
  if (!waypointBox) {
    throw new Error("Expected room path waypoint");
  }
  await page.mouse.move(waypointBox.x + waypointBox.width / 2, waypointBox.y + waypointBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(waypointBox.x + waypointBox.width / 2 - 18, waypointBox.y + waypointBox.height / 2 + 24, { steps: 5 });
  const dragPointAutosave = waitForVenueEditorAutosave(page);
  await page.mouse.up();
  await expect((await dragPointAutosave).ok()).toBe(true);
  await expect.poll(() => waypoint.getAttribute("data-position")).not.toBe(beforeDrag);

  await waypoint.click();
  await expect(selectedPathPanel).toContainText("Waypoint 1 selected");
  const deleteWaypointAutosave = waitForVenueEditorAutosave(page);
  await selectedPathPanel.getByRole("button", { name: "Delete Waypoint" }).click();
  await expect((await deleteWaypointAutosave).ok()).toBe(true);
  await expect(waypoint).toHaveCount(0);
  await expect(path).toBeVisible();

  const deleteAutosave = waitForVenueEditorAutosave(page);
  await selectedPathPanel.getByRole("button", { name: "Delete Path" }).click();
  await expect((await deleteAutosave).ok()).toBe(true);
  await expect(path).toHaveCount(0);
  await expect(selectedPathPanel).toHaveCount(0);
});

test("removes connected room paths from the selected room panel", async ({ page }) => {
  await page.goto("/venue-editor");

  const editor = page.locator(".venue-editor");
  const stageRoom = page.locator("[data-room-id='stage']");
  const prosceniumPath = page.locator("[data-room-path='proscenium_apron__stage']");
  await expect(stageRoom).toBeVisible();
  await expect(prosceniumPath).toBeVisible();
  await stageRoom.click();

  const prosceniumRow = page.locator("[data-connected-room-id='proscenium_apron']");
  const removeProsceniumLink = prosceniumRow.getByRole("button", { name: "Remove link to Proscenium Apron" });
  await expect(prosceniumRow).toContainText("Proscenium Apron");
  await expect(removeProsceniumLink).toHaveText("[x]");

  const unlinkAutosave = waitForVenueEditorAutosave(page);
  await removeProsceniumLink.click();
  await expect((await unlinkAutosave).ok()).toBe(true);
  await expect(prosceniumPath).toHaveCount(0);
  await expect(prosceniumRow).toHaveCount(0);
  await expect(editor).toContainText("Saved");
});

test("zooms the venue map without moving room geometry", async ({ page }) => {
  await page.goto("/venue-editor");

  const board = page.locator("[data-board]");
  const stageRoom = page.locator("[data-room-id='stage']");
  await expect(board).toBeVisible();
  await expect(stageRoom).toBeVisible();

  const boardBox = await board.boundingBox();
  if (!boardBox) {
    throw new Error("Expected venue board bounding box");
  }

  const beforeZoom = Number(await board.getAttribute("data-zoom"));
  const rectBeforeZoom = await stageRoom.getAttribute("data-rect");
  await page.mouse.move(boardBox.x + boardBox.width / 2, boardBox.y + boardBox.height / 2);
  await page.mouse.wheel(0, 500);
  await expect.poll(async () => Number(await board.getAttribute("data-zoom"))).toBeGreaterThan(beforeZoom);
  expect(await stageRoom.getAttribute("data-rect")).toBe(rectBeforeZoom);
});

test("resizes the game shell with the browser window", async ({ page }) => {
  await page.setViewportSize({ width: 1180, height: 760 });
  await page.goto("/");

  const app = page.locator("#app");
  const canvas = page.locator("#world-canvas");
  await expectServerFedHud(page.locator("#hud"));

  const wideApp = await app.boundingBox();
  const wideCanvas = await canvas.boundingBox();
  if (!wideApp || !wideCanvas) {
    throw new Error("Expected game app and canvas boxes");
  }

  expect(Math.round(wideApp.width)).toBe(1180);
  expect(Math.round(wideApp.height)).toBe(760);

  await page.setViewportSize({ width: 640, height: 760 });
  await expect.poll(async () => Math.round((await app.boundingBox())?.width ?? 0)).toBe(640);
  await expect.poll(async () => Math.round((await app.boundingBox())?.height ?? 0)).toBe(760);

  const narrowCanvas = await canvas.boundingBox();
  if (!narrowCanvas) {
    throw new Error("Expected resized canvas box");
  }

  expect(narrowCanvas.width).not.toBeCloseTo(wideCanvas.width, 0);
  expect(narrowCanvas.width).toBeGreaterThan(500);
});

test("drives the simulation from the controls panel", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");

  await expectServerFedHud(hud);
  await openControlsPanel(page);
  const stopButton = page.getByRole("button", { name: "Stop" });
  const playButton = page.getByRole("button", { name: "Play" });
  const stepButton = page.getByRole("button", { name: "Step" });
  await expect(stopButton).toBeVisible();
  await expect(playButton).toBeVisible();
  await expect(stepButton).toBeVisible();

  await stopButton.click();
  await expect(stopButton).toHaveClass(/is-active/, { timeout: 10_000 });

  await stepButton.click();
  await expect(stepButton).toBeEnabled();

  await playButton.click();
  await expect(playButton).toHaveClass(/is-active/, { timeout: 10_000 });

  await page.keyboard.press("Space");
  await expect(stopButton).toHaveClass(/is-active/, { timeout: 10_000 });

  await page.keyboard.press("Space");
  await expect(playButton).toHaveClass(/is-active/, { timeout: 10_000 });
});

test("keeps the first control click when the HUD refreshes during the press", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  await expectServerFedHud(hud);
  await openControlsPanel(page);

  const stopButton = page.getByRole("button", { name: "Stop" });
  await expect(stopButton).toBeVisible();

  const startingTick = await readWorldTick(page);
  const buttonBox = await stopButton.boundingBox();
  if (!buttonBox) {
    throw new Error("Expected Stop control bounding box");
  }

  await page.mouse.move(buttonBox.x + buttonBox.width / 2, buttonBox.y + buttonBox.height / 2);
  await page.mouse.down();
  await expect.poll(async () => readWorldTick(page), { timeout: 5_000 }).toBeGreaterThan(startingTick);
  await page.mouse.up();

  await expect(stopButton).toHaveClass(/is-active/, { timeout: 10_000 });
});

test("opens the top controls panel only from command-g", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  await expectServerFedHud(hud);
  await expect(hud.locator(".top-panel")).toBeHidden();
  await expect(hud.locator("[data-action='toggle-top-controls']")).toHaveCount(0);

  await openControlsPanel(page);
  await expect(hud.locator(".top-panel")).toBeVisible();
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Step" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Venue editor" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Shuffle" })).toBeVisible();

  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Venue editor" }).click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL(/\/venue-editor(?:$|\?)/);
  await popup.close();

  await closeControlsPanel(page);
  await expect(hud.locator(".top-panel")).toBeHidden();
});

test("keeps disco toggle focus while websocket snapshots refresh the HUD", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  await expectServerFedHud(hud);
  await openControlsPanel(page);

  const discoButton = page.locator("#top-controls-panel [data-action='toggle-disco']");
  await expect(discoButton).toBeVisible();
  if ((await discoButton.getAttribute("aria-pressed")) === "true") {
    await discoButton.click();
    await expect(discoButton).toHaveAttribute("aria-pressed", "false", { timeout: 10_000 });
  }

  await discoButton.focus();
  await expect(discoButton).toBeFocused();
  const startingTick = await readWorldTick(page);
  await expect.poll(async () => readWorldTick(page), { timeout: 5_000 }).toBeGreaterThan(startingTick);
  await expect(discoButton).toBeFocused();

  const controlResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/control") && response.request().method() === "POST",
    { timeout: 3_000 },
  );
  await discoButton.click();
  await expect((await controlResponse).ok()).toBe(true);
  await expect(discoButton).toHaveAttribute("aria-pressed", "true", { timeout: 10_000 });
  await expect(discoButton).toBeFocused();
  await expect(hud.locator(".teams-color-bar")).toHaveClass(/is-disco/);

  await discoButton.click();
  await expect(discoButton).toHaveAttribute("aria-pressed", "false", { timeout: 10_000 });
});

test("shuffles cog teams from the top controls panel", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  await expectServerFedHud(hud);
  const beforeColors = await cogTeamColors(page);

  await openControlsPanel(page);
  const shuffleResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/cogs/shuffle-teams") && response.request().method() === "POST",
    { timeout: 3_000 },
  );
  await page.getByRole("button", { name: "Shuffle" }).click();
  await expect((await shuffleResponse).ok()).toBe(true);

  await expectBalancedTeamShuffle(page, beforeColors);
});

test("selects cogs from the right roster panel", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const selectedRow = hud.locator(".top-status-item[data-status='selected']");
  const roster = page.locator(".cogs-panel");
  const log = page.locator(".log-panel");
  const babbage = roster.locator(".cog-row", { hasText: "Babbage" });

  await expectServerFedHud(hud);
  await expect(roster).toBeVisible();
  await expect(roster).toContainText("Ada");
  await expect(roster).toContainText("Babbage");
  await expect(roster).toContainText("Mira");

  await babbage.click();

  await expect(selectedRow).toContainText("Babbage");
  await expect(babbage).toHaveClass(/is-selected/);
  await expect(log).toContainText("Babbage");
  await expect(log.locator(".profile-section")).toBeVisible();
  expect(await log.locator(".profile-section").getAttribute("open")).toBeNull();
  await expect(babbage.locator(".trait-badge")).toHaveCount(0);
  await expect(roster.locator(".cog-color")).toHaveCount(0);
  await expect(babbage.locator(".cog-row-avatar img")).toBeVisible();
  await expect(babbage.locator(".cog-row-flip")).toBeVisible();
  await expect(babbage.locator(".cog-score")).toContainText("pts");
  const babbageBox = await babbage.boundingBox();
  expect(babbageBox?.height).toBeLessThanOrEqual(58);
  await expect(log.locator(".log-subsection[data-log-subsection='actions'] .log-outline-row.is-selected").first()).toBeVisible({
    timeout: 10_000,
  });
});

test("clears the selected cog with escape", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const roster = page.locator(".cogs-panel");
  const selectedRows = roster.locator(".cog-row.is-selected");
  const babbage = roster.locator(".cog-row", { hasText: "Babbage" });

  await expectServerFedHud(hud);
  await expect(roster).toBeVisible();

  await babbage.click();
  await expect(babbage).toHaveClass(/is-selected/);
  await expect(selectedRows).toHaveCount(1);

  await page.keyboard.press("Escape");

  await expect(babbage).not.toHaveClass(/is-selected/);
  await expect(selectedRows).toHaveCount(0);

  await page.waitForTimeout(700);
  await expect(selectedRows).toHaveCount(0);
});

test("leaves command-w available for browser window close", async ({ page }) => {
  await page.goto("/");

  await expectServerFedHud(page.locator("#hud"));

  const keydownWasCanceled = await page.evaluate(() => {
    const event = new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      code: "KeyW",
      key: "w",
      metaKey: true,
    });

    return !window.dispatchEvent(event);
  });

  expect(keydownWasCanceled).toBe(false);
});

test("toggles the shortcuts panel with f1", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const shortcutsPanel = hud.locator(".shortcuts-panel");
  await expectServerFedHud(hud);
  await expect(shortcutsPanel).toHaveCount(0);

  await page.keyboard.press("F1");

  await expect(shortcutsPanel).toBeVisible();
  await expect(shortcutsPanel).toContainText("Cmd-G");
  await expect(shortcutsPanel).toContainText("Cmd-S");
  await expect(page).toHaveURL(/\/$/);

  await page.keyboard.press("F1");

  await expect(shortcutsPanel).toHaveCount(0);
});

test("toggles controls and game flow with command-g", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  await expectServerFedHud(hud);
  await expect(hud.locator("[data-action='toggle-top-controls']")).toHaveCount(0);
  await expect(hud.locator(".top-drawer")).toBeHidden();
  await expect(hud.locator(".game-flow-panel")).toHaveCount(0);

  await page.keyboard.press("Meta+G");

  await expect(hud.locator(".top-drawer")).toBeVisible();
  await expect(hud.locator(".game-flow-panel")).toBeVisible();

  await page.keyboard.press("Meta+G");

  await expect(hud.locator(".top-drawer")).toBeHidden();
  await expect(hud.locator(".game-flow-panel")).toHaveCount(0);
});

test("toggles roster with command-r", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  await expectServerFedHud(hud);
  await expect(hud.locator(".right-panel")).toBeVisible();

  await page.keyboard.press("Meta+R");

  await expect(hud.locator(".right-panel")).toHaveCount(0);
  await expect(page).toHaveURL(/\/$/);

  await page.keyboard.press("Meta+R");

  await expect(hud.locator(".right-panel")).toBeVisible();
});

test("toggles the builder QR code with command-b", async ({ page }) => {
  await page.goto("/");

  const qrCard = page.locator(".builder-qr-card");
  await expectServerFedHud(page.locator("#hud"));
  await expect(qrCard).toBeVisible();

  await page.keyboard.press("Meta+B");

  await expect(qrCard).toHaveCount(0);
  await expect(page).toHaveURL(/\/$/);

  await page.keyboard.press("Meta+B");

  await expect(qrCard).toBeVisible();
});

test("toggles disco mode with command-d", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const discoButton = page.locator("#top-controls-panel [data-action='toggle-disco']");
  await expectServerFedHud(hud);

  const initialPressed = await discoButton.getAttribute("aria-pressed");
  const nextPressed = initialPressed === "true" ? "false" : "true";
  const firstToggle = page.waitForResponse(
    (response) => response.url().endsWith("/api/control") && response.request().method() === "POST",
    { timeout: 3_000 },
  );
  await page.keyboard.press("Meta+D");

  await expect((await firstToggle).ok()).toBe(true);
  await expect(discoButton).toHaveAttribute("aria-pressed", nextPressed, { timeout: 10_000 });
  await expect(page).toHaveURL(/\/$/);

  const secondToggle = page.waitForResponse(
    (response) => response.url().endsWith("/api/control") && response.request().method() === "POST",
    { timeout: 3_000 },
  );
  await page.keyboard.press("Meta+D");

  await expect((await secondToggle).ok()).toBe(true);
  await expect(discoButton).toHaveAttribute("aria-pressed", initialPressed ?? "false", { timeout: 10_000 });
});

test("shuffles teams with command-s", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  await expectServerFedHud(hud);
  await expect(hud.locator(".top-drawer")).toBeHidden();
  const beforeColors = await cogTeamColors(page);

  const shuffleResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/cogs/shuffle-teams") && response.request().method() === "POST",
    { timeout: 3_000 },
  );
  await page.keyboard.press("Meta+S");

  await expect((await shuffleResponse).ok()).toBe(true);
  await expect(page).toHaveURL(/\/$/);
  await expect(hud.locator(".top-drawer")).toBeHidden();
  await expectBalancedTeamShuffle(page, beforeColors);
});

test("selects cogs by clicking them on the map", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const canvas = page.locator("#world-canvas");
  const selectedRow = hud.locator(".top-status-item[data-status='selected']");

  await expectServerFedHud(hud);
  await openControlsPanel(page);
  const stopButton = page.getByRole("button", { name: "Stop" });
  await stopButton.click();
  await expect(stopButton).toHaveClass(/is-active/, { timeout: 10_000 });
  await page.waitForTimeout(700);
  await closeControlsPanel(page);

  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  const target = findKeyboardMoveTarget(snapshot);

  const box = await canvas.boundingBox();
  if (!box) {
    throw new Error("Expected canvas bounding box");
  }
  const tileSize = Math.min(box.width / snapshot.dimensions.width, box.height / snapshot.dimensions.height);
  const offsetX = (box.width - snapshot.dimensions.width * tileSize) / 2;
  const offsetY = (box.height - snapshot.dimensions.height * tileSize) / 2;

  await canvas.click({
    position: {
      x: offsetX + (target.cog.position.x + 0.5) * tileSize,
      y: offsetY + (target.cog.position.y + 0.5) * tileSize,
    },
  });

  await expect(selectedRow).toContainText(target.cog.name);
  await page.keyboard.press(target.key);
  await expect
    .poll(async () => {
      const movedSnapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
      return movedSnapshot.cogs.find((cog) => cog.id === target.cog.id)?.position;
    })
    .toEqual(target.expectedPosition);
});

test("expands a roster cog on click and shows its inspector details", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const roster = page.locator(".cogs-panel");

  await expectServerFedHud(hud);
  await openControlsPanel(page);
  const stopButton = page.getByRole("button", { name: "Stop" });
  await stopButton.click();
  await expect(stopButton).toHaveClass(/is-active/, { timeout: 10_000 });
  await page.waitForTimeout(700);
  await closeControlsPanel(page);

  const target = await expandRosterCog(roster);

  await expect(target.panel).toContainText("Traits");
  await expect(target.panel).toContainText("Achievement Goals");
  await expect(target.panel).not.toContainText("State");
  await expect(target.panel).not.toContainText("Valid Actions");
  await expect(target.panel.locator(".cog-choice-facts")).toHaveCount(0);
  await expect(target.panel.locator(".trait-badge[data-trait-kind='defensiveTrait']")).toBeVisible();
  await expect(target.panel.locator(".trait-badge[data-trait-kind='activeTrait']")).toBeVisible();
  await expect(target.panel.locator(".trait-badge[data-trait-kind='personalGoal']")).toHaveCount(0);

  const profileLink = target.panel.locator("[data-action='open-profile-window']");
  await expect(profileLink).toBeVisible();
  await expect(target.panel.locator(".cog-choice-qr-code")).toBeVisible();
  await expect(profileLink).toHaveAttribute("href", new RegExp(`/profile/${target.cogId}\\?setCogCookie=1$`));
  await expect(profileLink).toHaveAttribute("target", "cogshambo-profile");
  await expect(target.panel.getByRole("button", { name: /Kick .+ home/ })).toBeVisible();
  await expect(target.panel.locator("[data-action='select-cog-valid-action']")).toHaveCount(0);
  await expect(target.panel.locator("[data-action='select-cog-choice']")).toHaveCount(0);

  const profilePopupPromise = page.waitForEvent("popup");
  await profileLink.click();
  const profilePage = await profilePopupPromise;
  await profilePage.waitForLoadState("domcontentloaded");
  expect(new URL(profilePage.url()).pathname).toBe(`/profile/${target.cogId}`);
  expect(new URL(profilePage.url()).searchParams.get("setCogCookie")).toBe("1");
  await expect(profilePage.locator(".cog-profile-page")).toBeVisible();
  await expect
    .poll(async () => profilePage.evaluate(() => document.cookie))
    .toContain(`cogshambo_cog_id=${encodeURIComponent(target.cogId)}`);
  await profilePage.close();
});

test("opens a full cog profile page with prompt-only auto-save editing and history", async ({ page }) => {
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  const cog = snapshot.cogs.find((candidate) => candidate.name === "Babbage") ?? snapshot.cogs[0];
  if (!cog) {
    throw new Error("Expected at least one cog in the smoke world");
  }

  await page.goto(`/profile/${encodeURIComponent(cog.id)}`);
  await expectStandaloneRoute(page);

  const profile = page.locator(".cog-profile-page");
  await expect(profile).toBeVisible();
  await expect(profile.locator(".profile-hero h1")).toContainText("Babbage");
  await expect(profile).toContainText("Diary");
  await expect(profile.locator(".profile-score-block")).toHaveCount(0);
  await expect(profile).not.toContainText("Debate History");
  await expect(profile).toContainText("Controller Log");
  const achievement = profile.locator(".profile-achievement-row").first();
  await expect(achievement).toBeVisible();
  await expect(achievement).not.toHaveAttribute("open", "");
  await achievement.locator("summary").click();
  await expect(achievement).toHaveAttribute("open", "");
  await expect(achievement.locator(".profile-achievement-description")).toBeVisible();

  await expect(profile.locator("[data-profile-field='name']")).toHaveCount(0);
  await expect(profile.locator(".trait-editor")).toHaveCount(0);
  await expect(profile.locator(".attribute-editor")).toHaveCount(0);
  await expect(profile.getByRole("button", { name: "Save profile" })).toHaveCount(0);

  const promptInput = profile.locator("[data-profile-field='behaviorPrompt']");
  const savedPrompt = "Auto-save this profile prompt.";
  const profileSave = page.waitForResponse(
    (response) => response.url().includes("/api/cogs/") && response.url().endsWith("/profile") && response.request().method() === "PATCH",
    { timeout: 2_000 },
  );
  await promptInput.fill(savedPrompt);
  await expect((await profileSave).ok()).toBe(true);
  const updatedSnapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  expect(updatedSnapshot.cogs.find((candidate) => candidate.id === cog.id)?.behaviorPrompt).toBe(savedPrompt);

  await profile.getByRole("button", { name: "Close" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("keeps compact profile edit focus while websocket snapshots refresh the main HUD", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const roster = page.locator(".cogs-panel");
  const babbage = roster.locator(".cog-row", { hasText: "Babbage" });

  await expectServerFedHud(hud);
  await openControlsPanel(page);
  await page.getByRole("button", { name: "Play" }).click();
  await babbage.click();
  await page.locator(".log-panel .profile-section summary").click();

  const profile = page.locator(".log-panel .profile-section");
  const promptInput = profile.locator("[data-profile-field='behaviorPrompt']");
  await expect(profile).toBeVisible();
  await profile.evaluate((element) => {
    element.setAttribute("data-profile-preserve-marker", "root");
  });

  const startingTick = await readWorldTick(page);
  await promptInput.fill("Babbage live prompt draft.");
  await expect(promptInput).toBeFocused();

  await expect.poll(async () => readWorldTick(page), { timeout: 5_000 }).toBeGreaterThan(startingTick);
  await page.waitForTimeout(300);
  await expect(profile).toHaveAttribute("data-profile-preserve-marker", "root");
  await expect(promptInput).toBeFocused();
  await expect(promptInput).toHaveValue("Babbage live prompt draft.");
});

test("keeps full profile page draft focus and diary state on the standalone route", async ({ page }) => {
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  const cog = snapshot.cogs.find((candidate) => candidate.name === "Babbage") ?? snapshot.cogs[0];
  if (!cog) {
    throw new Error("Expected at least one cog in the smoke world");
  }

  const websocketUrls = collectWebSocketUrls(page);
  await page.goto(`/profile/${encodeURIComponent(cog.id)}`);

  const profile = page.locator(`.cog-profile-page[data-cog-id="${cog.id}"]`);
  const promptInput = profile.locator("[data-profile-field='behaviorPrompt']");
  const achievement = profile.locator(".profile-achievement-row").first();

  await expectStandaloneRoute(page);
  await expect(profile).toBeVisible();
  await expect(promptInput).toBeVisible();
  await expect(achievement).toBeVisible();
  const diaryEntryCount = await profile.locator(".profile-diary-room-entry").count();
  const openedDiaryEntry = diaryEntryCount > 0
    ? profile.locator(".profile-diary-room-entry").first()
    : undefined;
  if (openedDiaryEntry) {
    await openedDiaryEntry.evaluate((entry) => {
      if (entry instanceof HTMLDetailsElement) {
        entry.open = true;
      }
    });
    await expect(openedDiaryEntry).toHaveAttribute("open", "");
  }
  await achievement.locator("summary").click();
  await expect(achievement).toHaveAttribute("open", "");

  await promptInput.fill("Unsaved profile draft keeps focus while the profile updates.");
  await promptInput.evaluate((element) => {
    if (!(element instanceof HTMLTextAreaElement)) {
      throw new Error("Expected profile prompt textarea");
    }

    element.setSelectionRange(17, 22);
    element.scrollTop = element.scrollHeight;
  });
  await expect(promptInput).toBeFocused();

  const startingTick = await readWorldTick(page);
  await expect.poll(async () => readWorldTick(page), { timeout: 5_000 }).toBeGreaterThan(startingTick);
  await page.waitForTimeout(300);

  if (openedDiaryEntry) {
    await expect(openedDiaryEntry).toHaveAttribute("open", "");
  }
  await expect(achievement).toHaveAttribute("open", "");
  await expect(promptInput).toBeFocused();
  await expect(promptInput).toHaveValue("Unsaved profile draft keeps focus while the profile updates.");
  await expect
    .poll(async () =>
      promptInput.evaluate((element) => ({
        selectionEnd: (element as HTMLTextAreaElement).selectionEnd,
        selectionStart: (element as HTMLTextAreaElement).selectionStart,
      })),
    )
    .toEqual({ selectionEnd: 22, selectionStart: 17 });
  expect(websocketUrls).toEqual([]);
});

test("keeps roster scroll while websocket snapshots refresh the HUD", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const roster = page.locator(".cog-roster");
  const tickValue = hud.locator("[data-status='tick'] .top-value");

  await expectServerFedHud(hud);
  for (let index = 0; index < 14; index += 1) {
    await createSmokeCog(page, index);
  }
  await expect(roster.locator(".cog-row")).toHaveCount(17, { timeout: 10_000 });
  await expect.poll(() => isScrollable(roster)).toBe(true);

  const startingTick = Number(await tickValue.textContent());
  const scrollBefore = await roster.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
    return element.scrollTop;
  });
  expect(scrollBefore).toBeGreaterThan(0);
  const focusedCogId = await focusRosterRow(roster, 10);
  await expect(roster.locator(`[data-cog-id="${focusedCogId}"]`)).toBeFocused();

  await expect.poll(async () => Number(await tickValue.textContent()), { timeout: 5_000 }).toBeGreaterThan(startingTick);
  await expect(roster.locator(`[data-cog-id="${focusedCogId}"]`)).toBeFocused();
  await expect.poll(() => roster.evaluate((element) => element.scrollTop), { timeout: 5_000 }).toBeGreaterThanOrEqual(scrollBefore - 1);
});

test("hides rule trait editing from the profile page", async ({ page }) => {
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  const cog = snapshot.cogs.find((candidate) => candidate.name === "Babbage") ?? snapshot.cogs[0];
  if (!cog) {
    throw new Error("Expected at least one cog in the smoke world");
  }

  await page.goto(`/profile/${encodeURIComponent(cog.id)}`);
  await expectStandaloneRoute(page);

  const profile = page.locator(".cog-profile-page");

  await expect(profile.locator(".trait-editor")).toHaveCount(0);
  await expect(profile.locator("[data-action='set-trait']")).toHaveCount(0);
  await expect(profile.locator("[data-profile-field='behaviorPrompt']")).toBeVisible();
});

test("builds a cog with generated sprites and opens its profile", async ({ page }) => {
  await mockArtGenSprites(page);
  await page.goto("/");

  const hud = page.locator("#hud");
  await expectServerFedHud(hud);

  await page.keyboard.press("Meta+G");
  const buildCogButton = page.locator("#top-controls-panel [data-action='open-builder-link']");
  await expect(buildCogButton).toBeVisible();

  const popupPromise = page.waitForEvent("popup");
  await buildCogButton.click();
  const builderPage = await popupPromise;
  await builderPage.waitForLoadState("domcontentloaded");

  const builder = builderPage.locator(".cog-builder-page");
  await expect(builder).toBeVisible();
  await expect(builder.locator(".builder-sprite-option")).toHaveCount(0);
  await advanceBuilderWizardToSprites(builder, {
    name: "Helix",
    description: "A brass passionate cog with a teal glass eye and careful park arguments.",
  });

  await expect(builder.locator(".builder-sprite-option")).toHaveCount(11);
  await builder.getByRole("button", { name: "Generate custom sprite" }).click();
  await waitForBuilderSpritesReady(builder);
  await expect(builder.locator(".builder-sprite-option")).toHaveCount(2);
  await expect(builder.locator("[data-action='select-builder-sprite'] img").first()).toHaveAttribute(
    "src",
    "/assets/cogshambo/sprite-sheets/cute-scout-cog/frames/cute-scout-cog-01.png",
  );
  await builder.locator("[data-action='select-builder-sprite']").first().click();
  await expect(builder.locator("[data-action='select-builder-sprite']").first()).toHaveClass(/is-selected/);

  const create = builderPage.waitForResponse(
    (response) => response.url().endsWith("/api/cogs") && response.request().method() === "POST",
    { timeout: 3_000 },
  );
  const profilePopupPromise = page.waitForEvent("popup");
  await builder.locator("[data-action='builder-next']").click();
  await builder.locator("[data-action='builder-next']").click();
  await expect(builder.locator("[data-builder-step='side']")).toBeVisible();
  await builder.getByRole("button", { name: "Join The Red Team" }).click();
  await expect((await create).ok()).toBe(true);

  await expect.poll(() => builderPage.isClosed()).toBe(true);
  const profilePage = await profilePopupPromise;
  await profilePage.waitForLoadState("domcontentloaded");
  expect(new URL(profilePage.url()).pathname).toMatch(/^\/profile\//);
  await expect(profilePage.locator(".cog-profile-page")).toBeVisible();
  await expect(profilePage.getByRole("heading", { name: "Helix" })).toBeVisible();
  await expect(profilePage.locator(".cog-profile-page")).toContainText("teal glass eye");
  const createdCogId = decodeURIComponent(new URL(profilePage.url()).pathname.replace(/^\/profile\//, ""));
  const createdCogCookie = (await page.context().cookies()).find((cookie) => cookie.name === "cogshambo_cog_id");
  expect(createdCogCookie?.value).toBe(createdCogId);
  await profilePage.close();
});

test("keeps the cog builder usable on narrow screens", async ({ page }) => {
  await mockArtGenSprites(page);
  await page.setViewportSize({ width: 390, height: 740 });
  await page.goto("/");

  const hud = page.locator("#hud");
  await expectServerFedHud(hud);
  await expect(page.locator(".control-panel [data-action='open-builder-window']")).toHaveCount(0);

  const popupPromise = page.waitForEvent("popup");
  await page.locator(".builder-qr-card").click();
  const builderPage = await popupPromise;
  await builderPage.setViewportSize({ width: 390, height: 740 });
  await builderPage.waitForLoadState("domcontentloaded");

  const builder = builderPage.locator(".cog-builder-page");
  await expect(builder).toBeVisible();
  await expect(builder.locator(".builder-wizard-shell")).toBeVisible();
  await expect(builder.locator(".builder-sprite-option")).toHaveCount(0);
  await expect(builder.getByRole("button", { name: "Begin" })).toBeVisible();

  const hasInitialHorizontalOverflow = await builderPage.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(hasInitialHorizontalOverflow).toBe(false);

  await advanceBuilderWizardToSprites(builder, {
    name: "Pocket",
    description: "A compact mobile cog with a bright lens.",
  });

  await builderPage.locator(".cog-builder-shell").evaluate((element) => {
    element.scrollTo(0, element.scrollHeight);
  });
  await expect(builder.getByRole("button", { name: "Continue" })).toBeInViewport();

  await expect(builder.locator(".builder-sprite-option")).toHaveCount(11);
  await builder.getByRole("button", { name: "Generate custom sprite" }).click();
  await waitForBuilderSpritesReady(builder);
  await expect(builder.locator(".builder-sprite-option")).toHaveCount(2);
  await builder.locator("[data-action='select-builder-sprite']").first().click();
  await expect(builder.locator("[data-action='select-builder-sprite']").first()).toHaveClass(/is-selected/);

  const hasHorizontalOverflow = await builderPage.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(hasHorizontalOverflow).toBe(false);
});

test("keeps builder description focus and draft on the standalone route", async ({ page }) => {
  await mockArtGenSprites(page);
  await createSmokeCog(page, 0);
  const websocketUrls = collectWebSocketUrls(page);
  await page.goto("/builder");

  const builder = page.locator(".cog-builder-page");
  await expectStandaloneRoute(page);
  await expect(builder).toBeVisible();
  await advanceBuilderWizardToSprites(builder, {
    name: "Helix",
    description: "A brass passionate cog with a teal glass eye and careful park arguments.",
  });

  const description = builder.getByLabel("Cog appearance");
  const builderStage = builder.locator(".builder-wizard-stage");
  const spriteGrid = builder.locator(".builder-sprite-grid");
  await builderStage.evaluate((element) => {
    element.scrollTop = Math.min(160, Math.max(0, element.scrollHeight - element.clientHeight));
  });
  await expect(description).toBeFocused();
  await expect.poll(() => spriteGrid.evaluate((element) => getComputedStyle(element).overflowY), { timeout: 5_000 }).toBe(
    "visible",
  );
  const startingTick = await readWorldTick(page);

  await expect.poll(async () => readWorldTick(page), { timeout: 5_000 }).toBeGreaterThan(startingTick);

  await expect(builder.locator("[data-builder-step='appearance']")).toBeVisible();
  await expect(description).toBeFocused();
  await expect(description).toHaveValue("A brass passionate cog with a teal glass eye and careful park arguments.");
  await expect(builder.getByRole("button", { name: "Continue" })).toBeEnabled();
  await expect.poll(() => builderStage.evaluate((element) => element.scrollTop), { timeout: 5_000 }).toBeGreaterThanOrEqual(
    35,
  );
  expect(websocketUrls).toEqual([]);
});

test("auto-saves profile prompt edits without extra profile controls", async ({ page }) => {
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  const cog = snapshot.cogs.find((candidate) => candidate.name === "Babbage") ?? snapshot.cogs[0];
  if (!cog) {
    throw new Error("Expected at least one cog in the smoke world");
  }

  await page.goto(`/profile/${encodeURIComponent(cog.id)}`);
  await expectStandaloneRoute(page);

  const profile = page.locator(".cog-profile-page");
  const promptInput = profile.locator("[data-profile-field='behaviorPrompt']");
  const savedPrompt = "Compact profile prompts save by themselves.";
  const promptSave = page.waitForResponse(
    (response) => response.url().includes("/api/cogs/") && response.url().endsWith("/profile") && response.request().method() === "PATCH",
    { timeout: 2_000 },
  );
  await promptInput.fill(savedPrompt);
  await expect((await promptSave).ok()).toBe(true);

  await expect(profile.locator("[data-profile-field='name']")).toHaveCount(0);
  await expect(profile.locator(".trait-editor")).toHaveCount(0);
  await expect(profile.locator(".attribute-editor")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save profile" })).toHaveCount(0);
});

test("renders the cog log prompt and action feed", async ({ page }) => {
  await page.goto("/");

  const hud = page.locator("#hud");
  const roster = page.locator(".cogs-panel");
  const ada = roster.locator(".cog-row", { hasText: "Ada" });
  await expectServerFedHud(hud);
  const startingTick = await readWorldTick(page);
  await openControlsPanel(page);
  await page.getByRole("button", { name: "Play" }).click();
  await expect.poll(async () => readWorldTick(page), { timeout: 5_000 }).toBeGreaterThan(startingTick);
  await expect(ada).toHaveCount(1);
  const cogId = await ada.getAttribute("data-cog-id");
  if (!cogId) {
    throw new Error("Expected at least one cog in the smoke world");
  }

  await ada.click();
  await expect.poll(() => cogConversationLogLength(page, cogId), { timeout: 10_000 }).toBeGreaterThan(0);

  await page.goto(`/profile/${encodeURIComponent(cogId)}`);
  await expectStandaloneRoute(page);

  const controllerLog = page.locator(".profile-controller-log");
  await expect(controllerLog).not.toHaveAttribute("open", "");
  await expect(controllerLog.locator(".log-tick-section").first()).toBeHidden();
  await controllerLog.locator("summary.profile-block-header").click();
  await expect(controllerLog).toHaveAttribute("open", "");

  const tickSections = controllerLog.locator(".log-tick-section");
  await expect.poll(() => tickSections.count(), { timeout: 10_000 }).toBeGreaterThan(0);

  if ((await tickSections.count()) > 1) {
    const firstTick = await readTickSection(tickSections.first());
    const secondTick = await readTickSection(tickSections.nth(1));
    expect(firstTick).toBeGreaterThanOrEqual(secondTick);
  }

  const firstTickSection = tickSections.first();
  const subsections = firstTickSection.locator(".log-subsection");
  await expect(subsections).toHaveCount(5);
  expect(await subsectionOrder(firstTickSection)).toEqual(["rules", "identity", "current", "thoughts", "actions"]);
  await expect(firstTickSection.locator(".log-subsection[data-log-subsection='rules']")).toContainText("Instructions");
  await expect(firstTickSection.locator(".log-subsection[data-log-subsection='identity']")).toContainText("You Are");
  await expect(firstTickSection.locator(".log-subsection[data-log-subsection='current']")).toContainText("Current State");
  await expect(firstTickSection.locator(".log-subsection[data-log-subsection='thoughts']")).toContainText(
    "LLM Thoughts",
  );
  await expect(firstTickSection.locator(".log-subsection[data-log-subsection='actions']")).toContainText("Pick an action");
  const rules = firstTickSection.locator(".log-subsection[data-log-subsection='rules']");
  const identity = firstTickSection.locator(".log-subsection[data-log-subsection='identity']");
  const current = firstTickSection.locator(".log-subsection[data-log-subsection='current']");
  await expect(rules).not.toHaveAttribute("open", "");
  await expect(identity).toHaveAttribute("open", "");
  await expect(current).toHaveAttribute("open", "");
  await expect(firstTickSection.locator(".log-subsection[data-log-subsection='thoughts']")).toHaveAttribute("open", "");
  await expect(firstTickSection.locator(".log-subsection[data-log-subsection='actions']")).toHaveAttribute("open", "");
  await expect(rules.locator(".log-instructions-block")).toBeHidden();
  await rules.locator("summary").click();
  await expect(rules).toHaveAttribute("open", "");
  await expect(rules.locator(".log-instructions-block")).toBeVisible();
  await expect(rules.locator(".log-outline-row")).toHaveCount(0);
  await expect(firstTickSection.locator(".log-emphasis").first()).toBeVisible();

  const choices = firstTickSection.locator(".log-subsection[data-log-subsection='actions']");
  await expect(choices.locator(".log-outline-row.is-action.is-selected").first()).toBeVisible();
  await expect(choices.locator(".log-action-button")).toHaveCount(0);
  await expect(choices.locator(".log-move-pad")).toHaveCount(0);
  await expect(choices.locator(".log-selected-action")).toHaveCount(0);
});

async function expectServerFedHud(hud: Locator): Promise<void> {
  await expect(hud.locator(".top-drawer")).toBeAttached({ timeout: 10_000 });
  await expect(hud.locator(".cog-row").first()).toBeVisible({ timeout: 10_000 });
}

async function openControlsPanel(page: Page): Promise<void> {
  await page.keyboard.press("Meta+G");
  await expect(page.locator("#top-controls-panel")).toBeVisible();
}

async function closeControlsPanel(page: Page): Promise<void> {
  await page.keyboard.press("Meta+G");
  await expect(page.locator("#top-controls-panel")).toBeHidden();
}

async function cogTeamColors(page: Page): Promise<Map<string, string>> {
  const world = await page.request.get("/api/world").then((response) => response.json()) as {
    cogs: Array<{ id: string; color: string }>;
  };
  return new Map(world.cogs.map((cog) => [cog.id, cog.color]));
}

async function expectBalancedTeamShuffle(page: Page, beforeColors: Map<string, string>): Promise<void> {
  await expect
    .poll(async () => {
      const colors = await cogTeamColors(page);
      const teamColors = Array.from(colors.values());
      const changed = Array.from(colors).some(([id, color]) => color !== beforeColors.get(id));
      const redCount = teamColors.filter((color) => color === "red").length;
      const blueCount = teamColors.filter((color) => color === "blue").length;
      return changed && redCount === blueCount && redCount > 0;
    })
    .toBe(true);
}

async function expectStandaloneRoute(page: Page): Promise<void> {
  await expect(page.locator("#hud")).toHaveCount(0);
  await expect(page.locator("#world-canvas")).toHaveCount(0);
  await expect(page.locator("#world-bubbles")).toHaveCount(0);
}

function collectWebSocketUrls(page: Page): string[] {
  const urls: string[] = [];
  page.on("websocket", (socket) => {
    urls.push(socket.url());
  });
  return urls;
}

async function installWebGpuDrawProbe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    type RenderPassProbe = {
      drawCalls: number;
      lastInstanceCount: number;
      patchErrors: string[];
      patched: boolean;
    };
    type RenderPass = {
      draw: (vertexCount: number, instanceCount?: number, firstVertex?: number, firstInstance?: number) => void;
    };
    type CommandEncoderPrototype = {
      __cogshamboDrawProbePatched?: boolean;
      beginRenderPass?: (...args: unknown[]) => RenderPass;
    };

    const global = globalThis as typeof globalThis & {
      GPUCommandEncoder?: { prototype?: CommandEncoderPrototype };
      __cogshamboGpuDrawProbe?: RenderPassProbe;
    };
    const probe: RenderPassProbe = {
      drawCalls: 0,
      lastInstanceCount: 0,
      patchErrors: [],
      patched: false,
    };
    global.__cogshamboGpuDrawProbe = probe;

    let attempts = 0;
    const patch = (): void => {
      const prototype = global.GPUCommandEncoder?.prototype;
      if (!prototype?.beginRenderPass) {
        attempts += 1;
        if (attempts < 200) {
          window.setTimeout(patch, 10);
        }
        return;
      }

      if (prototype.__cogshamboDrawProbePatched) {
        probe.patched = true;
        return;
      }

      const originalBeginRenderPass = prototype.beginRenderPass;
      prototype.__cogshamboDrawProbePatched = true;
      prototype.beginRenderPass = function beginRenderPassWithProbe(...args: unknown[]): RenderPass {
        const pass = originalBeginRenderPass.apply(this, args);
        const originalDraw = pass.draw.bind(pass);
        pass.draw = (vertexCount, instanceCount = 1, firstVertex, firstInstance) => {
          probe.drawCalls += 1;
          probe.lastInstanceCount = instanceCount;
          return originalDraw(vertexCount, instanceCount, firstVertex, firstInstance);
        };
        return pass;
      };
      probe.patched = true;
    };

    try {
      patch();
    } catch (error) {
      probe.patchErrors.push(error instanceof Error ? error.message : String(error));
    }
  });
}

async function expectBoardRendererDraws(page: Page): Promise<void> {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const probe = (
            globalThis as typeof globalThis & {
              __cogshamboGpuDrawProbe?: {
                drawCalls: number;
                lastInstanceCount: number;
                patchErrors: string[];
                patched: boolean;
              };
            }
          ).__cogshamboGpuDrawProbe;
          if (probe?.patchErrors.length) {
            throw new Error(probe.patchErrors.join("; "));
          }
          if (probe?.patched && probe.lastInstanceCount > 0) {
            return probe.drawCalls;
          }

          const canvas = document.querySelector<HTMLCanvasElement>("#world-canvas");
          const context = canvas?.getContext("2d");
          if (!canvas || !context || canvas.width <= 0 || canvas.height <= 0) {
            return 0;
          }

          const image = context.getImageData(0, 0, canvas.width, canvas.height).data;
          let visibleSamples = 0;
          let samples = 0;
          const stepX = Math.max(1, Math.floor(canvas.width / 32));
          const stepY = Math.max(1, Math.floor(canvas.height / 32));
          for (let y = 0; y < canvas.height; y += stepY) {
            for (let x = 0; x < canvas.width; x += stepX) {
              const offset = (y * canvas.width + x) * 4;
              if (image[offset] + image[offset + 1] + image[offset + 2] > 60) {
                visibleSamples += 1;
              }
              samples += 1;
            }
          }

          return samples > 0 && visibleSamples / samples > 0.2 ? visibleSamples : 0;
        }),
      { timeout: 10_000 },
    )
    .toBeGreaterThan(0);
}

async function waitForBuilderSpritesReady(builder: Locator): Promise<void> {
  await expect(builder.getByRole("button", { name: "Generate custom sprite" })).toBeEnabled({ timeout: 15_000 });
}

async function advanceBuilderWizardToSprites(
  builder: Locator,
  options: { description: string; name: string },
): Promise<void> {
  await builder.locator("[data-action='builder-next']").click();
  await builder.getByLabel("Cog name").fill(options.name);
  await builder.locator("[data-action='builder-next']").click();
  await builder.locator("[data-trait-kind='defensiveTrait'][data-trait-value='stubborn']").click();
  await builder.locator("[data-action='builder-next']").click();
  await builder.locator("[data-trait-kind='activeTrait'][data-trait-value='passionate']").click();
  await builder.locator("[data-action='builder-next']").click();
  await expect(builder.locator("[data-builder-step='appearance']")).toBeVisible();
  await expect(builder.locator(".builder-sprite-option")).toHaveCount(11);
  await builder.getByRole("button", { name: "Custom", exact: true }).click();
  await builder.getByLabel("Cog appearance").fill(options.description);
}

async function mockArtGenSprites(page: Page): Promise<void> {
  await page.context().route("**/api/cog-sprites", async (route) => {
    const requestBody = route.request().postDataJSON() as { count?: number };
    const count = Math.max(1, Math.min(5, requestBody.count ?? 1));

    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        source: "nano-banana",
        sprites: Array.from({ length: count }, (_value, index) => {
          const frame = String(index + 1).padStart(2, "0");
          const url = `/assets/cogshambo/sprite-sheets/cute-scout-cog/frames/cute-scout-cog-${frame}.png`;
          return {
            key: `cute-scout-cog-${frame}`,
            label: `Sprite ${index + 1}`,
            url,
            spriteUrls: {
              red: url,
              blue: url,
            },
          };
        }),
      }),
    });
  });
}

async function createSmokeCog(page: Page, index: number): Promise<void> {
  const response = await page.request.post("/api/cogs", {
    data: {
      name: `Scroll Cog ${index + 1}`,
      color: index % 2 === 0 ? "red" : "blue",
    },
  });

  expect(response.status()).toBe(201);
}

async function isScrollable(locator: Locator): Promise<boolean> {
  return locator.evaluate((element) => element.scrollHeight > element.clientHeight);
}

async function focusRosterRow(roster: Locator, index: number): Promise<string> {
  return roster.locator(".cog-row").nth(index).evaluate((element) => {
    if (!(element instanceof HTMLElement)) {
      throw new Error("Expected roster row to be focusable");
    }

    element.focus({ preventScroll: true });
    const cogId = element.dataset.cogId;
    if (!cogId) {
      throw new Error("Expected roster row to include a cog id");
    }

    return cogId;
  });
}

async function readTick(tickRow: Locator): Promise<number> {
  const text = await tickRow.textContent();
  const value = text?.match(/\d+/)?.[0];
  if (!value) {
    throw new Error(`Unable to read tick from ${text ?? "empty HUD row"}`);
  }

  return Number.parseInt(value, 10);
}

async function readWorldTick(page: Page): Promise<number> {
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  return snapshot.tick;
}

async function cogConversationLogLength(page: Page, cogId: string): Promise<number> {
  const snapshot = (await (await page.request.get("/api/world")).json()) as SmokeSnapshot;
  return snapshot.cogs.find((cog) => cog.id === cogId)?.conversationLog?.length ?? 0;
}

function waitForVenueEditorAutosave(page: Page) {
  return page.waitForResponse(
    (response) => response.url().endsWith("/api/venue-editor") && response.request().method() === "PUT",
    { timeout: 5_000 },
  );
}

function parseSpotPosition(position: string | null): SmokePosition {
  if (!position) {
    throw new Error("Expected spot position");
  }
  const [x, y] = position.split(",").map((part) => Number(part));
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    throw new Error(`Invalid spot position ${position}`);
  }
  return { x, y };
}

async function readTickSection(section: Locator): Promise<number> {
  const tick = await section.getAttribute("data-tick");
  if (!tick) {
    throw new Error("Unable to read tick section");
  }

  return Number.parseInt(tick, 10);
}

async function subsectionOrder(section: Locator): Promise<string[]> {
  return section.locator(".log-subsection").evaluateAll((elements) =>
    elements.map((element) => element.getAttribute("data-log-subsection") ?? ""),
  );
}

async function expectOverlayItemOverMap(canvas: Locator, item: Locator): Promise<void> {
  const canvasBox = await canvas.boundingBox();
  const itemBox = await item.boundingBox();
  if (!canvasBox || !itemBox) {
    throw new Error("Unable to inspect overlay item and canvas layout");
  }

  expect(itemBox.x).toBeGreaterThanOrEqual(canvasBox.x);
  expect(itemBox.y).toBeGreaterThanOrEqual(canvasBox.y);
  expect(itemBox.x + itemBox.width).toBeLessThanOrEqual(canvasBox.x + canvasBox.width);
  expect(itemBox.y + itemBox.height).toBeLessThanOrEqual(canvasBox.y + canvasBox.height);
}

function findPositionOutsideRoomRects(
  rooms: Array<{ rect?: { x: number; y: number; width: number; height: number } }>,
  dimensions: { width: number; height: number },
): SmokePosition {
  for (let y = 0; y < dimensions.height; y += 1) {
    for (let x = 0; x < dimensions.width; x += 1) {
      const position = { x, y };
      if (rooms.every((room) => !room.rect || !isPositionInsideRect(position, room.rect))) {
        return position;
      }
    }
  }

  throw new Error("Expected at least one position outside all room rectangles");
}

function isPositionInsideRect(
  position: SmokePosition,
  rect: { x: number; y: number; width: number; height: number },
): boolean {
  return (
    position.x >= rect.x &&
    position.x <= rect.x + rect.width &&
    position.y >= rect.y &&
    position.y <= rect.y + rect.height
  );
}

async function clickVenueBoardPosition(
  page: Page,
  position: SmokePosition,
  dimensions: { width: number; height: number },
): Promise<void> {
  const board = page.locator("[data-board]");
  const boardBox = await board.boundingBox();
  if (!boardBox) {
    throw new Error("Expected venue board bounding box");
  }

  await page.mouse.click(
    boardBox.x + ((position.x + 0.5) / dimensions.width) * boardBox.width,
    boardBox.y + ((position.y + 0.5) / dimensions.height) * boardBox.height,
  );
}

async function moveVenueBoardPosition(
  page: Page,
  position: SmokePosition,
  dimensions: { width: number; height: number },
): Promise<void> {
  const board = page.locator("[data-board]");
  const boardBox = await board.boundingBox();
  if (!boardBox) {
    throw new Error("Expected venue board bounding box");
  }

  await page.mouse.move(
    boardBox.x + ((position.x + 0.5) / dimensions.width) * boardBox.width,
    boardBox.y + ((position.y + 0.5) / dimensions.height) * boardBox.height,
  );
}

function findKeyboardMoveTarget(snapshot: SmokeSnapshot): KeyboardMoveTarget {
  const moves = [
    { key: "w", delta: { x: 0, y: -1 } },
    { key: "a", delta: { x: -1, y: 0 } },
    { key: "s", delta: { x: 0, y: 1 } },
    { key: "d", delta: { x: 1, y: 0 } },
  ];

  for (const cog of snapshot.cogs) {
    if (cog.debate) {
      continue;
    }

    for (const move of moves) {
      const expectedPosition = {
        x: cog.position.x + move.delta.x,
        y: cog.position.y + move.delta.y,
      };
      if (isOpenMoveDestination(snapshot, cog.id, expectedPosition)) {
        return { cog, expectedPosition, key: move.key };
      }
    }
  }

  throw new Error("Expected at least one cog with an open keyboard move");
}

async function expandRosterCog(roster: Locator): Promise<ExpandedRosterCog> {
  const rows = roster.locator(".cog-row[data-cog-id]");
  const rowCount = await rows.count();

  for (let index = 0; index < rowCount; index += 1) {
    const row = rows.nth(index);
    const cogId = await row.getAttribute("data-cog-id");
    if (!cogId) {
      continue;
    }

    await row.click();
    const panel = roster.locator(`.cog-choice-panel[data-cog-id="${cogId}"]`);
    await expect(panel).toBeVisible();

    return { cogId, panel };
  }

  throw new Error("Expected at least one expanded roster cog");
}

function isOpenMoveDestination(snapshot: SmokeSnapshot, cogId: string, position: SmokePosition): boolean {
  if (
    position.x < 0 ||
    position.y < 0 ||
    position.x >= snapshot.dimensions.width ||
    position.y >= snapshot.dimensions.height
  ) {
    return false;
  }

  if (snapshot.terrain.some((cell) => cell.terrain === "wall" && samePosition(cell.position, position))) {
    return false;
  }

  if (snapshot.cogs.some((cog) => cog.id !== cogId && samePosition(cog.position, position))) {
    return false;
  }

  return !snapshot.objects.some((object) => samePosition(object.position, position));
}

function samePosition(left: SmokePosition, right: SmokePosition): boolean {
  return left.x === right.x && left.y === right.y;
}

async function expectDedicatedRightPanel(canvas: Locator, roster: Locator): Promise<void> {
  const canvasBox = await canvas.boundingBox();
  const rosterBox = await roster.boundingBox();

  if (!canvasBox || !rosterBox) {
    throw new Error("Unable to inspect canvas and roster layout");
  }

  expect(canvasBox.x + canvasBox.width).toBeLessThanOrEqual(rosterBox.x + 1);
}
