import { NextResponse } from "next/server";
import { redis } from "@/lib/upstash";

export interface Voice {
  name: string;
  voice_id: string;
  created: string;
}

// Read-only view of what the local worker last reported. Vercel never
// touches the filesystem directly — this is just whatever the worker last
// pushed to catalog:* keys.
export async function GET() {
  const [ads, experts, voices, updatedAt] = await Promise.all([
    redis.get<string[]>("catalog:ads"),
    redis.get<string[]>("catalog:experts"),
    redis.get<Voice[]>("catalog:voices"),
    redis.get<string>("catalog:updated_at"),
  ]);

  return NextResponse.json({
    ads: ads ?? [],
    experts: experts ?? [],
    voices: voices ?? [],
    updated_at: updatedAt ?? null,
  });
}
