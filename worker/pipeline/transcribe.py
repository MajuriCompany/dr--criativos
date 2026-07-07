"""ElevenLabs Scribe transcription. Ported from video-use/helpers/transcribe.py,
self-contained (no cross-repo import) per the plan's isolation rule.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

import requests

SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"


def extract_audio(source_path: Path, dest: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(source_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def call_scribe(audio_path: Path, api_key: str, language: str | None = None, num_speakers: int | None = None) -> dict:
    data: dict[str, str] = {
        "model_id": "scribe_v1",
        "diarize": "true",
        "tag_audio_events": "true",
        "timestamps_granularity": "word",
    }
    if language:
        data["language_code"] = language
    if num_speakers:
        data["num_speakers"] = str(num_speakers)

    with open(audio_path, "rb") as f:
        resp = requests.post(
            SCRIBE_URL,
            headers={"xi-api-key": api_key},
            files={"file": (audio_path.name, f, "audio/wav")},
            data=data,
            timeout=1800,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Scribe returned {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def transcribe_one(
    source: Path,
    edit_dir: Path,
    api_key: str,
    language: str | None = None,
    num_speakers: int | None = None,
) -> Path:
    """Transcribe a single audio/video file. Returns path to transcript JSON.
    Cached: returns existing path immediately if the transcript already exists.
    """
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{source.stem}.json"

    if out_path.exists():
        return out_path

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{source.stem}.wav"
        extract_audio(source, audio)
        payload = call_scribe(audio, api_key, language, num_speakers)

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path
