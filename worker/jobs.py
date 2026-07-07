"""Job queue operations against Upstash Redis. Schema:

job:{id}          JSON blob (see PLAN.md) — the single source of truth per job
jobs:queue        List of pending job IDs (RPUSH on create)
jobs:processing   List of claimed-but-not-finished job IDs
jobs:recent       Capped list (last 20) of job IDs, for the "what's running" UI
"""
from __future__ import annotations

import json
import time
import traceback
from typing import Any

from upstash_client import Upstash

RECENT_CAP = 20


def get_job(up: Upstash, job_id: str) -> dict | None:
    raw = up.get(f"job:{job_id}")
    return json.loads(raw) if raw else None


def _save(up: Upstash, job: dict) -> None:
    job["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    up.set(f"job:{job['id']}", json.dumps(job, ensure_ascii=False))


def claim_job(up: Upstash, worker_id: str) -> dict | None:
    """Atomically pop the next pending job ID (LMOVE — see upstash_client.py
    for why this is race-free) and mark it running. Returns None if the
    queue is empty."""
    job_id = up.lmove("jobs:queue", "jobs:processing")
    if not job_id:
        return None
    job = get_job(up, job_id)
    if job is None:
        # blob missing/expired — drop the orphaned ID and move on
        up.lrem("jobs:processing", 0, job_id)
        return None
    job["status"] = "running"
    job["claimed_by"] = worker_id
    _save(up, job)
    return job


def report_progress(up: Upstash, job: dict, step: str, message: str) -> None:
    job["progress"] = {"step": step, "message": message}
    _save(up, job)


def add_artifact(up: Upstash, job: dict, path: str) -> None:
    job.setdefault("result", {}).setdefault("artifacts", []).append(path)
    _save(up, job)


def mark_done(up: Upstash, job: dict) -> None:
    job["status"] = "done"
    up.lrem("jobs:processing", 0, job["id"])
    _save(up, job)


ERROR_HINTS = [
    (lambda msg: "401" in msg or "invalid" in msg.lower() and "minimax" in msg.lower(),
     "Chave da MiniMax inválida ou expirada — verifique o worker/.env."),
    (lambda msg: "elevenlabs" in msg.lower() and ("quota" in msg.lower() or "429" in msg),
     "Cota da ElevenLabs esgotada este mês — aguarde o reset ou verifique o painel ElevenLabs."),
    (lambda msg: "ffmpeg" in msg.lower() or "ffprobe" in msg.lower(),
     "Falha ao processar áudio/vídeo — verifique se o arquivo de origem não está corrompido."),
    (lambda msg: "not found" in msg.lower() and ("ad" in msg.lower() or "expert" in msg.lower()),
     "Pasta de anúncio ou expert não encontrada em edicao-videos/ — confira o nome."),
]


def _friendly_message(exc: Exception) -> str:
    msg = str(exc)
    for check, hint in ERROR_HINTS:
        if check(msg):
            return hint
    return "Erro inesperado — veja os detalhes técnicos."


def mark_error(up: Upstash, job: dict, exc: Exception, step: str) -> None:
    job["status"] = "error"
    job["error"] = {
        "step": step,
        "message": _friendly_message(exc),
        "detail": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }
    up.lrem("jobs:processing", 0, job["id"])
    _save(up, job)


def push_recent(up: Upstash, job_id: str) -> None:
    up.lpush("jobs:recent", job_id)
    up.ltrim("jobs:recent", 0, RECENT_CAP - 1)


def sweep_stale_processing_jobs(up: Upstash) -> int:
    """Run on worker startup: any job still marked 'processing' from a prior
    crashed run gets marked as an error instead of silently resumed (ffmpeg
    may have left a partial file)."""
    stale_ids = up.lrange("jobs:processing", 0, -1)
    count = 0
    for job_id in stale_ids:
        job = get_job(up, job_id)
        if job and job.get("status") == "running":
            job["status"] = "error"
            job["error"] = {
                "step": job.get("progress", {}).get("step", "?"),
                "message": "O worker foi interrompido antes de terminar — rode este job de novo.",
                "detail": "worker restarted while job was in flight",
            }
            _save(up, job)
            count += 1
        up.lrem("jobs:processing", 0, job_id)
    return count
