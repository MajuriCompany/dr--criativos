"use client";

import { useState } from "react";
import { useJobStatus } from "@/lib/useJobStatus";
import type { Voice } from "@/app/api/catalog/route";
import JobStatusPanel from "./JobStatusPanel";

const inputClass =
  "w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-orange-500 focus:ring-4 focus:ring-orange-500/20";

export default function ManageVoices({ voices, onAdded }: { voices: Voice[]; onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
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

  async function deleteVoice(id: string) {
    setDeletingId(id);
    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "delete_voice", params: { delete_voice_id: id } }),
      });
      const created = await res.json();
      setJobId(created.id);
      setConfirmDeleteId(null);
      onAdded();
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="mb-4 rounded-xl border border-slate-700 bg-slate-950/40 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-2 text-left text-xs font-medium text-slate-400"
      >
        {open ? "▾" : "▸"} gerenciar vozes
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-700 p-3">
          {voices.length > 0 && (
            <ul className="space-y-1">
              {voices.map((v) => (
                <li
                  key={v.voice_id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm"
                >
                  {confirmDeleteId === v.voice_id ? (
                    <>
                      <span className="text-xs text-amber-400">Tem certeza, chapa?</span>
                      <span className="flex shrink-0 gap-2">
                        <button
                          type="button"
                          onClick={() => deleteVoice(v.voice_id)}
                          disabled={deletingId === v.voice_id}
                          className="rounded-lg bg-red-600 px-2 py-1 text-xs font-medium text-white transition hover:bg-red-500 disabled:opacity-50"
                        >
                          {deletingId === v.voice_id ? "excluindo..." : "sim, excluir"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-400 transition hover:bg-slate-800"
                        >
                          cancelar
                        </button>
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="truncate text-slate-200">{v.name}</span>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(v.voice_id)}
                        className="shrink-0 text-xs text-slate-500 transition hover:text-red-400"
                      >
                        excluir
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}

          <div className="space-y-2 border-t border-slate-800 pt-3">
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
              className="rounded-lg bg-orange-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-orange-500 disabled:opacity-50"
            >
              {submitting ? "Adicionando..." : "Adicionar voz"}
            </button>
            <p className="text-xs text-slate-500">
              No painel MiniMax: abra a voz em &quot;Voice Mixing&quot;, copie o voice_id ao lado do
              nome, e cole aqui.
            </p>
          </div>

          <JobStatusPanel job={job} />
        </div>
      )}
    </div>
  );
}
