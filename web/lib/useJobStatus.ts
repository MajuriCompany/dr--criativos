"use client";

import { useEffect, useState } from "react";
import type { Job } from "./jobs";

// Plain polling, not SWR/react-query — this only runs while a human is
// watching one active job, so there's no cache-sharing need to justify the
// extra dependency.
export function useJobStatus(jobId: string | null): Job | null {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let stopped = false;

    async function tick() {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) return;
      const data: Job = await res.json();
      if (stopped) return;
      setJob(data);
      if (data.status === "pending" || data.status === "running") {
        setTimeout(tick, 2000);
      }
    }

    tick();
    return () => {
      stopped = true;
    };
  }, [jobId]);

  return job;
}
