"""Pydantic schemas and shared enums/constants for the video auto-cuts system."""
from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()


class VideoStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    READY = "ready"
    FAILED = "failed"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class ClipFormat(StrEnum):
    VERTICAL = "vertical"      # 9:16
    SQUARE = "square"          # 1:1
    HORIZONTAL = "horizontal"  # 16:9
    ORIGINAL = "original"      # keep source aspect ratio


FORMAT_DIMENSIONS: dict[ClipFormat, Optional[tuple[int, int]]] = {
    ClipFormat.VERTICAL: (1080, 1920),
    ClipFormat.SQUARE: (1080, 1080),
    ClipFormat.HORIZONTAL: (1920, 1080),
    ClipFormat.ORIGINAL: None,
}


class PlatformPreset(BaseModel):
    id: str
    label: str
    format: ClipFormat
    icon: str
    note: str = ""


PLATFORM_PRESETS: list[PlatformPreset] = [
    PlatformPreset(id="tiktok", label="TikTok", format=ClipFormat.VERTICAL, icon="🎵", note="9:16"),
    PlatformPreset(id="instagram_reels", label="Instagram Reels", format=ClipFormat.VERTICAL, icon="📱", note="9:16"),
    PlatformPreset(id="youtube_shorts", label="YouTube Shorts", format=ClipFormat.VERTICAL, icon="▶️", note="9:16"),
    PlatformPreset(id="instagram_feed", label="Instagram Feed", format=ClipFormat.SQUARE, icon="🖼️", note="1:1"),
    PlatformPreset(id="facebook_feed", label="Facebook", format=ClipFormat.SQUARE, icon="👍", note="1:1"),
    PlatformPreset(id="youtube", label="YouTube (vídeo)", format=ClipFormat.HORIZONTAL, icon="📺", note="16:9"),
    PlatformPreset(id="twitter_x", label="X (Twitter)", format=ClipFormat.HORIZONTAL, icon="✖️", note="16:9"),
    PlatformPreset(id="linkedin", label="LinkedIn", format=ClipFormat.HORIZONTAL, icon="💼", note="16:9"),
    PlatformPreset(id="original", label="Formato original", format=ClipFormat.ORIGINAL, icon="🎬", note="cru"),
]

PLATFORM_BY_ID: dict[str, PlatformPreset] = {p.id: p for p in PLATFORM_PRESETS}


class Word(BaseModel):
    start: float
    end: float
    text: str


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)


class Clip(BaseModel):
    id: str = Field(default_factory=new_id)
    start: float
    end: float
    title: str
    summary: str
    score: float
    suggested_platforms: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    transcript_excerpt: str = ""

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)


class Export(BaseModel):
    id: str = Field(default_factory=new_id)
    clip_id: str
    platform: Optional[str] = None
    format: ClipFormat
    captions: bool = True
    status: ExportStatus = ExportStatus.QUEUED
    error: Optional[str] = None
    file_name: Optional[str] = None
    created_at: float = Field(default_factory=now)


class VideoJob(BaseModel):
    id: str = Field(default_factory=new_id)
    original_filename: str
    source_file: str
    status: VideoStatus = VideoStatus.QUEUED
    error: Optional[str] = None
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: float = Field(default_factory=now)
    updated_at: float = Field(default_factory=now)
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    clips: list[Clip] = Field(default_factory=list)
    exports: list[Export] = Field(default_factory=list)

    def find_clip(self, clip_id: str) -> Optional[Clip]:
        return next((c for c in self.clips if c.id == clip_id), None)

    def find_export(self, export_id: str) -> Optional[Export]:
        return next((e for e in self.exports if e.id == export_id), None)
