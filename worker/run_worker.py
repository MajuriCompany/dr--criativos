"""Main worker loop: claim a pending job from Upstash, run the matching
pipeline step(s) using the local files in EDICAO_VIDEOS_ROOT, report status
back. Nothing here ever uploads media anywhere — only text (job params/
status) crosses the network, via Upstash.

Run with: python run_worker.py  (or double-click start_worker.bat)
"""
from __future__ import annotations

import json
import re
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
                          base_name: str | None = None) -> dict:
    base_name = base_name or source_audio.stem
    report_progress(up, job, "cut_silence", "transcrevendo áudio...")
    edit_dir = ad_dir / "edit"
    edit_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcribe.transcribe_one(
        source_audio, edit_dir, config.elevenlabs_api_key(), cache_key=base_name,
    )

    report_progress(up, job, "cut_silence", "cortando silêncio...")
    result = cut_silence_pipeline.cut_silence(source_audio, transcript_path, edit_dir, base_name)
    add_artifact(up, job, str(result["final_mp3"]))
    return result


def run_sync_step(up: Upstash, job: dict, ad_dir: Path, expert_folder: str,
                   sentences_json: Path, final_mp3: Path) -> Path:
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
    out_video = ad_dir / "final_sincronizado.mp4"
    render_result = render_pipeline.render_video(edl, edit_dir, out_video)

    drift = abs(render_result["final_duration"] - total_duration)
    if drift > 0.5:
        raise RuntimeError(
            f"vídeo renderizado ({render_result['final_duration']:.2f}s) não bate com "
            f"o áudio ({total_duration:.2f}s) — diferença de {drift:.2f}s, algo deu "
            f"errado na montagem da EDL"
        )

    add_artifact(up, job, str(out_video))
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
        final_mp3, sentences_json = catalog.resolve_cut_result(ad_dir, base_name)
        if not (final_mp3.exists() and sentences_json.exists()):
            raise FileNotFoundError(
                f"esse áudio ainda não foi cortado — rode \"Cortar Silêncio\" nele primeiro "
                f"(esperava encontrar {sentences_json.name} em edit/)"
            )
        run_sync_step(up, job, ad_dir, params["expert_folder"], sentences_json, final_mp3)

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

    def push_catalog() -> None:
        cat = catalog.build_catalog(config.EDICAO_VIDEOS_ROOT)
        up.set("catalog:ads", json.dumps(cat["ads"]))
        up.set("catalog:experts", json.dumps(cat["experts"]))
        up.set("catalog:voices", json.dumps(cat["voices"], ensure_ascii=False))
        up.set("catalog:ad_tree", json.dumps(cat["ad_tree"]))
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
