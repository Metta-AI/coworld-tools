import qrcode from "qrcode-generator";

import { COG_ID_COOKIE_CLAIM_PARAM } from "../cog-cookie";
import { escapeHtml } from "./html";

const PUBLIC_APP_ORIGIN = "https://redvblue.dbloom.in";

export function builderQrUrl(currentHref = fallbackCurrentHref()): string {
  const currentUrl = new URL(currentHref);
  const builderUrl = isLocalHost(currentUrl.hostname)
    ? new URL(PUBLIC_APP_ORIGIN)
    : new URL(currentUrl.origin);

  builderUrl.pathname = "/builder";
  builderUrl.search = currentUrl.search;
  builderUrl.hash = "";
  builderUrl.searchParams.delete("builder");
  builderUrl.searchParams.delete("config");
  builderUrl.searchParams.delete("profile");
  builderUrl.searchParams.delete("editor");
  builderUrl.searchParams.delete(COG_ID_COOKIE_CLAIM_PARAM);

  return builderUrl.toString();
}

export function profileQrUrl(cogId: string, currentHref = fallbackCurrentHref()): string {
  const currentUrl = new URL(currentHref);
  const profileUrl = isLocalHost(currentUrl.hostname)
    ? new URL(PUBLIC_APP_ORIGIN)
    : new URL(currentUrl.origin);

  profileUrl.pathname = `/profile/${encodeURIComponent(cogId)}`;
  profileUrl.search = "";
  profileUrl.hash = "";
  profileUrl.searchParams.set(COG_ID_COOKIE_CLAIM_PARAM, "1");

  return profileUrl.toString();
}

export function renderBuilderQrCard(href = builderQrUrl()): string {
  return `
    <a
      aria-label="Make a cog"
      class="builder-qr-card"
      href="${escapeHtml(href)}"
      target="cogshambo-cog-builder"
      title="Make a cog"
      data-action="open-builder-window"
    >
      <span>Make a cog</span>
      ${renderQrSvg(href)}
    </a>
  `;
}

export function renderQrSvg(data: string, className = "builder-qr-code"): string {
  const qr = qrcode(0, "M");
  qr.addData(data);
  qr.make();

  const moduleCount = qr.getModuleCount();
  const margin = 3;
  const viewBoxSize = moduleCount + margin * 2;
  const darkModules: string[] = [];

  for (let row = 0; row < moduleCount; row += 1) {
    for (let col = 0; col < moduleCount; col += 1) {
      if (qr.isDark(row, col)) {
        darkModules.push(`M${col + margin} ${row + margin}h1v1h-1z`);
      }
    }
  }

  return `
    <svg aria-hidden="true" class="${escapeHtml(className)}" focusable="false" viewBox="0 0 ${viewBoxSize} ${viewBoxSize}">
      <rect fill="#ffffff" height="${viewBoxSize}" width="${viewBoxSize}" x="0" y="0"></rect>
      <path d="${darkModules.join("")}" fill="#101314"></path>
    </svg>
  `;
}

function fallbackCurrentHref(): string {
  return typeof window === "undefined" ? `${PUBLIC_APP_ORIGIN}/` : window.location.href;
}

function isLocalHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}
