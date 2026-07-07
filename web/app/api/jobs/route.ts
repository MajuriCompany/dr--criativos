import { NextRequest, NextResponse } from "next/server";
import { createJob, listRecentJobs, JobType, JobParams } from "@/lib/jobs";
import { requireSession } from "@/lib/auth";

export async function POST(req: NextRequest) {
  const unauthorized = await requireSession();
  if (unauthorized) return unauthorized;

  const body = await req.json();
  const { type, params } = body as { type: JobType; params: JobParams };

  if (!type || !["tts", "cut_silence", "sync", "pipeline", "add_voice"].includes(type)) {
    return NextResponse.json({ error: "tipo de job inválido" }, { status: 400 });
  }

  const job = await createJob(type, params);
  return NextResponse.json(job);
}

export async function GET() {
  const unauthorized = await requireSession();
  if (unauthorized) return unauthorized;

  const jobs = await listRecentJobs();
  return NextResponse.json(jobs);
}
