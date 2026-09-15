"""Background job orchestration: the video processing pipeline and clip exports.

Both video analysis and per-clip export are I/O + CPU bound (ffmpeg, whisper)
so they run on a small shared thread pool rather than tying up the request
loop. Progress is persisted to each video's meta.json as it advances so
clients can poll for status.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from . import config
from .models import FORMAT_DIMENSIONS, ExportStatus, VideoJob, VideoStatus
from .pipeline import captions, ffmpeg_utils
from .pipeline.highlight_detection import detect_highlights
from .pipeline.transcribe import transcribe
from .storage import store

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=config.WORKER_THREADS, thread_name_prefix="cortes-worker")


def submit_video_processing(video_id: str) -> None:
    _executor.submit(_process_video, video_id)


def submit_export(video_id: str, export_id: str) -> None:
    _executor.submit(_process_export, video_id, export_id)


def _set_status(video_id: str, status: VideoStatus, **fields) -> None:
    def mutate(job: VideoJob) -> None:
        job.status = status
        for k, v in fields.items():
            setattr(job, k, v)

    store.update(video_id, mutate)


def _process_video(video_id: str) -> None:
    job = store.get(video_id)
    source_path = store.video_dir(video_id) / job.source_file
    audio_path = store.video_dir(video_id) / "audio.wav"
    try:
        _set_status(video_id, VideoStatus.EXTRACTING_AUDIO)
        info = ffmpeg_utils.probe(source_path)
        duration = info["duration"] or 0.0

        def set_probe(job: VideoJob) -> None:
            job.duration = duration
            job.width = info["width"]
            job.height = info["height"]

        store.update(video_id, set_probe)

        ffmpeg_utils.extract_audio(source_path, audio_path)

        _set_status(video_id, VideoStatus.TRANSCRIBING)
        segments = transcribe(audio_path)

        def set_transcript(job: VideoJob) -> None:
            job.transcript = segments

        store.update(video_id, set_transcript)

        _set_status(video_id, VideoStatus.ANALYZING)
        clips = detect_highlights(segments, duration)

        def set_clips(job: VideoJob) -> None:
            job.clips = clips
            job.status = VideoStatus.READY

        store.update(video_id, set_clips)
    except Exception as exc:
        logger.exception("Video processing failed for %s", video_id)
        _set_status(video_id, VideoStatus.FAILED, error=str(exc))
    finally:
        if audio_path.exists():
            try:
                audio_path.unlink()
            except OSError:
                pass


def _fail_export(video_id: str, export_id: str, message: str) -> None:
    def mutate(job: VideoJob) -> None:
        exp = job.find_export(export_id)
        if exp:
            exp.status = ExportStatus.FAILED
            exp.error = message

    store.update(video_id, mutate)


def _process_export(video_id: str, export_id: str) -> None:
    job = store.get(video_id)
    export = job.find_export(export_id)
    if export is None:
        return
    clip = job.find_clip(export.clip_id)
    if clip is None:
        _fail_export(video_id, export_id, "clipe não encontrado")
        return

    def set_processing(job: VideoJob) -> None:
        exp = job.find_export(export_id)
        if exp:
            exp.status = ExportStatus.PROCESSING

    store.update(video_id, set_processing)

    source_path = store.video_dir(video_id) / job.source_file
    exports_dir = store.exports_dir(video_id)
    out_name = f"{export_id}.mp4"
    out_path = exports_dir / out_name
    subtitles_path: Optional[Path] = None

    try:
        if export.captions:
            all_words = [w for seg in job.transcript for w in seg.words]
            if all_words:
                cues = captions.build_caption_cues(all_words, clip.start, clip.end)
            else:
                cues = captions.cues_from_segments(
                    [s.model_dump() for s in job.transcript], clip.start, clip.end,
                )
            if cues:
                dims = FORMAT_DIMENSIONS[export.format] or (job.width or 1080, job.height or 1920)
                subtitles_path = exports_dir / f"{export_id}.ass"
                captions.write_ass(cues, subtitles_path, play_res_x=dims[0], play_res_y=dims[1])

        ffmpeg_utils.export_clip(
            source_path, out_path, clip.start, clip.end, export.format, subtitles_path,
        )

        def set_done(job: VideoJob) -> None:
            exp = job.find_export(export_id)
            if exp:
                exp.status = ExportStatus.DONE
                exp.file_name = out_name

        store.update(video_id, set_done)
    except Exception as exc:
        logger.exception("Export failed for %s/%s", video_id, export_id)
        _fail_export(video_id, export_id, str(exc))
    finally:
        if subtitles_path and subtitles_path.exists():
            try:
                subtitles_path.unlink()
            except OSError:
                pass
