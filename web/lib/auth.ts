// Single shared-password gate — no per-user accounts, no signed sessions.
// Acceptable for this threat model: a small trusted team, everyone shares
// one login and one MiniMax/ElevenLabs balance. The cookie's value is
// compared directly against APP_PASSWORD server-side.
//
// Auth is checked per-route/per-page (not via a central middleware/proxy.ts)
// after Edge Middleware was suspected of causing 404s at Vercel's routing
// layer for this project — every route below calls requireSession() itself.

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const SESSION_COOKIE = "panel_session";

export async function requireSession(): Promise<NextResponse | null> {
  const store = await cookies();
  const value = store.get(SESSION_COOKIE)?.value;
  if (!isValidSessionCookie(value)) {
    return NextResponse.json({ error: "não autenticado" }, { status: 401 });
  }
  return null;
}

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
