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


_TREE_EXCLUDED_DIRS = {"edit"}
_TREE_MAX_DEPTH = 6


def scan_audio_tree(ad_dir: Path, _depth: int = 0) -> dict:
    """Recursively lists audio files and subfolders under an ad folder, so the
    panel can offer a drill-down picker instead of requiring a flat layout.
    Skips edit/ (the pipeline's own working directory, not source material)
    and caps depth as a cheap guard against unexpectedly deep/large trees.
    """
    tree: dict = {"files": [], "dirs": {}}
    if not ad_dir.is_dir() or _depth > _TREE_MAX_DEPTH:
        return tree
    for p in sorted(ad_dir.iterdir()):
        if p.name.startswith("."):
            continue
        if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS:
            tree["files"].append(p.name)
        elif p.is_dir() and p.name not in _TREE_EXCLUDED_DIRS:
            tree["dirs"][p.name] = scan_audio_tree(p, _depth + 1)
    return tree


# "final" is a reserved sentinel for the legacy fixed-name pair (edit/final.mp3
# + edit/sentences.json) produced by ad02's original manual process, before
# cut results were namespaced by source filename. resolve_cut_result() below
# special-cases it back to the un-prefixed paths.
def scan_cut_results(ad_dir: Path) -> list[str]:
    edit_dir = ad_dir / "edit"
    if not edit_dir.is_dir():
        return []
    results = []
    if (edit_dir / "final.mp3").exists() and (edit_dir / "sentences.json").exists():
        results.append("final")
    for p in sorted(edit_dir.glob("*_final.mp3")):
        base = p.name[: -len("_final.mp3")]
        if (edit_dir / f"{base}_sentences.json").exists():
            results.append(base)
    return results


def resolve_cut_result(ad_dir: Path, base_name: str) -> tuple[Path, Path]:
    edit_dir = ad_dir / "edit"
    if base_name == "final":
        return edit_dir / "final.mp3", edit_dir / "sentences.json"
    return edit_dir / f"{base_name}_final.mp3", edit_dir / f"{base_name}_sentences.json"


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
        "ad_tree": {ad: scan_audio_tree(edicao_videos_root / ad) for ad in ads},
        "cut_results": {ad: scan_cut_results(edicao_videos_root / ad) for ad in ads},
    }
