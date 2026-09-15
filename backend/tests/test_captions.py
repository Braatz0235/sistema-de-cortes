from app.models import Word
from app.pipeline import captions


def test_build_caption_cues_basic():
    words = [
        Word(start=10.0, end=10.3, text="Olá"),
        Word(start=10.3, end=10.6, text="mundo"),
        Word(start=10.6, end=11.0, text="isso"),
        Word(start=11.0, end=11.4, text="é"),
        Word(start=11.4, end=11.9, text="um"),
        Word(start=11.9, end=12.5, text="teste"),
    ]
    cues = captions.build_caption_cues(words, clip_start=10.0, clip_end=13.0, max_chars=100, max_duration=100)
    assert len(cues) == 1
    start, end, text = cues[0]
    assert start == 0.0
    assert text == "Olá mundo isso é um teste"


def test_build_caption_cues_respects_max_duration():
    # Cue length is checked after each word is appended, so it can overshoot
    # max_duration by at most one word's own span (0.2s here) - not before.
    words = [Word(start=i * 0.2, end=i * 0.2 + 0.15, text=f"w{i}") for i in range(20)]
    cues = captions.build_caption_cues(words, clip_start=0, clip_end=10, max_chars=1000, max_duration=2.0)
    assert len(cues) > 1
    for start, end, _ in cues:
        assert end - start <= 2.2 + 1e-6


def test_build_caption_cues_filters_outside_range():
    words = [
        Word(start=0.0, end=0.5, text="fora"),
        Word(start=5.0, end=5.5, text="dentro"),
        Word(start=20.0, end=20.5, text="fora2"),
    ]
    cues = captions.build_caption_cues(words, clip_start=4.0, clip_end=6.0)
    assert len(cues) == 1
    assert cues[0][2] == "dentro"


def test_cues_from_segments_splits_words_across_duration():
    segments = [{"start": 0.0, "end": 4.0, "text": "uma frase de teste aqui"}]
    cues = captions.cues_from_segments(segments, clip_start=0.0, clip_end=4.0, max_chars=1000, max_duration=100)
    assert len(cues) == 1
    assert cues[0][2] == "uma frase de teste aqui"


def test_write_ass_creates_file(tmp_path):
    cues = [(0.0, 1.5, "Olá mundo")]
    dst = tmp_path / "subs.ass"
    captions.write_ass(cues, dst, play_res_x=1080, play_res_y=1920)
    content = dst.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:00.00,0:00:01.50,Default" in content
    assert "Olá mundo" in content
