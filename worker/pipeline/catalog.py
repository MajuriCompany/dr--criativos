"""Scans edicao-videos/ for ad/expert folders and parses tts/voices.md,
producing the lightweight catalog the web UI's dropdowns are built from.
Never touches media file contents — folder/file names and a small markdown
table only.
"""
from __future__ import annotations

import re
from pathlib import Path

# Folders that live at the same level as ad folders but aren't one — never
# list these as an "ad" the panel could target.
_RESERVED_DIR_NAMES = {"tts", "edit"}

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a"}


def scan_ad_folders(root: Path) -> list[str]:
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir()
        and not p.name.startswith(".")
        and p.name not in _RESERVED_DIR_NAMES
        and not re.match(r"^expert\d*$", p.name)
    )


def scan_expert_folders(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.is_dir() and re.match(r"^expert\d*$", p.name))


def scan_audio_files(ad_dir: Path) -> list[str]:
    if not ad_dir.is_dir():
        return []
    return sorted(
        p.name for p in ad_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
    )


_VOICE_ROW_RE = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|\s*`?(?P<voice_id>moss_audio_[0-9a-f-]+)`?\s*\|\s*(?P<created>[^|]*?)\s*\|\s*$"
)


def parse_voices_md(path: Path) -> list[dict]:
    if not path.exists():
        return []
    voices = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _VOICE_ROW_RE.match(line.strip())
        if m:
            voices.append({
                "name": m.group("name").strip(),
                "voice_id": m.group("voice_id").strip(),
                "created": m.group("created").strip(),
            })
    return voices


def build_catalog(edicao_videos_root: Path) -> dict:
    ads = scan_ad_folders(edicao_videos_root)
    return {
        "ads": ads,
        "experts": scan_expert_folders(edicao_videos_root),
        "voices": parse_voices_md(edicao_videos_root / "tts" / "voices.md"),
        "ad_files": {ad: scan_audio_files(edicao_videos_root / ad) for ad in ads},
    }
