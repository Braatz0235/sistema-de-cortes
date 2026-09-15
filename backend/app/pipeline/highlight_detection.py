"""Pick the best moments of a video to turn into standalone clips.

Primary strategy: ask Claude to read the timestamped transcript and propose
ranked clip candidates. Falls back to a local keyword/punctuation heuristic
when no ANTHROPIC_API_KEY is configured, or if the API call fails for any
reason, so the pipeline never gets stuck.
"""
from __future__ import annotations

import json
import logging
import re

from .. import config
from ..models import Clip, TranscriptSegment

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Você é um editor de vídeo especialista em cortes virais para redes sociais \
(TikTok, Instagram Reels, YouTube Shorts, YouTube, LinkedIn, X). Você recebe a transcrição de um \
vídeo com marcações de tempo [mm:ss - mm:ss] e deve identificar os melhores trechos para virarem \
cortes/clipes independentes e de alto potencial de engajamento.

Responda APENAS com um array JSON válido, sem nenhum texto antes ou depois, exatamente neste formato:
[
  {{
    "start": <segundos, número>,
    "end": <segundos, número>,
    "title": "<título curto e chamativo, no mesmo idioma da transcrição>",
    "summary": "<1-2 frases explicando por que esse trecho prende atenção>",
    "score": <número de 0 a 100, potencial viral/engajamento>,
    "suggested_platforms": [lista com valores entre "tiktok", "instagram_reels", "youtube_shorts", \
"instagram_feed", "facebook_feed", "youtube", "twitter_x", "linkedin"],
    "hashtags": ["#exemplo", "..."]
  }}
]

Regras:
- Cada trecho deve ter começo e fim que formem uma ideia completa (não corte no meio de uma frase importante).
- Duração de cada corte entre {min_s:.0f} e {max_s:.0f} segundos.
- No máximo {max_clips} trechos, ordenados do maior para o menor score, sem sobreposição entre eles.
- Prefira formatos verticais (tiktok/instagram_reels/youtube_shorts) para trechos curtos e dinâmicos, \
e formatos horizontais (youtube/twitter_x/linkedin) para trechos mais longos/explicativos. Pode sugerir mais de uma plataforma por trecho.
- hashtags: 3 a 6 hashtags relevantes ao conteúdo, no mesmo idioma da transcrição."""

_KEYWORDS = {
    "importante", "incrível", "incrivel", "segredo", "erro", "nunca", "sempre", "dica", "dicas",
    "atenção", "atencao", "cuidado", "resultado", "resultados", "transformou", "mudou", "chocante",
    "inacreditável", "inacreditavel", "surpreendente", "gratuito", "comprovado", "garantido",
    "melhor", "pior", "verdade", "mentira", "polêmica", "polemica", "impacto", "real", "exclusivo",
    "secret", "important", "never", "always", "amazing", "incredible", "shocking", "proven",
    "result", "mistake", "truth", "warning", "tip", "hack", "free", "exclusive", "best", "worst",
}

_STOPWORDS = {
    "para", "como", "isso", "esse", "essa", "esta", "este", "mais", "muito", "muita", "quando",
    "onde", "porque", "então", "entao", "aquilo", "sobre", "tambem", "também", "depois", "antes",
    "agora", "todo", "toda", "todos", "todas", "pessoas", "coisa", "coisas", "fazer", "sendo",
    "that", "this", "with", "have", "from", "your", "about", "because", "there", "which", "would",
    "could", "should", "their", "these", "those", "going", "really",
}


def _fmt_mmss(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60:02d}:{t % 60:02d}"


def _format_transcript(segments: list[TranscriptSegment]) -> str:
    return "\n".join(f"[{_fmt_mmss(s.start)} - {_fmt_mmss(s.end)}] {s.text}" for s in segments)


def _parse_json_array(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    data = json.loads(text.strip())
    if not isinstance(data, list):
        raise ValueError("expected a JSON array from the model")
    return data


def _claude_highlights(segments: list[TranscriptSegment], duration: float) -> list[dict]:
    from anthropic import Anthropic  # imported lazily: optional dependency when no API key is set

    transcript_text = _format_transcript(segments)
    if len(transcript_text) > 60000:
        transcript_text = transcript_text[:60000] + "\n[...transcrição truncada...]"

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    system_prompt = _SYSTEM_PROMPT.format(
        min_s=config.MIN_CLIP_SECONDS, max_s=config.MAX_CLIP_SECONDS, max_clips=config.MAX_CLIPS,
    )
    user_prompt = f"Duração total do vídeo: {duration:.0f} segundos.\n\nTranscrição:\n{transcript_text}"

    message = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    return _parse_json_array(raw)


def _segment_score(text: str) -> float:
    lower = text.lower()
    score = sum(3 for kw in _KEYWORDS if kw in lower)
    score += lower.count("?") * 2
    score += lower.count("!") * 2
    score += sum(1 for ch in text if ch.isdigit()) * 0.5
    word_count = len(text.split())
    if 6 <= word_count <= 40:
        score += 1
    return score


def _guess_platforms(duration: float) -> list[str]:
    if duration <= 60:
        return ["tiktok", "instagram_reels", "youtube_shorts", "instagram_feed"]
    return ["youtube", "linkedin", "twitter_x"]


def _guess_hashtags(text: str, limit: int = 5) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ]{4,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w in _STOPWORDS:
            continue
        freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [f"#{w.capitalize()}" for w, _ in top] or ["#corte", "#viral"]


def _make_title(text: str, limit_words: int = 9) -> str:
    words = text.split()
    if not words:
        return "Corte em destaque"
    title = " ".join(words[:limit_words])
    return title + ("…" if len(words) > limit_words else "")


def _equal_windows(duration: float, min_s: float, max_s: float, max_clips: int) -> list[dict]:
    if duration <= 0:
        return []
    target = min(max(min_s, duration), max_s)
    n = max(1, min(max_clips, int(duration // target) or 1))
    step = duration / n
    return [
        {"start": i * step, "end": min(duration, i * step + target), "score": 1.0}
        for i in range(n)
    ]


def _heuristic_highlights_raw(segments: list[TranscriptSegment], duration: float) -> list[dict]:
    min_s, max_s, max_clips = config.MIN_CLIP_SECONDS, config.MAX_CLIP_SECONDS, config.MAX_CLIPS
    if not segments:
        return _equal_windows(duration, min_s, max_s, max_clips)

    scores = [_segment_score(s.text) for s in segments]
    n = len(segments)
    candidates = []
    for i in range(n):
        start = segments[i].start
        acc = 0.0
        for j in range(i, n):
            if segments[j].start - start > max_s:
                break
            acc += scores[j]
            end = segments[j].end
            dur = end - start
            if dur >= min_s:
                # Rank by score *density* (points per second), not raw sum: a raw
                # sum always favors the longest window, since it keeps accumulating
                # more segments' scores, which would just return ~the whole video
                # as "the highlight" instead of a tight, concentrated moment.
                density = acc / dur
                candidates.append({
                    "start": start, "end": end, "density": density,
                    "score": round(min(100, 35 + density * 25), 1),
                })

    if not candidates:
        return _equal_windows(duration, min_s, max_s, max_clips)

    candidates.sort(key=lambda c: c["density"], reverse=True)
    chosen: list[dict] = []
    for c in candidates:
        overlaps = any(not (c["end"] <= ch["start"] or c["start"] >= ch["end"]) for ch in chosen)
        if overlaps:
            continue
        chosen.append(c)
        if len(chosen) >= max_clips:
            break
    chosen.sort(key=lambda c: c["start"])
    return chosen


def _transcript_excerpt(segments: list[TranscriptSegment], start: float, end: float, limit: int = 280) -> str:
    parts = [s.text for s in segments if s.end > start and s.start < end]
    text = " ".join(parts).strip()
    return (text[: limit - 1] + "…") if len(text) > limit else text


def detect_highlights(segments: list[TranscriptSegment], duration: float) -> list[Clip]:
    candidates: list[dict] = []

    if config.ANTHROPIC_API_KEY:
        try:
            candidates = _claude_highlights(segments, duration)
        except Exception:
            logger.exception("Claude highlight detection failed, falling back to heuristic")
            candidates = []

    if not candidates:
        candidates = _heuristic_highlights_raw(segments, duration)

    clips: list[Clip] = []
    for c in candidates:
        try:
            start = max(0.0, min(float(c["start"]), duration))
            end = max(start + 1.0, min(float(c["end"]), duration))
        except (KeyError, TypeError, ValueError):
            continue
        excerpt = _transcript_excerpt(segments, start, end)
        clips.append(Clip(
            start=round(start, 2),
            end=round(end, 2),
            title=(c.get("title") or _make_title(excerpt)).strip(),
            summary=(c.get("summary") or excerpt[:180]).strip(),
            score=float(c.get("score", 50) or 50),
            suggested_platforms=c.get("suggested_platforms") or _guess_platforms(end - start),
            hashtags=c.get("hashtags") or _guess_hashtags(excerpt),
            transcript_excerpt=excerpt,
        ))

    clips.sort(key=lambda c: c.score, reverse=True)
    return clips[: config.MAX_CLIPS]
