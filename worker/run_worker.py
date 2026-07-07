"""Main worker loop: claim a pending job from Upstash, run the matching
pipeline step(s) using the local files in EDICAO_VIDEOS_ROOT, report status
back. Nothing here ever uploads media anywhere — only text (job params/
status) crosses the network, via Upstash.

Run with: python run_worker.py  (or double-click start_worker.bat)
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import config
from jobs import (add_artifact, claim_job, mark_done, mark_error,
                   push_recent, report_progress, sweep_stale_processing_jobs)
from pipeline import catalog, cut_silence as cut_silence_pipeline
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
    durations = {}
    for f in sorted(expert_dir.glob("*.mp4")):
        durations[f.stem] = _ffprobe_duration(f)
    return durations


def run_tts_step(up: Upstash, job: dict, ad_dir: Path) -> Path:
    p = job["params"]["tts"]
    report_progress(up, job, "tts", "gerando áudio via MiniMax...")
    edit_dir = ad_dir / "edit"
    edit_dir.mkdir(parents=True, exist_ok=True)
    raw_path = edit_dir / "raw_tts.mp3"
    tts.generate_speech(
        config.minimax_api_key(), p["text"], p["voice_id"], raw_path,
        speed=p.get("speed", 1.0), emotion=p.get("emotion"),
    )
    add_artifact(up, job, str(raw_path))
    return raw_path


def run_cut_silence_step(up: Upstash, job: dict, ad_dir: Path, source_audio: Path) -> dict:
    report_progress(up, job, "cut_silence", "transcrevendo áudio...")
    edit_dir = ad_dir / "edit"
    edit_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcribe.transcribe_one(source_audio, edit_dir, config.elevenlabs_api_key())

    report_progress(up, job, "cut_silence", "cortando silêncio...")
    result = cut_silence_pipeline.cut_silence(source_audio, transcript_path, edit_dir)
    add_artifact(up, job, str(result["final_mp3"]))
    return result


def run_sync_step(up: Upstash, job: dict, ad_dir: Path, expert_folder: str,
                   sentences_json: Path, final_mp3: Path) -> Path:
    report_progress(up, job, "sync", "montando EDL de sincronização...")
    expert_dir = config.EDICAO_VIDEOS_ROOT / expert_folder
    if not expert_dir.is_dir():
        raise FileNotFoundError(f"expert folder not found: {expert_folder}")

    take_durations = _take_durations(expert_dir)
    sources = {label: str(expert_dir / f"{label}.mp4") for label in take_durations}
    sentences = json.loads(sentences_json.read_text(encoding="utf-8"))
    total_duration = _ffprobe_duration(final_mp3)

    edl = sync_takes.build_sync_edl(sentences, sources, take_durations, total_duration, str(final_mp3))

    report_progress(up, job, "sync", "renderizando vídeo final...")
    edit_dir = ad_dir / "edit"
    out_video = ad_dir / "final_sincronizado.mp4"
    render_pipeline.render_video(edl, edit_dir, out_video)
    add_artifact(up, job, str(out_video))
    return out_video


def run_job(up: Upstash, job: dict) -> None:
    job_type = job["type"]
    params = job["params"]
    ad_folder = params.get("ad_folder")
    ad_dir = config.EDICAO_VIDEOS_ROOT / ad_folder if ad_folder else None

    if job_type == "tts":
        run_tts_step(up, job, ad_dir)

    elif job_type == "cut_silence":
        source_audio = ad_dir / params["audio_filename"]
        run_cut_silence_step(up, job, ad_dir, source_audio)

    elif job_type == "sync":
        run_sync_step(up, job, ad_dir, params["expert_folder"],
                      ad_dir / "edit" / "sentences.json", ad_dir / "edit" / "final.mp3")

    elif job_type == "pipeline":
        raw_tts = run_tts_step(up, job, ad_dir)
        cut_result = run_cut_silence_step(up, job, ad_dir, raw_tts)
        run_sync_step(up, job, ad_dir, params["expert_folder"],
                      cut_result["sentences_json"], cut_result["final_mp3"])

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

        now = time.time()
        if now - last_catalog_push > config.CATALOG_REFRESH_INTERVAL_S:
            cat = catalog.build_catalog(config.EDICAO_VIDEOS_ROOT)
            up.set("catalog:ads", json.dumps(cat["ads"]))
            up.set("catalog:experts", json.dumps(cat["experts"]))
            up.set("catalog:voices", json.dumps(cat["voices"], ensure_ascii=False))
            up.set("catalog:ad_files", json.dumps(cat["ad_files"]))
            up.set("catalog:updated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            last_catalog_push = now

        time.sleep(config.POLL_INTERVAL_S)


if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\nworker encerrado.")
        sys.exit(0)
