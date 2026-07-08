"""Read-only diagnostic: report silent stretches in an audio/video file via
ffmpeg's silencedetect filter. Always discards ffmpeg's output (-f null NUL)
— never writes or overwrites anything. Safe to run with any path/args.

Usage: python check_silence.py <file> [noise_db] [min_duration_s]
"""
from __future__ import annotations

import subprocess
import sys


def check_silence(path: str, noise_db: float = -35.0, min_duration_s: float = 0.3) -> None:
    result = subprocess.run(
        ["ffmpeg", "-i", path, "-af", f"silencedetect=noise={noise_db}dB:d={min_duration_s}",
         "-f", "null", "NUL"],
        capture_output=True, text=True,
    )
    for line in result.stderr.splitlines():
        if "silence_start" in line or "silence_end" in line:
            print(line.split("]", 1)[-1].strip())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python check_silence.py <file> [noise_db] [min_duration_s]")
        sys.exit(1)
    file_path = sys.argv[1]
    noise = float(sys.argv[2]) if len(sys.argv) > 2 else -35.0
    min_dur = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3
    check_silence(file_path, noise, min_dur)
