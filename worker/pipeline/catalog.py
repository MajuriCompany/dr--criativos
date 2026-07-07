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
_RESERVED_DIR_NAMES = {"tts", "edit", "EXPERTS"}

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
    """Experts can live two ways: legacy top-level folders (expert1, expert2,
    from before this convention existed) or, going forward, subfolders of
    EXPERTS/ with any name. Both are listed; resolve_expert_dir() below knows
    how to find either kind given just the name.
    """
    legacy = {
        p.name for p in root.iterdir()
        if p.is_dir() and re.match(r"^expert\d*$", p.name)
    }
    experts_dir = root / "EXPERTS"
    grouped = set()
    if experts_dir.is_dir():
        grouped = {
            p.name for p in experts_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        }
    return sorted(legacy | grouped)


def resolve_expert_dir(root: Path, expert_name: str) -> Path:
    legacy_dir = root / expert_name
    if legacy_dir.is_dir():
        return legacy_dir
    return root / "EXPERTS" / expert_name


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
# cut results were namespaced by source filename.
def resolve_cut_result(ad_dir: Path, base_name: str) -> tuple[Path, Path]:
    edit_dir = ad_dir / "edit"
    if base_name == "final":
        return edit_dir / "final.mp3", edit_dir / "sentences.json"
    return edit_dir / f"{base_name}_final.mp3", edit_dir / f"{base_name}_sentences.json"


_VOICE_ROW_RE = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|\s*`?(?P<voice_id>moss_audio_[0-9a-f-]+)`?\s*\|\s*(?P<created>[^|]*?)\s*\|\s*$"
)


_VOICE_ID_RE = re.compile(r"^moss_audio_[0-9a-f-]+$")


def append_voice(path: Path, name: str, voice_id: str, created: str) -> None:
    name = name.strip().replace("|", "-")
    voice_id = voice_id.strip()
    if not name:
        raise ValueError("nome da voz não pode ser vazio")
    if not _VOICE_ID_RE.match(voice_id):
        raise ValueError(f"voice_id em formato inesperado (esperado moss_audio_...): {voice_id!r}")

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# Banco de vozes MiniMax — mapeamento nome → voice_id\n\n"
            "| Nome no painel MiniMax | voice_id | Criada em |\n"
            "|---|---|---|\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as f:
        f.write(f"| {name} | `{voice_id}` | {created} |\n")


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
    }
