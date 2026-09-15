"""HTTP API: upload a video, poll its processing status/clips, export & download cuts."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import config, jobs
from ..models import (
    PLATFORM_BY_ID,
    PLATFORM_PRESETS,
    ClipFormat,
    Export,
    ExportStatus,
    VideoJob,
    VideoStatus,
    new_id,
)
from ..storage import store

router = APIRouter(prefix="/api")


def _get_job_or_404(video_id: str) -> VideoJob:
    job = store.try_get(video_id)
    if job is None:
        raise HTTPException(status_code=404, detail="vídeo não encontrado")
    return job


@router.get("/platforms")
def list_platforms():
    return PLATFORM_PRESETS


@router.get("/videos")
def list_videos():
    return [
        {
            "id": j.id,
            "original_filename": j.original_filename,
            "status": j.status,
            "duration": j.duration,
            "created_at": j.created_at,
            "clip_count": len(j.clips),
        }
        for j in store.list()
    ]


@router.post("/videos", status_code=201)
async def upload_video(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"formato não suportado ({suffix or 'sem extensão'}); use: "
                f"{', '.join(sorted(config.ALLOWED_VIDEO_EXTENSIONS))}"
            ),
        )

    video_id = new_id()
    source_name = f"source{suffix}"
    job = VideoJob(id=video_id, original_filename=file.filename or source_name, source_file=source_name)
    store.create(job)

    dest = store.video_dir(video_id) / source_name
    written = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="arquivo excede o tamanho máximo permitido")
                out.write(chunk)
    except HTTPException:
        store.delete(video_id)
        raise
    except Exception:
        store.delete(video_id)
        raise HTTPException(status_code=500, detail="falha ao salvar o arquivo enviado")
    finally:
        await file.close()

    if written == 0:
        store.delete(video_id)
        raise HTTPException(status_code=400, detail="arquivo vazio")

    jobs.submit_video_processing(video_id)
    return {"id": video_id, "status": job.status}


@router.get("/videos/{video_id}")
def get_video(video_id: str):
    job = _get_job_or_404(video_id)
    data = job.model_dump(mode="json")
    data.pop("transcript", None)  # can be large; the UI doesn't need the raw transcript
    return data


@router.get("/videos/{video_id}/source")
def get_video_source(video_id: str):
    job = _get_job_or_404(video_id)
    path = store.video_dir(video_id) / job.source_file
    if not path.exists():
        raise HTTPException(status_code=404, detail="arquivo de origem não encontrado")
    return FileResponse(path)


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(video_id: str):
    _get_job_or_404(video_id)
    store.delete(video_id)
    return None


class ExportRequest(BaseModel):
    platform: Optional[str] = None
    format: Optional[ClipFormat] = None
    captions: bool = True


@router.post("/videos/{video_id}/clips/{clip_id}/exports", status_code=201)
def create_export(video_id: str, clip_id: str, body: ExportRequest):
    job = _get_job_or_404(video_id)
    if job.status != VideoStatus.READY:
        raise HTTPException(status_code=409, detail="vídeo ainda não está pronto")
    clip = job.find_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="corte não encontrado")

    platform = body.platform
    if platform and platform not in PLATFORM_BY_ID:
        raise HTTPException(status_code=400, detail="plataforma desconhecida")

    clip_format = body.format
    if clip_format is None:
        clip_format = PLATFORM_BY_ID[platform].format if platform else ClipFormat.VERTICAL

    export = Export(clip_id=clip_id, platform=platform, format=clip_format, captions=body.captions)

    def mutate(job: VideoJob) -> None:
        job.exports.append(export)

    store.update(video_id, mutate)
    jobs.submit_export(video_id, export.id)
    return export


@router.get("/videos/{video_id}/exports/{export_id}")
def get_export(video_id: str, export_id: str):
    job = _get_job_or_404(video_id)
    export = job.find_export(export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="exportação não encontrada")
    return export


@router.get("/videos/{video_id}/exports/{export_id}/download")
def download_export(video_id: str, export_id: str):
    job = _get_job_or_404(video_id)
    export = job.find_export(export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="exportação não encontrada")
    if export.status != ExportStatus.DONE or not export.file_name:
        raise HTTPException(status_code=409, detail="exportação ainda não concluída")

    path = store.exports_dir(video_id) / export.file_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="arquivo de exportação não encontrado")

    clip = job.find_clip(export.clip_id)
    raw_name = f"{(clip.title if clip else 'corte')[:40]}-{export.platform or export.format}.mp4"
    download_name = re.sub(r"[^\w\-. ]", "_", raw_name)
    return FileResponse(path, filename=download_name, media_type="video/mp4")
