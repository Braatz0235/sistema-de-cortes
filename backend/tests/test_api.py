import pytest
from fastapi.testclient import TestClient

from app import jobs as jobs_module
from app.main import app
from app.models import Clip, VideoStatus
from app.storage import store


@pytest.fixture(autouse=True)
def no_background_jobs(monkeypatch):
    # Keep tests from spawning real ffmpeg/whisper/Claude work; api/videos.py
    # calls `jobs.submit_...`, and it imported the same module object, so
    # patching these attributes here reaches it too.
    monkeypatch.setattr(jobs_module, "submit_video_processing", lambda video_id: None)
    monkeypatch.setattr(jobs_module, "submit_export", lambda video_id, export_id: None)


@pytest.fixture
def client():
    return TestClient(app)


def _fake_video_bytes():
    return b"\x00\x00\x00\x18ftypmp42" + b"0" * 1024


def _upload(client):
    res = client.post("/api/videos", files={"file": ("clip.mp4", _fake_video_bytes(), "video/mp4")})
    assert res.status_code == 201
    return res.json()["id"]


def test_list_platforms(client):
    res = client.get("/api/platforms")
    assert res.status_code == 200
    data = res.json()
    assert any(p["id"] == "tiktok" for p in data)
    assert any(p["id"] == "youtube" for p in data)


def test_upload_rejects_bad_extension(client):
    res = client.post("/api/videos", files={"file": ("clip.txt", b"hello", "text/plain")})
    assert res.status_code == 400


def test_upload_and_get_video(client):
    video_id = _upload(client)

    res = client.get(f"/api/videos/{video_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == video_id
    assert body["status"] == "queued"
    assert "transcript" not in body


def test_video_appears_in_list(client):
    video_id = _upload(client)
    res = client.get("/api/videos")
    assert res.status_code == 200
    ids = [v["id"] for v in res.json()]
    assert video_id in ids


def test_get_unknown_video_404(client):
    res = client.get("/api/videos/does-not-exist")
    assert res.status_code == 404


def test_export_requires_ready_status(client):
    video_id = _upload(client)
    res = client.post(f"/api/videos/{video_id}/clips/whatever/exports", json={"platform": "tiktok"})
    assert res.status_code == 409


def test_export_flow_when_ready(client):
    video_id = _upload(client)
    clip = Clip(start=0.0, end=20.0, title="Teste", summary="resumo", score=80)

    def mark_ready(job):
        job.status = VideoStatus.READY
        job.duration = 60.0
        job.clips = [clip]

    store.update(video_id, mark_ready)

    res = client.post(
        f"/api/videos/{video_id}/clips/{clip.id}/exports",
        json={"platform": "tiktok", "captions": False},
    )
    assert res.status_code == 201
    export = res.json()
    assert export["format"] == "vertical"
    assert export["status"] == "queued"

    res2 = client.get(f"/api/videos/{video_id}/exports/{export['id']}")
    assert res2.status_code == 200
    assert res2.json()["id"] == export["id"]


def test_export_unknown_clip_404(client):
    video_id = _upload(client)
    store.update(video_id, lambda job: setattr(job, "status", VideoStatus.READY))
    res = client.post(f"/api/videos/{video_id}/clips/nope/exports", json={"platform": "tiktok"})
    assert res.status_code == 404


def test_export_unknown_platform_rejected(client):
    video_id = _upload(client)
    clip = Clip(start=0.0, end=20.0, title="Teste", summary="resumo", score=80)

    def mark_ready(job):
        job.status = VideoStatus.READY
        job.clips = [clip]

    store.update(video_id, mark_ready)

    res = client.post(f"/api/videos/{video_id}/clips/{clip.id}/exports", json={"platform": "myspace"})
    assert res.status_code == 400


def test_export_format_overrides_platform_default(client):
    video_id = _upload(client)
    clip = Clip(start=0.0, end=20.0, title="Teste", summary="resumo", score=80)

    def mark_ready(job):
        job.status = VideoStatus.READY
        job.clips = [clip]

    store.update(video_id, mark_ready)

    res = client.post(
        f"/api/videos/{video_id}/clips/{clip.id}/exports",
        json={"format": "horizontal"},
    )
    assert res.status_code == 201
    assert res.json()["format"] == "horizontal"


def test_delete_video(client):
    video_id = _upload(client)
    res = client.delete(f"/api/videos/{video_id}")
    assert res.status_code == 204
    res2 = client.get(f"/api/videos/{video_id}")
    assert res2.status_code == 404
