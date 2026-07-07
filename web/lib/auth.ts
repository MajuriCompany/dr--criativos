// Single shared-password gate — no per-user accounts, no signed sessions.
// Acceptable for this threat model: a small trusted team, everyone shares
// one login and one MiniMax/ElevenLabs balance. The cookie's value is
// compared directly against APP_PASSWORD server-side.

export const SESSION_COOKIE = "panel_session";

export function checkPassword(candidate: string): boolean {
  const expected = process.env.APP_PASSWORD;
  if (!expected) {
    throw new Error("APP_PASSWORD not set");
  }
  return candidate === expected;
}

export function isValidSessionCookie(value: string | undefined): boolean {
  if (!value) return false;
  const expected = process.env.APP_PASSWORD;
  if (!expected) return false;
  return value === expected;
}
