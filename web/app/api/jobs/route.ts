import { NextRequest, NextResponse } from "next/server";
import { createJob, listRecentJobs, JobType, JobParams } from "@/lib/jobs";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { type, params } = body as { type: JobType; params: JobParams };

  if (!type || !["tts", "cut_silence", "sync", "pipeline"].includes(type)) {
    return NextResponse.json({ error: "tipo de job inválido" }, { status: 400 });
  }

  const job = await createJob(type, params);
  return NextResponse.json(job);
}

export async function GET() {
  const jobs = await listRecentJobs();
  return NextResponse.json(jobs);
}
