import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import { builderQrUrl, profileQrUrl, renderBuilderQrCard, renderQrSvg } from "../../src/client/ui/builder-qr";

const styles = readFileSync(new URL("../../src/client/ui/styles.css", import.meta.url), "utf8");

describe("builder QR", () => {
  it("points localhost scans at the public builder URL", () => {
    const url = builderQrUrl("http://127.0.0.1:6060/?profile=cog-1&foo=bar#details");

    expect(url).toBe("https://redvblue.dbloom.in/builder?foo=bar");
  });

  it("keeps deployed origins and removes non-builder page modes", () => {
    const url = builderQrUrl("https://venue.example.com/show?config=1&profile=cog-2");

    expect(url).toBe("https://venue.example.com/builder");
  });

  it("points profile QR scans at the public profile claim URL", () => {
    const url = profileQrUrl("cog-1", "http://127.0.0.1:6060/?profile=cog-2&foo=bar#details");

    expect(url).toBe("https://redvblue.dbloom.in/profile/cog-1?setCogCookie=1");
  });

  it("renders a scannable QR card link", () => {
    const markup = renderBuilderQrCard("https://redvblue.dbloom.in/builder");

    expect(markup).toContain('class="builder-qr-card"');
    expect(markup).toContain('href="https://redvblue.dbloom.in/builder"');
    expect(markup).toContain('data-action="open-builder-window"');
    expect(markup).toContain("Make a cog");
    expect(markup).toContain("<svg");
  });

  it("renders QR module paths without leaking raw data into the SVG", () => {
    const markup = renderQrSvg('https://redvblue.dbloom.in/builder?name=<Ada "One">');

    expect(markup).toContain('class="builder-qr-code"');
    expect(markup).toContain("<path");
    expect(markup).not.toContain("<Ada");
  });

  it("anchors the QR card beside the roster and above the event ticker", () => {
    const desktopBlock = cssBlock(".builder-qr-card");
    const noRosterBlock = cssBlock("#app:not(:has(.right-panel)) .builder-qr-card");
    const mobileBlock = cssBlock(".builder-qr-card", styles.indexOf("@media (max-width: 760px)"));

    expect(desktopBlock).toContain("bottom: 64px;");
    expect(desktopBlock).toContain("right: calc(clamp(220px, 28vw, 360px) + 14px);");
    expect(desktopBlock).not.toContain("left:");
    expect(noRosterBlock).toContain("right: 14px;");
    expect(mobileBlock).toContain("bottom: 54px;");
    expect(mobileBlock).toContain("right: 10px;");
    expect(mobileBlock).not.toContain("left:");
  });
});

function cssBlock(selector: string, startIndex = 0): string {
  const match = styles.slice(startIndex).match(new RegExp(`${escapeRegExp(selector)}\\s*\\{[\\s\\S]*?\\n\\s*\\}`));
  expect(match).toBeTruthy();
  return match?.[0] ?? "";
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
