"""Render a synced video from a sync_takes EDL. Ported from
edicao-videos/ad02/edit/render_sync.py, parametrized (no hardcoded paths).

Per-segment extract (no audio, re-encoded since arbitrary in-points need
frame-accurate cuts) -> lossless concat -> mux the fixed audio track as the
single audio stream.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def render_video(edl: dict, work_dir: Path, out_video_path: Path, fps: int = 30) -> dict:
    """edl: {"sources": {label: path}, "ranges": [{"source","start","end",...}],
    "audio_track": path}. Returns {"video_duration", "final_duration"}."""
    clips_dir = work_dir / "clips_video"
    clips_dir.mkdir(parents=True, exist_ok=True)

    seg_paths = []
    for i, r in enumerate(edl["ranges"]):
        src = edl["sources"][r["source"]]
        start = r["start"]
        dur = r["end"] - r["start"]
        out_path = clips_dir / f"seg_{i:02d}_{r['source']}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{dur:.3f}",
             "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-r", str(fps), str(out_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        seg_paths.append(out_path)

    concat_list = work_dir / "_concat_video.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_paths))
    base_video = work_dir / "base_video.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(base_video)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    concat_list.unlink(missing_ok=True)

    out_video_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(base_video), "-i", str(edl["audio_track"]),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-shortest", "-movflags", "+faststart", str(out_video_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )

    return {
        "video_duration": _ffprobe_duration(base_video),
        "final_duration": _ffprobe_duration(out_video_path),
    }
