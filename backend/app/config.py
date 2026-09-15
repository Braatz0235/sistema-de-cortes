"""Central configuration, read from environment variables with sane defaults."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage" / "videos"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Transcription (faster-whisper). "base" is a good speed/accuracy tradeoff on CPU.
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "base")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE") or None  # None = auto-detect

# Highlight detection via Claude. Falls back to a local heuristic when unset.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

MIN_CLIP_SECONDS = float(os.environ.get("MIN_CLIP_SECONDS", 15))
MAX_CLIP_SECONDS = float(os.environ.get("MAX_CLIP_SECONDS", 90))
MAX_CLIPS = int(os.environ.get("MAX_CLIPS", 8))

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 2 * 1024 * 1024 * 1024))  # 2GB
WORKER_THREADS = int(os.environ.get("WORKER_THREADS", 2))

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
