import { redis } from "./upstash";

export type JobType = "tts" | "cut_silence" | "sync" | "pipeline";
export type JobStatus = "pending" | "running" | "done" | "error";

export interface JobParams {
  ad_folder?: string;
  audio_filename?: string;
  expert_folder?: string;
  sync_source?: string;
  tts?: {
    text: string;
    voice_id: string;
    speed: number;
    emotion?: string;
    filename?: string;
  };
}

export interface Job {
  id: string;
  type: JobType;
  status: JobStatus;
  created_at: string;
  updated_at?: string;
  params: JobParams;
  progress?: { step: string; message: string };
  result?: { artifacts: string[] };
  error?: { step: string; message: string; detail: string };
}

const RECENT_CAP = 20;

function newJobId(): string {
  return `job_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
}

export async function createJob(type: JobType, params: JobParams): Promise<Job> {
  const job: Job = {
    id: newJobId(),
    type,
    status: "pending",
    created_at: new Date().toISOString(),
    params,
  };
  await redis.set(`job:${job.id}`, JSON.stringify(job));
  await redis.rpush("jobs:queue", job.id);
  return job;
}

export async function getJob(id: string): Promise<Job | null> {
  const raw = await redis.get<string | Job>(`job:${id}`);
  if (!raw) return null;
  // @upstash/redis auto-parses JSON-looking strings for some clients; handle both shapes.
  return typeof raw === "string" ? (JSON.parse(raw) as Job) : (raw as Job);
}

export async function listRecentJobs(): Promise<Job[]> {
  const ids = await redis.lrange("jobs:recent", 0, RECENT_CAP - 1);
  const jobs = await Promise.all(ids.map((id) => getJob(id)));
  return jobs.filter((j): j is Job => j !== null);
}
