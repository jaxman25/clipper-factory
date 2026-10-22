"""Word-level ASS captions for burned-in shorts.

OpenMontage's caption stage is an agentic pipeline living inside its own repo
(it is not an importable package), so this module reproduces the same delivery
style natively: 2-3 word cards, yellow fill (#FFD700), heavy black stroke,
a pop-in scale animation per card, plus dedicated hook and outro styles.

Everything is plain ASS (Advanced SubStation Alpha), which ffmpeg burns in with
the ``ass`` filter, so no extra runtime dependency is needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,78,{primary},&H000000FF&,&H00000000&,&HA0000000&,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,430,1
Style: Hook,DejaVu Sans,92,{primary},&H000000FF&,&H00000000&,&HA0000000&,-1,0,0,0,100,100,0,0,1,7,3,8,60,60,250,1
Style: Outro,DejaVu Sans,62,&H00FFFFFF&,&H000000FF&,&H00000000&,&HA0000000&,-1,0,0,0,100,100,0,0,1,5,2,5,80,80,0,1
Style: Label,DejaVu Sans,44,&H00FFFFFF&,&H000000FF&,&H00000000&,&HA0000000&,-1,0,0,0,100,100,2,0,1,4,1,8,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


@dataclass
class CaptionWord:
    start: float
    end: float
    text: str


def hex_to_ass(color: str) -> str:
    """#FFD700 -> &H00D7FF& (ASS uses &HAABBGGRR)."""
    value = color.strip().lstrip("#")
    if len(value) != 6:
        value = "FFD700"
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H00{b}{g}{r}&"


def _ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _escape(text: str) -> str:
    text = text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _cards(words: Sequence[CaptionWord], per_card: int) -> list[tuple[float, float, str]]:
    """Group words into short display cards, breaking on pauses/punctuation."""
    cards: list[tuple[float, float, list[CaptionWord]]] = []
    current: list[CaptionWord] = []
    for word in words:
        if current and (len(current) >= per_card or word.start - current[-1].end > 0.55):
            cards.append((current[0].start, current[-1].end, current))
            current = []
        current.append(word)
        if re.search(r"[.!?]$", word.text):
            cards.append((current[0].start, current[-1].end, current))
            current = []
    if current:
        cards.append((current[0].start, current[-1].end, current))

    out: list[tuple[float, float, str]] = []
    for idx, (start, _end, group) in enumerate(cards):
        next_start = cards[idx + 1][0] if idx + 1 < len(cards) else start + 4.0
        end = max(start + 0.45, min(next_start, group[-1].end + 0.45))
        text = " ".join(w.text for w in group).strip()
        if text:
            out.append((start, end, text.upper()))
    return out


def build_ass(
    words: Sequence[CaptionWord],
    duration: float,
    speed: float = 1.1,
    primary_color: str = "#FFD700",
    words_per_card: int = 3,
    hook: str = "",
    hook_seconds: float = 2.0,
    outro_text: str = "",
    outro_seconds: float = 2.0,
    transcript: str = "",
    label: str = "",
) -> str:
    """Return a complete .ass document for one clip."""
    duration = max(0.5, duration)
    speed = speed if speed > 0.1 else 1.0
    outro_start = max(0.0, duration - max(1.0, outro_seconds))

    events: list[str] = []

    if label:
        events.append(
            f"Dialogue: 0,{_ts(0)},{_ts(min(duration, 3.0))},Label,,0,0,0,,"
            f"{{\\fad(200,300)}}{_escape(label.upper())}"
        )

    if hook:
        events.append(
            f"Dialogue: 1,{_ts(0)},{_ts(min(duration, hook_seconds))},Hook,,0,0,0,,"
            f"{{\\fad(90,140)\\fscx88\\fscy88\\t(0,120,\\fscx104\\fscy104)}}"
            f"{_escape(hook.upper())}"
        )

    scaled = [
        CaptionWord(max(0.0, (w.start) / speed), max(0.05, w.end / speed), w.text)
        for w in words
        if w.text
    ]

    if not scaled and transcript.strip():
        # No word timings (e.g. a stub transcript): spread sentence-sized cards.
        chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+", transcript.strip()) if c.strip()]
        if chunks:
            per = max(1.2, duration / len(chunks))
            scaled = []
            for i, chunk in enumerate(chunks[:8]):
                start = i * per
                scaled.append(CaptionWord(start, min(duration, start + per), chunk))
            words_per_card = 99

    prev_end = 0.0
    for start, end, text in _cards(scaled, max(1, words_per_card)):
        start = max(start, prev_end + 0.01)
        end = min(end, duration)
        if hook and start < hook_seconds - 0.05:
            prev_end = 0.0
            continue
        if start >= duration - 0.15:
            break
        # Do not fight the outro card for the bottom third of the frame.
        if start >= outro_start and outro_text:
            break
        if end <= start:
            end = min(duration, start + 0.4)
        pop = "{\\fad(60,40)\\an2\\pos(540,1500)\\fscx86\\fscy86\\t(0,90,\\fscx100\\fscy100)}"
        events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{pop}{_escape(text)}")
        prev_end = end

    if outro_text:
        events.append(
            f"Dialogue: 2,{_ts(outro_start)},{_ts(duration)},Outro,,0,0,0,,"
            f"{{\\fad(250,200)\\an5\\pos(540,1210)\\fscx92\\fscy92\\t(0,260,\\fscx100\\fscy100)}}"
            f"{_escape(outro_text.upper())}"
        )

    return ASS_HEADER.format(primary=hex_to_ass(primary_color)) + "\n".join(events) + "\n"
