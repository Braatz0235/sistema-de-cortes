from pathlib import Path

from app.models import ClipFormat
from app.pipeline import ffmpeg_utils


def test_build_export_command_original_format_no_filter():
    cmd = ffmpeg_utils.build_export_command(Path("in.mp4"), Path("out.mp4"), 10.0, 25.5, ClipFormat.ORIGINAL)
    assert cmd[0] == "ffmpeg"
    assert "-filter_complex" not in cmd
    assert "0:v" in cmd
    assert "0:a?" in cmd


def test_build_export_command_vertical_uses_filter_complex():
    cmd = ffmpeg_utils.build_export_command(Path("in.mp4"), Path("out.mp4"), 0.0, 30.0, ClipFormat.VERTICAL)
    assert "-filter_complex" in cmd
    idx = cmd.index("-filter_complex")
    filter_str = cmd[idx + 1]
    assert "1080:1920" in filter_str
    assert "[vfmt]" in filter_str
    assert "[vfmt]" in cmd  # the -map argument that follows


def test_build_export_command_square_and_horizontal_dims():
    cmd_sq = ffmpeg_utils.build_export_command(Path("in.mp4"), Path("out.mp4"), 0, 10, ClipFormat.SQUARE)
    assert "1080:1080" in cmd_sq[cmd_sq.index("-filter_complex") + 1]

    cmd_h = ffmpeg_utils.build_export_command(Path("in.mp4"), Path("out.mp4"), 0, 10, ClipFormat.HORIZONTAL)
    assert "1920:1080" in cmd_h[cmd_h.index("-filter_complex") + 1]


def test_build_export_command_with_subtitles_escapes_colons(tmp_path):
    sub_path = tmp_path / "weird:name.ass"
    cmd = ffmpeg_utils.build_export_command(Path("in.mp4"), Path("out.mp4"), 0, 10, ClipFormat.SQUARE, sub_path)
    filter_str = cmd[cmd.index("-filter_complex") + 1]
    assert "subtitles=" in filter_str
    assert "\\:" in filter_str


def test_probe_parses_ffprobe_json(monkeypatch, tmp_path):
    fake_json = (
        '{"format": {"duration": "12.5"}, "streams": ['
        '{"codec_type": "video", "width": 1920, "height": 1080}, '
        '{"codec_type": "audio"}]}'
    )
    monkeypatch.setattr(ffmpeg_utils, "run", lambda cmd, timeout=None: fake_json)
    info = ffmpeg_utils.probe(tmp_path / "video.mp4")
    assert info == {"duration": 12.5, "width": 1920, "height": 1080, "has_audio": True}


def test_run_raises_on_nonzero_exit():
    try:
        ffmpeg_utils.run(["ffmpeg", "-nonexistent-flag"])
        assert False, "expected FFmpegError"
    except ffmpeg_utils.FFmpegError:
        pass
