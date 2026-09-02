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
  pending: "text-slate-400",
  running: "text-orange-400",
  done: "text-emerald-400",
  error: "text-red-400",
};

const STATUS_BORDER: Record<Job["status"], string> = {
  pending: "border-slate-700",
  running: "border-orange-700",
  done: "border-emerald-800",
  error: "border-red-900",
};

const STATUS_BG: Record<Job["status"], string> = {
  pending: "bg-slate-900/80",
  running: "bg-orange-950/40",
  done: "bg-emerald-950/30",
  error: "bg-red-950/30",
};

export default function JobStatusPanel({ job }: { job: Job | null }) {
  const [showDetail, setShowDetail] = useState(false);

  if (!job) return null;

  return (
    <div
      className={`mt-4 rounded-2xl border ${STATUS_BORDER[job.status]} ${STATUS_BG[job.status]} p-4 text-sm`}
    >
      <p className={`font-medium ${STATUS_COLOR[job.status]}`}>
        {STATUS_LABEL[job.status]}
        {job.progress?.message ? ` — ${job.progress.message}` : ""}
      </p>

      {job.result?.artifacts && job.result.artifacts.length > 0 && (
        <div className="mt-2">
          <p className="text-slate-500">Arquivos gerados (no seu PC):</p>
          <ul className="mt-1 list-disc pl-5 font-mono text-xs text-slate-300">
            {job.result.artifacts.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {job.error && (
        <div className="mt-2">
          <p className="text-red-400">{job.error.message}</p>
          <button
            onClick={() => setShowDetail((v) => !v)}
            className="mt-1 text-xs text-slate-500 underline"
          >
            {showDetail ? "ocultar detalhes técnicos" : "ver detalhes técnicos"}
          </button>
          {showDetail && (
            <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-slate-950 p-2 text-xs text-slate-400">
              {job.error.detail}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
