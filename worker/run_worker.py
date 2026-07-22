"""Main worker loop: claim a pending job from Upstash, run the matching
pipeline step(s) using the local files in EDICAO_VIDEOS_ROOT, report status
back. Nothing here ever uploads media anywhere — only text (job params/
status) crosses the network, via Upstash.

Run with: python run_worker.py  (or double-click start_worker.bat)
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import config
from jobs import (add_artifact, claim_job, mark_done, mark_error,
                   push_recent, report_progress, sweep_stale_processing_jobs)
from pipeline import capcut_draft, catalog, cut_silence as cut_silence_pipeline
from pipeline import render as render_pipeline
from pipeline import sync_takes, transcribe, tts
from upstash_client import Upstash

WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _take_durations(expert_dir: Path) -> dict[str, float]:
    # pycapcut-sourced, not ffprobe — see capcut_draft.probe_duration's
    # docstring for why: keeping this the single source of truth for how
    # much of a take sync_takes.py can allocate is what makes the CapCut
    # draft's video track land exactly on the audio track's total,
    # instead of drifting short by however much ffprobe over-reported.
    durations = {}
    for f in sorted(expert_dir.glob("*.mp4")):
        durations[f.stem] = capcut_draft.probe_duration(f)
    return durations


def _sanitize_filename(name: str, fallback: str) -> str:
    stem = Path(name).stem.strip() if name else ""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return stem or fallback


def _base_name_for_rel_path(rel: str) -> str:
    """Turn a (possibly subfolder-qualified) source filename like
    'nivel1/audio.mp3' into a flat, collision-resistant base name
    ('nivel1_audio') used to namespace edit/ outputs for that source."""
    flat = str(Path(rel).with_suffix("")).replace("\\", "/").replace("/", "_")
    return _sanitize_filename(flat, "audio")


def run_tts_step(up: Upstash, job: dict, ad_dir: Path) -> Path:
    p = job["params"]["tts"]
    report_progress(up, job, "tts", "gerando áudio via MiniMax...")
    filename = _sanitize_filename(p.get("filename", ""), "raw_tts")
    out_path = ad_dir / f"{filename}.mp3"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tts.generate_speech(
        config.minimax_api_key(), p["text"], p["voice_id"], out_path,
        speed=p.get("speed", 1.0), emotion=p.get("emotion"),
    )
    add_artifact(up, job, str(out_path))
    return out_path


def run_cut_silence_step(up: Upstash, job: dict, ad_dir: Path, source_audio: Path,
                          base_name: str | None = None,
                          publish_final_as: Path | None = None) -> dict:
    base_name = base_name or source_audio.stem
    report_progress(up, job, "cut_silence", "transcrevendo áudio...")
    edit_dir = ad_dir / "edit"
    edit_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcribe.transcribe_one(
        source_audio, edit_dir, config.elevenlabs_api_key(), cache_key=base_name,
    )

    report_progress(up, job, "cut_silence", "cortando silêncio...")
    result = cut_silence_pipeline.cut_silence(source_audio, transcript_path, edit_dir, base_name)

    # publish_final_as (Fluxo Completo only): the edit/ copy is internal
    # working state — sentences.json/kept_ranges.json there still matter
    # for sync_takes.py downstream — but the user-facing deliverable they
    # asked to land directly in their chosen folder is this copy.
    if publish_final_as:
        publish_final_as.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result["final_mp3"], publish_final_as)
        add_artifact(up, job, str(publish_final_as))
    else:
        add_artifact(up, job, str(result["final_mp3"]))
    return result


def run_sync_step(up: Upstash, job: dict, ad_dir: Path, expert_folder: str,
                   sentences_json: Path, final_mp3: Path,
                   kept_ranges_json: Path | None = None, base_name: str | None = None,
                   raw_audio_path: Path | None = None,
                   out_video_override: Path | None = None,
                   generate_draft: bool = True,
                   append_to_draft_name: str | None = None) -> Path:
    report_progress(up, job, "sync", "montando EDL de sincronização...")
    expert_dir = catalog.resolve_expert_dir(config.EDICAO_VIDEOS_ROOT, expert_folder)
    if not expert_dir.is_dir():
        raise FileNotFoundError(f"expert folder not found: {expert_folder}")

    take_durations = _take_durations(expert_dir)
    sources = {label: str(expert_dir / f"{label}.mp4") for label in take_durations}
    sentences = json.loads(sentences_json.read_text(encoding="utf-8"))
    total_duration = _ffprobe_duration(final_mp3)

    edl = sync_takes.build_sync_edl(sentences, sources, take_durations, total_duration, str(final_mp3))

    report_progress(up, job, "sync", "renderizando vídeo final...")
    edit_dir = ad_dir / "edit"
    out_video = out_video_override or (ad_dir / "final_sincronizado.mp4")
    render_result = render_pipeline.render_video(edl, edit_dir, out_video)

    drift = abs(render_result["final_duration"] - total_duration)
    if drift > 0.5:
        raise RuntimeError(
            f"vídeo renderizado ({render_result['final_duration']:.2f}s) não bate com "
            f"o áudio ({total_duration:.2f}s) — diferença de {drift:.2f}s, algo deu "
            f"errado na montagem da EDL"
        )

    add_artifact(up, job, str(out_video))

    if generate_draft and raw_audio_path and kept_ranges_json and kept_ranges_json.exists():
        report_progress(up, job, "sync", "gerando draft do CapCut...")
        kept_ranges = [tuple(r) for r in json.loads(kept_ranges_json.read_text(encoding="utf-8"))]
        try:
            if append_to_draft_name:
                # Continuation of an existing project (e.g. Part 2 of the
                # same CTV/VSL) — lands in the SAME CapCut draft, appended
                # after whatever's already there, not a fresh one.
                draft_path = capcut_draft.append_to_draft(
                    append_to_draft_name, config.CAPCUT_DRAFTS_ROOT, raw_audio_path, kept_ranges, edl,
                )
            else:
                # Same name the user typed in "Nome do arquivo de áudio a
                # gerar" (base_name already IS that value in the pipeline
                # flow — see run_tts_step/_sanitize_filename) — no
                # ad-folder prefix or "_auto" suffix, per explicit
                # request. Two different ads sharing that exact filename
                # would overwrite each other's draft in CapCut's single
                # shared drafts folder; accepted tradeoff for the simpler
                # name.
                draft_name = base_name or final_mp3.stem
                draft_path = capcut_draft.build_draft(
                    draft_name, config.CAPCUT_DRAFTS_ROOT, raw_audio_path, kept_ranges, edl,
                )
            add_artifact(up, job, str(draft_path))
        except Exception as exc:
            # A bonus artifact, not the job's main output — a CapCut/pycapcut
            # hiccup here shouldn't fail a sync that otherwise succeeded.
            report_progress(up, job, "sync", f"aviso: draft do CapCut falhou ({exc})")

    return out_video


def run_add_voice_step(up: Upstash, job: dict) -> None:
    p = job["params"]["voice"]
    report_progress(up, job, "add_voice", "salvando voz em tts/voices.md...")
    voices_path = config.EDICAO_VIDEOS_ROOT / "tts" / "voices.md"
    created = time.strftime("%Y-%m-%d", time.gmtime())
    catalog.append_voice(voices_path, p["name"], p["voice_id"], created)
    add_artifact(up, job, str(voices_path))


def run_job(up: Upstash, job: dict) -> None:
    job_type = job["type"]
    params = job["params"]
    ad_folder = params.get("ad_folder")
    ad_dir = config.EDICAO_VIDEOS_ROOT / ad_folder if ad_folder else None

    if job_type == "add_voice":
        run_add_voice_step(up, job)

    elif job_type == "tts":
        run_tts_step(up, job, ad_dir)

    elif job_type == "cut_silence":
        rel = params["audio_filename"]
        source_audio = ad_dir / rel
        base_name = _base_name_for_rel_path(rel)
        run_cut_silence_step(up, job, ad_dir, source_audio, base_name)

    elif job_type == "sync":
        rel = params["audio_filename"]
        base_name = _base_name_for_rel_path(rel)
        final_mp3, sentences_json, kept_ranges_json = catalog.resolve_cut_result(ad_dir, base_name)
        if not (final_mp3.exists() and sentences_json.exists()):
            raise FileNotFoundError(
                f"esse áudio ainda não foi cortado — rode \"Cortar Silêncio\" nele primeiro "
                f"(esperava encontrar {sentences_json.name} em edit/)"
            )
        run_sync_step(up, job, ad_dir, params["expert_folder"], sentences_json, final_mp3,
                      kept_ranges_json, base_name, ad_dir / rel)

    elif job_type == "pipeline":
        # "subfolder" (pasta dentro de pasta, e.g. "AD14" or "AD14/variant1")
        # makes this run's whole output — raw audio, cut audio, synced
        # video, and the edit/ working files — live together under one
        # folder the user picked, instead of scattered flat in ad_dir with
        # a fixed "final_sincronizado.mp4" name that collides across runs.
        subfolder = (params.get("subfolder") or "").strip()
        output_dir = (ad_dir / subfolder) if subfolder else ad_dir

        raw_tts = run_tts_step(up, job, output_dir)
        base_name = raw_tts.stem
        cut_result = run_cut_silence_step(
            up, job, output_dir, raw_tts, base_name,
            publish_final_as=output_dir / f"{base_name}_CORTADO.mp3",
        )
        run_sync_step(up, job, output_dir, params["expert_folder"],
                      cut_result["sentences_json"], cut_result["final_mp3"],
                      cut_result["kept_ranges_json"], base_name, raw_tts,
                      out_video_override=output_dir / f"{base_name}_SINCRONIZADO.mp4",
                      generate_draft=params.get("generate_capcut_draft", True),
                      append_to_draft_name=(params.get("capcut_append_to") or "").strip() or None)

    else:
        raise ValueError(f"unknown job type: {job_type}")


def main_loop() -> None:
    url, token = config.upstash_credentials()
    up = Upstash(url, token)

    swept = sweep_stale_processing_jobs(up)
    if swept:
        print(f"marcados como erro (worker anterior travou no meio): {swept}")

    print(f"worker rodando ({WORKER_ID}), aguardando jobs a cada {config.POLL_INTERVAL_S}s...")
    last_catalog_push = 0.0

    def push_catalog() -> None:
        cat = catalog.build_catalog(config.EDICAO_VIDEOS_ROOT, config.CAPCUT_DRAFTS_ROOT)
        up.set("catalog:ads", json.dumps(cat["ads"]))
        up.set("catalog:experts", json.dumps(cat["experts"]))
        up.set("catalog:voices", json.dumps(cat["voices"], ensure_ascii=False))
        up.set("catalog:ad_tree", json.dumps(cat["ad_tree"]))
        up.set("catalog:capcut_drafts", json.dumps(cat["capcut_drafts"]))
        up.set("catalog:updated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    while True:
        job = claim_job(up, WORKER_ID)
        if job:
            push_recent(up, job["id"])
            print(f"[{job['id']}] iniciando ({job['type']})")
            try:
                run_job(up, job)
                mark_done(up, job)
                print(f"[{job['id']}] concluído")
            except Exception as exc:  # noqa: BLE001 — surfaced to the UI, not swallowed silently
                step = job.get("progress", {}).get("step", job["type"])
                mark_error(up, job, exc, step)
                print(f"[{job['id']}] ERRO em '{step}': {exc}")
            continue

        # Manual "atualizar" button on the panel sets this key; honored on the
        # next poll (<=10s) instead of waiting for the idle 60s auto-rescan.
        if up.get("catalog:refresh_requested"):
            up.delete("catalog:refresh_requested")
            push_catalog()
            last_catalog_push = time.time()
        elif time.time() - last_catalog_push > config.CATALOG_REFRESH_INTERVAL_S:
            push_catalog()
            last_catalog_push = time.time()

        time.sleep(config.POLL_INTERVAL_S)


if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\nworker encerrado.")
        sys.exit(0)
