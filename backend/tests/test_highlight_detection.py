from app.models import TranscriptSegment
from app.pipeline.highlight_detection import (
    _guess_hashtags,
    _heuristic_highlights_raw,
    _make_title,
    _parse_json_array,
    detect_highlights,
)


def _seg(start, end, text):
    return TranscriptSegment(start=start, end=end, text=text)


def test_detect_highlights_uses_heuristic_without_api_key(monkeypatch):
    monkeypatch.setattr("app.config.ANTHROPIC_API_KEY", None)
    segments = [
        _seg(0, 5, "Isso é uma introdução qualquer sem muita coisa relevante."),
        _seg(5, 15, "Atenção! Esse é o segredo mais importante que vai mudar sua vida, com 3 passos."),
        _seg(15, 25, "Aqui vamos falar de outro assunto genérico e tranquilo."),
        _seg(25, 40, "Nunca faça esse erro incrível, é chocante o resultado comprovado disso."),
        _seg(40, 70, "E por fim, uma conclusão longa e mediana sobre tudo que foi dito por aqui."),
    ]
    clips = detect_highlights(segments, duration=70)
    assert len(clips) > 0
    for clip in clips:
        assert clip.end > clip.start
        assert clip.title
        assert clip.suggested_platforms


def test_heuristic_highlights_no_overlap():
    segments = [_seg(i * 5, i * 5 + 5, f"frase numero {i} com dica importante {i}") for i in range(20)]
    candidates = _heuristic_highlights_raw(segments, duration=100)
    for a in candidates:
        for b in candidates:
            if a is b:
                continue
            assert a["end"] <= b["start"] or a["start"] >= b["end"]


def test_heuristic_highlights_handles_empty_transcript():
    clips = _heuristic_highlights_raw([], duration=120)
    assert len(clips) >= 1
    for c in clips:
        assert c["end"] > c["start"]


def test_guess_hashtags_returns_fallback_for_empty_text():
    assert _guess_hashtags("") == ["#corte", "#viral"]


def test_make_title_truncates():
    text = " ".join(["palavra"] * 20)
    title = _make_title(text, limit_words=5)
    assert title.endswith("…")
    assert len(title.split()) == 5


def test_parse_json_array_strips_markdown_fence():
    raw = '```json\n[{"start": 1, "end": 5, "title": "Oi"}]\n```'
    data = _parse_json_array(raw)
    assert data == [{"start": 1, "end": 5, "title": "Oi"}]


def test_parse_json_array_plain():
    raw = '[{"start": 1, "end": 5}]'
    assert _parse_json_array(raw) == [{"start": 1, "end": 5}]


def test_detect_highlights_uses_claude_response_when_api_key_set(monkeypatch):
    monkeypatch.setattr("app.config.ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(
        "app.pipeline.highlight_detection._claude_highlights",
        lambda segments, duration: [
            {
                "start": 2,
                "end": 12,
                "title": "Momento chave",
                "summary": "resumo",
                "score": 95,
                "suggested_platforms": ["tiktok"],
                "hashtags": ["#exemplo"],
            }
        ],
    )
    segments = [_seg(0, 15, "qualquer coisa aqui")]
    clips = detect_highlights(segments, duration=15)
    assert len(clips) == 1
    assert clips[0].title == "Momento chave"
    assert clips[0].score == 95
