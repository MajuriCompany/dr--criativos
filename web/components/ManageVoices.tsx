"use client";

import { useState } from "react";
import { useJobStatus } from "@/lib/useJobStatus";
import JobStatusPanel from "./JobStatusPanel";

const inputClass =
  "w-full rounded-lg border border-blue-200 dark:border-blue-900 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-blue-950 dark:text-blue-50 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/15";

export default function ManageVoices({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const job = useJobStatus(jobId);

  async function addVoice() {
    setSubmitting(true);
    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "add_voice",
          params: { voice: { name: name.trim(), voice_id: voiceId.trim() } },
        }),
      });
      const created = await res.json();
      setJobId(created.id);
      setName("");
      setVoiceId("");
      onAdded();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mb-4 rounded-xl border border-blue-100 dark:border-blue-900/60 bg-white/60 dark:bg-slate-900/40 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-2 text-left text-xs font-medium text-blue-900/60 dark:text-blue-300/60"
      >
        {open ? "▾" : "▸"} adicionar nova voz
      </button>
      {open && (
        <div className="space-y-2 border-t border-blue-100 dark:border-blue-900/60 p-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nome (ex. Voz Homem Grave)"
            className={inputClass}
          />
          <input
            value={voiceId}
            onChange={(e) => setVoiceId(e.target.value)}
            placeholder="voice_id (copiado do painel MiniMax)"
            className={inputClass}
          />
          <button
            type="button"
            onClick={addVoice}
            disabled={!name.trim() || !voiceId.trim() || submitting}
            className="rounded-lg bg-gradient-to-r from-blue-600 to-blue-700 px-3 py-1.5 text-xs font-medium text-white shadow-md shadow-blue-600/25 transition hover:from-blue-500 hover:to-blue-600 disabled:opacity-50 disabled:shadow-none"
          >
            {submitting ? "Adicionando..." : "Adicionar voz"}
          </button>
          <p className="text-xs text-blue-900/50 dark:text-blue-300/50">
            No painel MiniMax: abra a voz em &quot;Voice Mixing&quot;, copie o voice_id ao lado do
            nome, e cole aqui.
          </p>
          <JobStatusPanel job={job} />
        </div>
      )}
    </div>
  );
}
