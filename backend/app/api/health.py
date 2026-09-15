"""Health/readiness endpoint: surfaces missing config (ffmpeg, Claude key) up
front instead of letting it fail deep inside a background job."""
from __future__ import annotations

from fastapi import APIRouter

from .. import config
from ..pipeline import ffmpeg_utils

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    ffmpeg_ok = ffmpeg_utils.is_available()
    return {
        "status": "ok" if ffmpeg_ok else "degraded",
        "ffmpeg_available": ffmpeg_ok,
        "highlight_detection": "claude" if config.ANTHROPIC_API_KEY else "heuristic",
        "transcription": "openai" if config.OPENAI_API_KEY else "local",
        "whisper_model": config.OPENAI_STT_MODEL if config.OPENAI_API_KEY else config.WHISPER_MODEL_SIZE,
    }
