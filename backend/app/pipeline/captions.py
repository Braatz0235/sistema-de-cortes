"""Build burned-in caption (.ass) files from word-level transcript timestamps."""
from __future__ import annotations

from pathlib import Path

from ..models import Word

CueList = list[tuple[float, float, str]]


def build_caption_cues(
    words: list[Word],
    clip_start: float,
    clip_end: float,
    max_chars: int = 42,
    max_duration: float = 3.2,
) -> CueList:
    """Group words that fall inside [clip_start, clip_end) into short caption cues,
    with timestamps made relative to the clip's own start (0 = first frame of the clip).
    """
    cues: CueList = []
    current_words: list[str] = []
    current_start: float | None = None
    last_end = 0.0

    for word in words:
        if word.end <= clip_start or word.start >= clip_end:
            continue
        text = word.text.strip()
        if not text:
            continue
        w_start = max(0.0, word.start - clip_start)
        w_end = max(0.0, min(word.end, clip_end) - clip_start)

        if current_start is None:
            current_start = w_start
        current_words.append(text)
        last_end = w_end

        joined = " ".join(current_words)
        duration = w_end - current_start
        if len(joined) >= max_chars or duration >= max_duration:
            cues.append((current_start, w_end, joined))
            current_words = []
            current_start = None

    if current_words and current_start is not None:
        cues.append((current_start, max(last_end, current_start + 0.5), " ".join(current_words)))

    return cues


def cues_from_segments(
    segments: list[dict],
    clip_start: float,
    clip_end: float,
    max_chars: int = 42,
    max_duration: float = 3.2,
) -> CueList:
    """Fallback cue builder for transcripts without word-level timestamps: splits
    each segment's text evenly across its own duration.
    """
    cues: CueList = []
    for seg in segments:
        s, e, text = seg["start"], seg["end"], seg["text"].strip()
        if e <= clip_start or s >= clip_end or not text:
            continue
        s = max(s, clip_start) - clip_start
        e = min(e, clip_end) - clip_start
        words = text.split()
        if not words:
            continue
        chunk: list[str] = []
        chunk_start = s
        span = max(e - s, 0.01)
        per_word = span / len(words)
        for i, w in enumerate(words):
            chunk.append(w)
            joined = " ".join(chunk)
            t_now = s + per_word * (i + 1)
            if len(joined) >= max_chars or t_now - chunk_start >= max_duration or i == len(words) - 1:
                cues.append((chunk_start, t_now, joined))
                chunk = []
                chunk_start = t_now
    return cues


def _fmt_time(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(cues: CueList, dst: Path, play_res_x: int = 1080, play_res_y: int = 1920) -> None:
    font_size = max(28, int(play_res_y * 0.05))
    outline = max(2, int(play_res_y * 0.004))
    margin_v = int(play_res_y * 0.09)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial Black,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H40000000,"
        f"1,0,0,0,100,100,0,0,3,{outline},0,2,60,60,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    for start, end, text in cues:
        if end <= start:
            end = start + 0.3
        escaped = text.replace("\n", "\\N").replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(end)},Default,,0,0,0,,{escaped}\n")

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("".join(lines), encoding="utf-8")
