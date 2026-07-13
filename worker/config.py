"""Worker configuration, loaded from worker/.env (git-ignored)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"{name} not set in worker/.env")
    return val


EDICAO_VIDEOS_ROOT = Path(os.environ.get("EDICAO_VIDEOS_ROOT", r"C:\Users\Nicol\Documents\edicao-videos"))

# CapCut's local draft storage — %LOCALAPPDATA% keeps this portable across
# Windows accounts/machines instead of hardcoding a username.
CAPCUT_DRAFTS_ROOT = Path(os.environ.get(
    "CAPCUT_DRAFTS_ROOT",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"),
))

# Idle-queue poll interval. Kept at 10s (not 2-3s) to stay comfortably inside
# Upstash's free-tier 500k-commands/month budget — see plan doc for the math.
POLL_INTERVAL_S = int(os.environ.get("POLL_INTERVAL_S", "10"))
CATALOG_REFRESH_INTERVAL_S = int(os.environ.get("CATALOG_REFRESH_INTERVAL_S", "60"))


def upstash_credentials() -> tuple[str, str]:
    return _require("UPSTASH_REDIS_REST_URL"), _require("UPSTASH_REDIS_REST_TOKEN")


def minimax_api_key() -> str:
    return _require("MINIMAX_API_KEY")


def elevenlabs_api_key() -> str:
    return _require("ELEVENLABS_API_KEY")
