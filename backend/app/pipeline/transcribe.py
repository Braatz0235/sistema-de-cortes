"""Speech-to-text, producing word-level timestamps.

Two backends:
- Local faster-whisper (default): free, no API key, but downloads a model
  (a few hundred MB) on first use and needs a CPU/GPU to run it.
- OpenAI's hosted Whisper API: used instead whenever OPENAI_API_KEY is set.
  No local model/download at all, at the cost of an API call per video.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from .. import config
from ..models import TranscriptSegment, Word

logger = logging.getLogger(__name__)

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


def _transcribe_local(audio_path: Path, language: Optional[str]) -> list[TranscriptSegment]:
    model = get_model()
    segments_iter, _info = model.transcribe(
        str(audio_path),
        language=language,
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


def _assign_word_to_segment(
    segments: list[TranscriptSegment], word_start: float
) -> Optional[TranscriptSegment]:
    for seg in segments:
        if seg.start <= word_start < seg.end:
            return seg
    if not segments:
        return None
    return segments[0] if word_start < segments[0].start else segments[-1]


def _transcribe_openai(audio_path: Path, language: Optional[str]) -> list[TranscriptSegment]:
    from openai import OpenAI  # imported lazily: optional dependency, only needed with OPENAI_API_KEY

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    kwargs = dict(
        model=config.OPENAI_STT_MODEL,
        response_format="verbose_json",
        timestamp_granularities=["segment", "word"],
    )
    if language:
        kwargs["language"] = language

    with audio_path.open("rb") as f:
        response = client.audio.transcriptions.create(file=f, **kwargs)

    segments = [
        TranscriptSegment(start=s.start, end=s.end, text=(s.text or "").strip())
        for s in (response.segments or [])
    ]
    for w in (response.words or []):
        seg = _assign_word_to_segment(segments, w.start)
        if seg is not None:
            seg.words.append(Word(start=w.start, end=w.end, text=w.word))
    return segments


def transcribe(audio_path: Path, language: Optional[str] = None) -> list[TranscriptSegment]:
    lang = language or config.WHISPER_LANGUAGE
    if config.OPENAI_API_KEY:
        try:
            return _transcribe_openai(audio_path, lang)
        except Exception:
            logger.exception("OpenAI transcription failed, falling back to local faster-whisper")
    return _transcribe_local(audio_path, lang)
