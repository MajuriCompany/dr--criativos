"use client";

import { useState } from "react";
import { useJobStatus } from "@/lib/useJobStatus";
import JobStatusPanel from "./JobStatusPanel";

const inputClass =
  "w-full rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100";

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
    <div className="mb-4 rounded border border-gray-200 dark:border-gray-800">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-2 text-left text-xs font-medium text-gray-600 dark:text-gray-400"
      >
        {open ? "▾" : "▸"} adicionar nova voz
      </button>
      {open && (
        <div className="space-y-2 border-t border-gray-200 dark:border-gray-800 p-3">
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
            className="rounded bg-gray-900 dark:bg-gray-100 px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 disabled:opacity-50"
          >
            {submitting ? "Adicionando..." : "Adicionar voz"}
          </button>
          <p className="text-xs text-gray-500">
            No painel MiniMax: abra a voz em &quot;Voice Mixing&quot;, copie o voice_id ao lado do
            nome, e cole aqui.
          </p>
          <JobStatusPanel job={job} />
        </div>
      )}
    </div>
  );
}
