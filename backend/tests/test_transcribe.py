from pathlib import Path

import pytest

from app.pipeline import transcribe as transcribe_mod
from app.pipeline.transcribe import _assign_word_to_segment
from app.models import TranscriptSegment


class _FakeWord:
    def __init__(self, word, start, end):
        self.word = word
        self.start = start
        self.end = end


class _FakeSegment:
    def __init__(self, text, start, end):
        self.text = text
        self.start = start
        self.end = end


class _FakeResponse:
    def __init__(self, segments, words):
        self.segments = segments
        self.words = words


class _FakeTranscriptions:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def create(self, file, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeAudio:
    def __init__(self, response):
        self.transcriptions = _FakeTranscriptions(response)


class _FakeOpenAI:
    last_instance = None

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.audio = _FakeAudio(_FakeOpenAI.response)
        _FakeOpenAI.last_instance = self


@pytest.fixture
def dummy_audio(tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"not-really-audio")
    return path


def test_assign_word_to_segment_basic():
    segments = [
        TranscriptSegment(start=0.0, end=5.0, text="a"),
        TranscriptSegment(start=5.0, end=10.0, text="b"),
    ]
    assert _assign_word_to_segment(segments, 2.0) is segments[0]
    assert _assign_word_to_segment(segments, 7.0) is segments[1]
    # before the first segment / after the last one -> clamp to nearest
    assert _assign_word_to_segment(segments, -1.0) is segments[0]
    assert _assign_word_to_segment(segments, 20.0) is segments[1]
    assert _assign_word_to_segment([], 1.0) is None


def test_transcribe_uses_openai_when_key_set(monkeypatch, dummy_audio):
    _FakeOpenAI.response = _FakeResponse(
        segments=[_FakeSegment("Ola mundo", 0.0, 2.0), _FakeSegment("segundo trecho", 2.0, 5.0)],
        words=[
            _FakeWord("Ola", 0.0, 0.5),
            _FakeWord("mundo", 0.5, 2.0),
            _FakeWord("segundo", 2.0, 3.0),
            _FakeWord("trecho", 3.0, 5.0),
        ],
    )
    monkeypatch.setattr("app.config.OPENAI_API_KEY", "fake-key")
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)

    segments = transcribe_mod.transcribe(dummy_audio)

    assert len(segments) == 2
    assert segments[0].text == "Ola mundo"
    assert [w.text for w in segments[0].words] == ["Ola", "mundo"]
    assert [w.text for w in segments[1].words] == ["segundo", "trecho"]


def test_transcribe_uses_local_when_no_openai_key(monkeypatch, dummy_audio):
    monkeypatch.setattr("app.config.OPENAI_API_KEY", None)
    sentinel = [TranscriptSegment(start=0.0, end=1.0, text="local")]
    monkeypatch.setattr(transcribe_mod, "_transcribe_local", lambda path, lang: sentinel)

    def boom(*a, **kw):
        raise AssertionError("should not call the OpenAI backend when no key is set")

    monkeypatch.setattr(transcribe_mod, "_transcribe_openai", boom)

    assert transcribe_mod.transcribe(dummy_audio) is sentinel


def test_transcribe_falls_back_to_local_on_openai_error(monkeypatch, dummy_audio):
    monkeypatch.setattr("app.config.OPENAI_API_KEY", "fake-key")
    sentinel = [TranscriptSegment(start=0.0, end=1.0, text="local-fallback")]
    monkeypatch.setattr(transcribe_mod, "_transcribe_local", lambda path, lang: sentinel)

    def boom(path, lang):
        raise RuntimeError("openai is down")

    monkeypatch.setattr(transcribe_mod, "_transcribe_openai", boom)

    assert transcribe_mod.transcribe(dummy_audio) is sentinel
