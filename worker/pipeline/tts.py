"""MiniMax Text-to-Speech (T2A v2). Ported from edicao-videos/tts/minimax_tts.py,
parametrized (no hardcoded output paths). See platform.minimax.io docs
(confirmed live 2026-07): POST /v1/t2a_v2 and /v1/get_voice, Bearer auth,
no GroupId needed on this key type.
"""
from __future__ import annotations

import binascii
import json
from pathlib import Path

import requests

API_BASE = "https://api.minimax.io/v1"
EMOTIONS = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent", "whisper"}


def list_voices(api_key: str, voice_type: str = "voice_cloning") -> dict:
    resp = requests.post(
        f"{API_BASE}/get_voice",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"voice_type": voice_type},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def generate_speech(
    api_key: str,
    text: str,
    voice_id: str,
    out_path: Path,
    speed: float = 1.0,
    vol: float = 1.0,
    pitch: int = 0,
    emotion: str | None = None,
    model: str = "speech-2.8-hd",
    sample_rate: int = 44100,
    audio_format: str = "mp3",
) -> dict:
    """Generate speech and write it to out_path. Returns the extra_info dict from the API."""
    if not (0.5 <= speed <= 2.0):
        raise ValueError(f"speed must be in [0.5, 2.0], got {speed}")
    if emotion is not None and emotion not in EMOTIONS:
        raise ValueError(f"emotion must be one of {sorted(EMOTIONS)}, got {emotion!r}")

    voice_setting = {"voice_id": voice_id, "speed": speed, "vol": vol, "pitch": pitch}
    if emotion:
        voice_setting["emotion"] = emotion

    payload = {
        "model": model,
        "text": text,
        "voice_setting": voice_setting,
        "audio_setting": {
            "sample_rate": sample_rate,
            "format": audio_format,
            "channel": 1,
            **({"bitrate": 256000} if audio_format == "mp3" else {}),
        },
        "output_format": "hex",
    }
    resp = requests.post(
        f"{API_BASE}/t2a_v2",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise RuntimeError(f"MiniMax API error: {base_resp}")

    audio_bytes = binascii.unhexlify(data["data"]["audio"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio_bytes)
    return data.get("extra_info", {})
