"""Speech-to-text via faster-whisper, producing word-level timestamps.

The model is loaded lazily (it's a multi-hundred-MB download on first use)
and cached as a process-wide singleton.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from .. import config
from ..models import TranscriptSegment, Word

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel  # imported lazily: heavy + optional at test time

                _model = WhisperModel(
                    config.WHISPER_MODEL_SIZE,
                    device=config.WHISPER_DEVICE,
                    compute_type=config.WHISPER_COMPUTE_TYPE,
                )
    return _model


def transcribe(audio_path: Path, language: Optional[str] = None) -> list[TranscriptSegment]:
    model = get_model()
    lang = language or config.WHISPER_LANGUAGE
    segments_iter, _info = model.transcribe(
        str(audio_path),
        language=lang,
        word_timestamps=True,
        vad_filter=True,
    )

    result: list[TranscriptSegment] = []
    for seg in segments_iter:
        words = [
            Word(start=w.start, end=w.end, text=w.word)
            for w in (seg.words or [])
        ]
        result.append(TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip(), words=words))
    return result
