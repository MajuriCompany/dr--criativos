import { NextResponse } from "next/server";
import { redis } from "@/lib/upstash";
import { requireSession } from "@/lib/auth";

// Signals the local worker to rescan edicao-videos/ on its next poll
// (<=10s) instead of waiting for the idle 60s auto-rescan. The worker
// clears this key itself once it's honored the request.
export async function POST() {
  const unauthorized = await requireSession();
  if (unauthorized) return unauthorized;

  await redis.set("catalog:refresh_requested", Date.now().toString());
  return NextResponse.json({ ok: true });
}
