"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useCatalog } from "@/lib/useCatalog";
import { useJobStatus } from "@/lib/useJobStatus";
import type { JobType } from "@/lib/jobs";
import JobStatusPanel from "./JobStatusPanel";
import AudioFilePicker from "./AudioFilePicker";
import SubfolderPicker from "./SubfolderPicker";
import ManageVoices from "./ManageVoices";

const EMOTIONS = ["happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent", "whisper"];

const TABS: { id: JobType; label: string }[] = [
  { id: "tts", label: "Gerar Áudio" },
  { id: "cut_silence", label: "Cortar Silêncio" },
  { id: "sync", label: "Sincronizar" },
  { id: "pipeline", label: "Fluxo Completo" },
];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">{label}</span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100";

export default function Dashboard() {
  const router = useRouter();
  const catalog = useCatalog();
  const [tab, setTab] = useState<JobType>("tts");
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJobStatus(jobId);

  const [adFolder, setAdFolder] = useState("");
  const [newAdFolder, setNewAdFolder] = useState(false);
  const [expertFolder, setExpertFolder] = useState("");
  const [audioFilename, setAudioFilename] = useState("");
  const [pipelineSubfolder, setPipelineSubfolder] = useState("");
  const [ttsFilename, setTtsFilename] = useState("");
  const [text, setText] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [speed, setSpeed] = useState(1.0);
  const [emotion, setEmotion] = useState("fluent");
  const [confirmedTts, setConfirmedTts] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const effectiveAdFolder = newAdFolder ? adFolder.trim() : adFolder;
  const audioTreeInFolder = catalog.ad_tree[effectiveAdFolder] ?? { files: [], dirs: {} };

  async function submit(type: JobType) {
    setSubmitting(true);
    try {
      const params: Record<string, unknown> = { ad_folder: effectiveAdFolder };
      if (type === "cut_silence" || type === "sync") {
        params.audio_filename = audioFilename;
      }
      if (type === "tts" || type === "pipeline") {
        params.tts = { text, voice_id: voiceId, speed, emotion, filename: ttsFilename.trim() };
      }
      if (type === "sync" || type === "pipeline") {
        params.expert_folder = expertFolder;
      }
      if (type === "pipeline") {
        params.subfolder = pipelineSubfolder.trim();
      }

      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, params }),
      });
      const created = await res.json();
      setJobId(created.id);
    } finally {
      setSubmitting(false);
    }
  }

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    router.push("/login");
  }

  const needsTts = tab === "tts" || tab === "pipeline";
  const needsExpert = tab === "sync" || tab === "pipeline";
  const needsAudioFilename = tab === "cut_silence" || tab === "sync";
  const canSubmit =
    !!effectiveAdFolder &&
    (!needsTts || (text.trim() && voiceId && ttsFilename.trim())) &&
    (!needsExpert || expertFolder) &&
    (!needsAudioFilename || audioFilename) &&
    (tab !== "tts" || true) &&
    (!needsTts || confirmedTts || tab !== "pipeline"); // confirm gate only enforced on the no-pause combined flow

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Painel de Corte e Sincronização
        </h1>
        <div className="flex items-center gap-3">
          <button
            onClick={() => catalog.refresh()}
            disabled={catalog.refreshing}
            className="text-xs text-gray-500 underline disabled:opacity-50"
          >
            {catalog.refreshing ? "atualizando..." : "atualizar catálogo"}
          </button>
          <button onClick={logout} className="text-xs text-gray-500 underline">
            sair
          </button>
        </div>
      </div>

      {catalog.updated_at === null && (
        <p className="mb-4 rounded bg-yellow-50 dark:bg-yellow-950 p-2 text-xs text-yellow-700 dark:text-yellow-400">
          Catálogo ainda não recebido do worker local — confirme que o worker está rodando
          (start_worker.bat) e aguarde ele reportar as pastas/vozes.
        </p>
      )}

      <div className="mb-4 flex gap-1 border-b border-gray-200 dark:border-gray-800">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => {
              setTab(t.id);
              setJobId(null);
            }}
            className={`px-3 py-2 text-sm ${
              tab === t.id
                ? "border-b-2 border-gray-900 dark:border-gray-100 font-medium text-gray-900 dark:text-gray-100"
                : "text-gray-500"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        <Field label="Pasta do anúncio">
          <div className="flex gap-2">
            {!newAdFolder ? (
              <select
                value={adFolder}
                onChange={(e) => setAdFolder(e.target.value)}
                className={inputClass}
              >
                <option value="">selecione...</option>
                {catalog.ads.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            ) : (
              <input
                value={adFolder}
                onChange={(e) => setAdFolder(e.target.value)}
                placeholder="ex. ad03"
                className={inputClass}
              />
            )}
            <button
              type="button"
              onClick={() => setNewAdFolder((v) => !v)}
              className="whitespace-nowrap rounded border border-gray-300 dark:border-gray-700 px-2 text-xs text-gray-600 dark:text-gray-400"
            >
              {newAdFolder ? "escolher existente" : "nova pasta"}
            </button>
          </div>
        </Field>

        {tab === "pipeline" && (
          <Field label="Subpasta de destino (opcional)">
            {effectiveAdFolder ? (
              <SubfolderPicker
                tree={audioTreeInFolder}
                value={pipelineSubfolder}
                onChange={setPipelineSubfolder}
              />
            ) : (
              <p className="text-xs text-gray-500">escolha a pasta do anúncio primeiro</p>
            )}
            <p className="mt-1 text-xs text-gray-500">
              O áudio gerado, o cortado ({"{nome}"}_CORTADO) e o vídeo sincronizado
              ({"{nome}"}_SINCRONIZADO) caem todos direto aqui dentro.
            </p>
          </Field>
        )}

        {needsAudioFilename && (
          <Field label={tab === "sync" ? "Áudio a sincronizar" : "Arquivo de áudio a cortar"}>
            {effectiveAdFolder ? (
              <AudioFilePicker
                tree={audioTreeInFolder}
                value={audioFilename}
                onChange={setAudioFilename}
              />
            ) : (
              <p className="text-xs text-gray-500">escolha a pasta do anúncio primeiro</p>
            )}
            {tab === "sync" && (
              <p className="mt-1 text-xs text-gray-500">
                Se esse áudio ainda não foi cortado, o sistema corta o silêncio automaticamente
                antes de sincronizar. Se já foi cortado antes, reaproveita o corte existente.
              </p>
            )}
          </Field>
        )}

        {needsTts && (
          <>
            <Field label="Nome do arquivo de áudio a gerar">
              <input
                value={ttsFilename}
                onChange={(e) => setTtsFilename(e.target.value)}
                placeholder="ex. roteiro_v1"
                className={inputClass}
              />
            </Field>
            <Field label="Texto">
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={5}
                className={inputClass}
              />
            </Field>
            <Field label="Voz">
              <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)} className={inputClass}>
                <option value="">selecione...</option>
                {catalog.voices.map((v) => (
                  <option key={v.voice_id} value={v.voice_id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </Field>
            <ManageVoices onAdded={() => catalog.refresh()} />
            <div className="flex gap-3">
              <Field label={`Velocidade (${speed.toFixed(2)}x)`}>
                <input
                  type="range"
                  min={0.5}
                  max={2}
                  step={0.05}
                  value={speed}
                  onChange={(e) => setSpeed(parseFloat(e.target.value))}
                  className="w-full"
                />
              </Field>
              <Field label="Entonação">
                <select value={emotion} onChange={(e) => setEmotion(e.target.value)} className={inputClass}>
                  {EMOTIONS.map((e) => (
                    <option key={e} value={e}>
                      {e}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </>
        )}

        {needsExpert && (
          <Field label="Expert / avatar">
            <select value={expertFolder} onChange={(e) => setExpertFolder(e.target.value)} className={inputClass}>
              <option value="">selecione...</option>
              {catalog.experts.map((ex) => (
                <option key={ex} value={ex}>
                  {ex}
                </option>
              ))}
            </select>
          </Field>
        )}

        {tab === "pipeline" && needsTts && (
          <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
            <input
              type="checkbox"
              checked={confirmedTts}
              onChange={(e) => setConfirmedTts(e.target.checked)}
            />
            Confirmo a voz/velocidade/entonação acima — o fluxo completo roda direto até o final,
            sem pausar, então uma escolha errada aqui só aparece no vídeo pronto.
          </label>
        )}

        <button
          onClick={() => submit(tab)}
          disabled={!canSubmit || submitting}
          className="w-full rounded bg-gray-900 dark:bg-gray-100 px-3 py-2 text-sm font-medium text-white dark:text-gray-900 disabled:opacity-50"
        >
          {submitting ? "Enviando..." : "Executar"}
        </button>
      </div>

      <JobStatusPanel job={job} />
    </div>
  );
}
