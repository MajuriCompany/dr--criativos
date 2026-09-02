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
      <span className="mb-1.5 block text-xs font-semibold tracking-wide text-slate-400">{label}</span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/20";

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
  const [generateCapcutDraft, setGenerateCapcutDraft] = useState(true);
  const [capcutMode, setCapcutMode] = useState<"new" | "append">("new");
  const [capcutAppendTo, setCapcutAppendTo] = useState("");
  const [cutAlsoSync, setCutAlsoSync] = useState(false);
  const [syncSource, setSyncSource] = useState<"audio" | "capcut">("audio");
  const [syncCapcutDraft, setSyncCapcutDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const effectiveAdFolder = newAdFolder ? adFolder.trim() : adFolder;
  const audioTreeInFolder = catalog.ad_tree[effectiveAdFolder] ?? { files: [], dirs: {} };

  async function submit(tabType: JobType) {
    setSubmitting(true);
    try {
      // "Cortar Silêncio" tab submits as "cut_and_sync" (not the plain
      // "cut_silence" job) when the user opted in to also sync right
      // after cutting — same underlying two steps as "Fluxo Completo",
      // just skipping the TTS step since the audio already exists.
      // "Sincronizar" tab submits as "sync_from_capcut" instead of "sync"
      // when syncing straight onto audio already cut inside an existing
      // CapCut project, rather than an audio file tracked by the panel.
      const syncFromCapcut = tabType === "sync" && syncSource === "capcut";
      const type: JobType = tabType === "cut_silence" && cutAlsoSync
        ? "cut_and_sync"
        : syncFromCapcut
          ? "sync_from_capcut"
          : tabType;
      const combinedCutSync = type === "cut_and_sync";

      const params: Record<string, unknown> = {};
      if (syncFromCapcut) {
        params.capcut_draft_name = syncCapcutDraft;
        params.expert_folder = expertFolder;
      } else {
        params.ad_folder = effectiveAdFolder;
        if (type === "cut_silence" || type === "sync" || combinedCutSync) {
          params.audio_filename = audioFilename;
        }
        if (type === "tts" || type === "pipeline") {
          params.tts = { text, voice_id: voiceId, speed, emotion, filename: ttsFilename.trim() };
        }
        if (type === "sync" || type === "pipeline" || combinedCutSync) {
          params.expert_folder = expertFolder;
        }
        if (type === "pipeline" || combinedCutSync) {
          params.generate_capcut_draft = generateCapcutDraft;
          if (generateCapcutDraft && capcutMode === "append") {
            params.capcut_append_to = capcutAppendTo;
          }
        }
        if (type === "pipeline") {
          params.subfolder = pipelineSubfolder.trim();
        }
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

  const syncFromCapcutMode = tab === "sync" && syncSource === "capcut";
  const needsTts = tab === "tts" || tab === "pipeline";
  const needsExpert = tab === "sync" || tab === "pipeline" || (tab === "cut_silence" && cutAlsoSync);
  const needsAudioFilename = tab === "cut_silence" || (tab === "sync" && syncSource === "audio");
  const showsCapcutOptions = tab === "pipeline" || (tab === "cut_silence" && cutAlsoSync);
  const canSubmit = syncFromCapcutMode
    ? !!syncCapcutDraft && !!expertFolder
    : !!effectiveAdFolder &&
      (!needsTts || (text.trim() && voiceId && ttsFilename.trim())) &&
      (!needsExpert || expertFolder) &&
      (!needsAudioFilename || audioFilename) &&
      (tab !== "tts" || true) &&
      (!needsTts || confirmedTts || tab !== "pipeline") && // confirm gate only enforced on the no-pause combined flow
      (!showsCapcutOptions || !generateCapcutDraft || capcutMode !== "append" || capcutAppendTo);

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white">
            <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5">
              <path d="M4 7h16M4 12h10M4 17h13" stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
            </svg>
          </div>
          <h1 className="text-lg font-semibold text-slate-100">
            Painel de Corte e Sincronização
          </h1>
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={() => catalog.refresh()}
            disabled={catalog.refreshing}
            className="text-xs font-medium text-blue-400 hover:text-blue-300 disabled:opacity-50"
          >
            {catalog.refreshing ? "atualizando..." : "atualizar catálogo"}
          </button>
          <button onClick={logout} className="text-xs font-medium text-slate-500 hover:text-slate-200">
            sair
          </button>
        </div>
      </div>

      {catalog.updated_at === null && (
        <p className="mb-4 rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-400">
          Catálogo ainda não recebido do worker local — confirme que o worker está rodando
          (start_worker.bat) e aguarde ele reportar as pastas/vozes.
        </p>
      )}

      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-5 flex gap-1 rounded-xl bg-slate-950/60 p-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => {
                setTab(t.id);
                setJobId(null);
              }}
              className={`flex-1 rounded-lg px-3 py-2 text-sm transition ${
                tab === t.id
                  ? "bg-blue-600 font-medium text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-100"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

      <div className="space-y-3">
        {tab === "sync" && (
          <div className="flex gap-3 text-xs text-slate-400">
            <label className="flex items-center gap-1">
              <input
                type="radio"
                name="syncSource"
                checked={syncSource === "audio"}
                onChange={() => setSyncSource("audio")}
                className="accent-blue-600"
              />
              Áudio do painel
            </label>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                name="syncSource"
                checked={syncSource === "capcut"}
                onChange={() => setSyncSource("capcut")}
                className="accent-blue-600"
              />
              Projeto do CapCut (áudio já cortado lá)
            </label>
          </div>
        )}

        {syncFromCapcutMode && (
          <Field label="Projeto do CapCut">
            <select
              value={syncCapcutDraft}
              onChange={(e) => setSyncCapcutDraft(e.target.value)}
              className={inputClass}
            >
              <option value="">selecione...</option>
              {catalog.capcut_drafts.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-slate-500">
              Lê o áudio JÁ CORTADO nesse projeto (pode ser vários arquivos concatenados) e
              adiciona a sincronia de vídeo direto nele — não mexe no áudio, não gera .mp4
              separado. Exporte o vídeo final pelo próprio CapCut depois.
            </p>
          </Field>
        )}

        {!syncFromCapcutMode && (
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
                className="whitespace-nowrap rounded-lg border border-slate-700 px-2 text-xs text-slate-400 transition hover:bg-slate-800"
              >
                {newAdFolder ? "escolher existente" : "nova pasta"}
              </button>
            </div>
          </Field>
        )}

        {tab === "pipeline" && (
          <Field label="Subpasta de destino (opcional)">
            {effectiveAdFolder ? (
              <SubfolderPicker
                tree={audioTreeInFolder}
                value={pipelineSubfolder}
                onChange={setPipelineSubfolder}
              />
            ) : (
              <p className="text-xs text-slate-500">escolha a pasta do anúncio primeiro</p>
            )}
            <p className="mt-1 text-xs text-slate-500">
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
              <p className="text-xs text-slate-500">escolha a pasta do anúncio primeiro</p>
            )}
            {tab === "sync" && (
              <p className="mt-1 text-xs text-slate-500">
                Se esse áudio ainda não foi cortado, o sistema corta o silêncio automaticamente
                antes de sincronizar. Se já foi cortado antes, reaproveita o corte existente.
              </p>
            )}
          </Field>
        )}

        {tab === "cut_silence" && (
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={cutAlsoSync}
              onChange={(e) => setCutAlsoSync(e.target.checked)}
              className="accent-blue-600"
            />
            Também sincronizar com um expert/avatar logo em seguida
          </label>
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
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={confirmedTts}
              onChange={(e) => setConfirmedTts(e.target.checked)}
              className="accent-blue-600"
            />
            Confirmo a voz/velocidade/entonação acima — o fluxo completo roda direto até o final,
            sem pausar, então uma escolha errada aqui só aparece no vídeo pronto.
          </label>
        )}

        {showsCapcutOptions && (
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={generateCapcutDraft}
                onChange={(e) => setGenerateCapcutDraft(e.target.checked)}
                className="accent-blue-600"
              />
              Criar também o draft no CapCut (áudio cortado + sincronia como clipes editáveis)
            </label>

            {generateCapcutDraft && (
              <div className="ml-5 space-y-2">
                <div className="flex gap-3 text-xs text-slate-400">
                  <label className="flex items-center gap-1">
                    <input
                      type="radio"
                      name="capcutMode"
                      checked={capcutMode === "new"}
                      onChange={() => setCapcutMode("new")}
                      className="accent-blue-600"
                    />
                    Criar do zero
                  </label>
                  <label className="flex items-center gap-1">
                    <input
                      type="radio"
                      name="capcutMode"
                      checked={capcutMode === "append"}
                      onChange={() => setCapcutMode("append")}
                      className="accent-blue-600"
                    />
                    Adicionar em projeto existente
                  </label>
                </div>
                {capcutMode === "append" && (
                  <Field label="Draft do CapCut a continuar">
                    <select
                      value={capcutAppendTo}
                      onChange={(e) => setCapcutAppendTo(e.target.value)}
                      className={inputClass}
                    >
                      <option value="">selecione...</option>
                      {catalog.capcut_drafts.map((d) => (
                        <option key={d} value={d}>
                          {d}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-xs text-slate-500">
                      Adiciona esse novo trecho DEPOIS do que já existe nesse draft — não
                      sobrescreve, não recria.
                    </p>
                  </Field>
                )}
              </div>
            )}
          </div>
        )}

        <button
          onClick={() => submit(tab)}
          disabled={!canSubmit || submitting}
          className="w-full rounded-lg bg-blue-600 px-3 py-2.5 text-sm font-medium text-white transition hover:bg-blue-500 disabled:opacity-50"
        >
          {submitting ? "Enviando..." : "Executar"}
        </button>
      </div>
      </div>

      <JobStatusPanel job={job} />
    </div>
  );
}
