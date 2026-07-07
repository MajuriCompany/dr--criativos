import { Redis } from "@upstash/redis";

// The Vercel Storage integration (Upstash marketplace add-on) names its
// vars KV_REST_API_URL / KV_REST_API_TOKEN, not the UPSTASH_REDIS_REST_*
// names Redis.fromEnv() looks for by default — so construct explicitly.
export const redis = new Redis({
  url: process.env.KV_REST_API_URL!,
  token: process.env.KV_REST_API_TOKEN!,
});
// redeploy trigger Tue Jul  7 12:24:20     2026
