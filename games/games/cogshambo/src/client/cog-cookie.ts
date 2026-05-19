const COG_ID_COOKIE_NAME = "cogshambo_cog_id";
const COG_ID_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;
export const COG_ID_COOKIE_CLAIM_PARAM = "setCogCookie";

export function readCogIdCookie(): string | undefined {
  const prefix = `${COG_ID_COOKIE_NAME}=`;
  const entry = document.cookie
    .split(";")
    .map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith(prefix));
  const encodedCogId = entry?.slice(prefix.length);
  if (!encodedCogId) {
    return undefined;
  }

  try {
    return decodeURIComponent(encodedCogId);
  } catch {
    return undefined;
  }
}

export function setCogIdCookie(cogId: string): void {
  document.cookie = `${COG_ID_COOKIE_NAME}=${encodeURIComponent(
    cogId,
  )}; Max-Age=${COG_ID_COOKIE_MAX_AGE_SECONDS}; Path=/; SameSite=Lax`;
}

export function clearCogIdCookie(): void {
  document.cookie = `${COG_ID_COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax`;
}
