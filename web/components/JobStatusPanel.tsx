"use client";

import { useState } from "react";
import type { Job } from "@/lib/jobs";

const STATUS_LABEL: Record<Job["status"], string> = {
  pending: "Na fila, aguardando o worker local...",
  running: "Processando...",
  done: "Concluído",
  error: "Erro",
};

const STATUS_COLOR: Record<Job["status"], string> = {
  pending: "text-gray-500",
  running: "text-blue-600",
  done: "text-green-600",
  error: "text-red-600",
};

export default function JobStatusPanel({ job }: { job: Job | null }) {
  const [showDetail, setShowDetail] = useState(false);

  if (!job) return null;

  return (
    <div className="mt-4 rounded border border-gray-200 dark:border-gray-800 p-4 text-sm">
      <p className={`font-medium ${STATUS_COLOR[job.status]}`}>
        {STATUS_LABEL[job.status]}
        {job.progress?.message ? ` — ${job.progress.message}` : ""}
      </p>

      {job.result?.artifacts && job.result.artifacts.length > 0 && (
        <div className="mt-2">
          <p className="text-gray-500 dark:text-gray-400">Arquivos gerados (no seu PC):</p>
          <ul className="mt-1 list-disc pl-5 font-mono text-xs text-gray-700 dark:text-gray-300">
            {job.result.artifacts.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {job.error && (
        <div className="mt-2">
          <p className="text-red-600">{job.error.message}</p>
          <button
            onClick={() => setShowDetail((v) => !v)}
            className="mt-1 text-xs text-gray-500 underline"
          >
            {showDetail ? "ocultar detalhes técnicos" : "ver detalhes técnicos"}
          </button>
          {showDetail && (
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-gray-100 dark:bg-gray-900 p-2 text-xs text-gray-600 dark:text-gray-400">
              {job.error.detail}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
