import { NextResponse } from "next/server";
import { getJob } from "@/lib/jobs";
import { requireSession } from "@/lib/auth";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const unauthorized = await requireSession();
  if (unauthorized) return unauthorized;

  const { id } = await params;
  const job = await getJob(id);
  if (!job) {
    return NextResponse.json({ error: "job não encontrado" }, { status: 404 });
  }
  return NextResponse.json(job);
}
