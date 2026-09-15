"""Simple JSON-file-backed persistence for video jobs.

No database needed: each video gets its own directory under STORAGE_DIR with
a meta.json describing it (status, transcript, clips, exports) plus the raw
media files. A per-video lock keeps concurrent read-modify-write safe.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import config
from .models import VideoJob


class VideoNotFoundError(Exception):
    pass


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, video_id: str) -> threading.Lock:
        with self._locks_guard:
            if video_id not in self._locks:
                self._locks[video_id] = threading.Lock()
            return self._locks[video_id]

    def video_dir(self, video_id: str) -> Path:
        return self.root / video_id

    def exports_dir(self, video_id: str) -> Path:
        d = self.video_dir(video_id) / "exports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def meta_path(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "meta.json"

    def create(self, job: VideoJob) -> VideoJob:
        d = self.video_dir(job.id)
        d.mkdir(parents=True, exist_ok=True)
        self._write(job)
        return job

    def _write(self, job: VideoJob) -> None:
        path = self.meta_path(job.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def get(self, video_id: str) -> VideoJob:
        path = self.meta_path(video_id)
        if not path.exists():
            raise VideoNotFoundError(video_id)
        return VideoJob.model_validate_json(path.read_text(encoding="utf-8"))

    def try_get(self, video_id: str) -> Optional[VideoJob]:
        try:
            return self.get(video_id)
        except VideoNotFoundError:
            return None

    def list(self) -> list[VideoJob]:
        jobs = []
        if not self.root.exists():
            return jobs
        for d in sorted(self.root.iterdir(), reverse=True):
            meta = d / "meta.json"
            if meta.exists():
                try:
                    jobs.append(VideoJob.model_validate_json(meta.read_text(encoding="utf-8")))
                except Exception:
                    continue
        return jobs

    def update(self, video_id: str, mutator: Callable[[VideoJob], None]) -> VideoJob:
        lock = self._lock_for(video_id)
        with lock:
            job = self.get(video_id)
            mutator(job)
            job.updated_at = time.time()
            self._write(job)
            return job

    def delete(self, video_id: str) -> None:
        d = self.video_dir(video_id)
        if d.exists():
            shutil.rmtree(d)
        with self._locks_guard:
            self._locks.pop(video_id, None)


store = JobStore(config.STORAGE_DIR)
