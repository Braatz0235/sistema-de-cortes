"""Thin subprocess wrappers around ffmpeg/ffprobe.

All video work (trimming, reformatting to vertical/square/horizontal, burning
captions) is done in a single ffmpeg pass per export to avoid quality loss
from repeated re-encoding.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from ..models import FORMAT_DIMENSIONS, ClipFormat


class FFmpegError(RuntimeError):
    pass


def run(cmd: list[str], timeout: Optional[float] = None) -> str:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "ignore")
        raise FFmpegError(f"command failed: {' '.join(cmd)}\n{stderr[-4000:]}")
    return proc.stdout.decode("utf-8", "ignore")


def probe(path: Path) -> dict:
    """Return {duration, width, height, has_audio} for a media file."""
    out = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    data = json.loads(out)
    duration = float(data.get("format", {}).get("duration") or 0.0)
    width = height = None
    has_audio = False
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and width is None:
            width = stream.get("width")
            height = stream.get("height")
        elif stream.get("codec_type") == "audio":
            has_audio = True
    return {"duration": duration, "width": width, "height": height, "has_audio": has_audio}


def extract_audio(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
         "-acodec", "pcm_s16le", str(dst)])


def _escape_ffmpeg_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _build_filter_complex(
    clip_format: ClipFormat,
    subtitles_path: Optional[Path],
) -> tuple[Optional[str], Optional[str]]:
    """Build a -filter_complex string. Returns (filter_str, output_label) or (None, None)."""
    target_dims = FORMAT_DIMENSIONS[clip_format]
    steps: list[str] = []
    current = "0:v"

    if target_dims is not None:
        w, h = target_dims
        # Fit the source inside the target frame and fill the rest with a
        # blurred, cropped copy of itself so nothing important is ever hard-cropped.
        steps.append(
            f"[{current}]split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},gblur=sigma=20[bg2];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,format=yuv420p[vfmt]"
        )
        current = "vfmt"

    if subtitles_path is not None:
        escaped = _escape_ffmpeg_path(str(subtitles_path))
        steps.append(f"[{current}]subtitles='{escaped}'[vsub]")
        current = "vsub"

    if not steps:
        return None, None
    return ";".join(steps), current


def build_export_command(
    src: Path,
    dst: Path,
    start: float,
    end: float,
    clip_format: ClipFormat,
    subtitles_path: Optional[Path] = None,
) -> list[str]:
    duration = max(0.1, end - start)
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}"]

    filter_complex, out_label = _build_filter_complex(clip_format, subtitles_path)
    if filter_complex:
        cmd += ["-filter_complex", filter_complex, "-map", f"[{out_label}]", "-map", "0:a?"]
    else:
        cmd += ["-map", "0:v", "-map", "0:a?"]

    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(dst),
    ]
    return cmd


def export_clip(
    src: Path,
    dst: Path,
    start: float,
    end: float,
    clip_format: ClipFormat,
    subtitles_path: Optional[Path] = None,
) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_export_command(src, dst, start, end, clip_format, subtitles_path)
    run(cmd, timeout=900)
