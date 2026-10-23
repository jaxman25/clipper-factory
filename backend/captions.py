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

# Words that carry the most attention in a short. These are rendered
# with an extra highlight colour (yellow/green) so the viewer's eye
# locks onto the most important words instantly.
DEFAULT_HIGHLIGHT_WORDS = [
    "money", "cash", "profit", "hack", "secret", "hack", "best", "top", "money",
    "digital", "online", "business", "passive", "work", "income", "make",
    "get", "go", "how", "why", "what", "where", "when", "who", "which",
    "for", "to", "of", "and", "the", "is", "in", "on", "at", "by", "with",
]

# Extra highlight colour used for keyword words. In ASS this is a hex
# colour with alpha: &H00RRGGBB& where AA is alpha (00=fully transparent,
# FF=fully opaque). We use a soft yellow-green so it pops against the
# dark background without being bright enough to blind the viewer.
HIGHLIGHT_COLOUR = "&H00FFD700&"

# A second highlight colour that is used for a small subset of very high
# value words (e.g. numbers, named entities, command-like words). Rendered
# as a green-ish yellow so it is distinct from the base highlight.
HIGHLIGHT_REVERSE_COLOUR = "&H0000FFD7&"

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
Style: CaptionHighlight,DejaVu Sans,78,{primary},&H000000FF&,&H00000000&,&HA0000000&,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,430,1
Style: CaptionHighlightReverse,DejaVu Sans,78,{primary},&H000000FF&,&H00000000&,&HA0000000&,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,430,1
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


def _is_highlight_word(word: str, highlight_words: Sequence[str] | None = None) -> bool:
    if not highlight_words:
        return False
    lowered = word.lower().strip().strip(".!?,;:")
    for kw in highlight_words:
        if lowered == kw.lower().strip().strip(".!?,;:"):
            return True
    return False


def _cards(
    words: Sequence[CaptionWord],
    per_card: int,
    highlight_words: Sequence[str] | None = None,
) -> list[tuple[float, float, str, list[str]]]:
    """Group words into short display cards, breaking on pauses/punctuation.

    Returns (start, end, text, highlight_tags) where highlight_tags is a
    list of keyword words in the card that should be rendered in the
    highlight style.
    """
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

    out: list[tuple[float, float, str, list[str]]] = []
    for idx, (start, _end, group) in enumerate(cards):
        next_start = cards[idx + 1][0] if idx + 1 < len(cards) else start + 4.0
        end = max(start + 0.45, min(next_start, group[-1].end + 0.45))
        text = " ".join(w.text for w in group).strip()
        if not text:
            out.append((start, end, text, []))
            continue
        tags: list[str] = []
        if highlight_words:
            for w in group:
                if _is_highlight_word(w.text, highlight_words):
                    tags.append(w.text)
        out.append((start, end, text.upper(), tags))
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
    highlight_words: Sequence[str] | None = None,
) -> str:
    """Return a complete .ass document for one clip.

    Words that appear in ``highlight_words`` are given a distinct tag so
    the renderer can emit a per-word highlight style.  Cards containing
    highlight words are split so each highlighted word is styled
    individually via the ``CaptionHighlight`` / ``CaptionHighlightReverse``
    ASS styles.
    """
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

    # Process cards one at a time so we can split cards that contain
    # highlight words, emitting each highlighted word with its own style.
    prev_end = 0.0
    for card_idx, (start, end, text, tags) in enumerate(_cards(scaled, max(1, words_per_card), highlight_words)):
        if card_idx > 0:
            start = max(start, prev_end + 0.01)
        end = min(end, duration)
        if hook and start < hook_seconds - 0.05:
            prev_end = end
            continue
        if start >= duration - 0.15:
            break
        # Do not fight the outro card for the bottom third of the frame.
        if start >= outro_start and outro_text:
            break
        if end <= start:
            end = min(duration, start + 0.4)

        pop = "{\\fad(60,40)\\an2\\pos(540,1500)\\fscx86\\fscy86\\t(0,90,\\fscx100\\fscy100)}"
        if not tags:
            # No highlight words in this card: emit a plain Caption style.
            events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{pop}{_escape(text)}")
        else:
            # Split the card: emit highlighted words with the highlight
            # style, and non-highlighted words with the plain Caption
            # style.  We rebuild the card as separate dialogue lines.
            events.extend(
                _emit_highlighted_card(start, end, tags, text, pop, highlight_words)
            )
        prev_end = end

    if outro_text:
        events.append(
            f"Dialogue: 2,{_ts(outro_start)},{_ts(duration)},Outro,,0,0,0,,"
            f"{{\\fad(250,200)\\an5\\pos(540,1210)\\fscx92\\fscy92\\t(0,260,\\fscx100\\fscy100)}}"
            f"{_escape(outro_text.upper())}"
        )

    return ASS_HEADER.format(primary=hex_to_ass(primary_color)) + "\n".join(events) + "\n"


def _split_highlighted_card(
    card_start: float,
    card_end: float,
    card_text: str,
    tags: list[str],
    base_text: str,
    highlight_words: Sequence[str] | None,
) -> list[tuple[float, float, str, str]]:
    """Rebuild a card as a list of (start, end, text, style) chunks.

    Each chunk is either a plain word (Caption style) or a highlighted
    word (CaptionHighlight or CaptionHighlightReverse style).  We split
    on word boundaries so each chunk is a contiguous run of words that
    either all contain highlight tags or none do.
    """
    if not highlight_words:
        return [(card_start, card_end, base_text, "Caption")]

    # Build a word-level map: word index -> "highlighted" or "plain".
    plan: list[tuple[float, float, str, str]] = []
    words = re.split(r"\s+", base_text.strip())
    for wi, word in enumerate(words):
        is_highlight = any(
            _is_highlight_word(word, highlight_words) for word in tags
        )
        style = "CaptionHighlightReverse" if is_highlight else "Caption"
        # Each word keeps its offset relative to the card start; the
        # actual timing is applied by the renderer from the ASS timings.
        plan.append((card_start, card_end, word, style))
    return plan


def _emit_highlighted_card(
    card_start: float,
    card_end: float,
    tags: list[str],
    card_text: str,
    pop: str,
    highlight_words: Sequence[str] | None,
) -> list[str]:
    """Return dialogue lines for a card that contains highlight words.

    The card is split into contiguous runs of words that either all
    contain a highlight tag or none do, so each run gets a uniform style.
    """
    # Split the card text into words and reconstruct runs of words that
    # share the same highlight status.
    words = re.split(r"\s+", card_text.strip())
    runs: list[list[str]] = []
    current_run: list[str] = []
    last_style = None  # type: str | None
    for wi, word in enumerate(words):
        is_highlight = any(
            _is_highlight_word(word, highlight_words or []) for word in tags
        )
        style = "CaptionHighlightReverse" if is_highlight else "Caption"
        if last_style is not None and style != last_style:
            runs.append(current_run)
            current_run = []
        current_run.append(word)
        last_style = style
    if current_run:
        runs.append(current_run)

    # If no runs were produced (e.g. empty text), fall back to plain.
    if not runs:
        return [f"Dialogue: 0,{_ts(card_start)},{_ts(card_end)},Caption,,0,0,0,,{pop}{_escape(card_text)}"]

    # Emit each run.  We reassemble the words with a single space and
    # apply the per-word highlight tag using a separate dialogue entry.
    lines: list[str] = []
    for run in runs:
        text = " ".join(run).strip()
        style = "CaptionHighlightReverse" if runs.index(run) % 2 == 1 else "Caption"
        if not any(_is_highlight_word(w, highlight_words or []) for w in run):
            style = "Caption"
        lines.append(f"Dialogue: 0,{_ts(card_start)},{_ts(card_end)},{style},,0,0,0,,{pop}{_escape(text)}")
    return lines


def hex_to_ass(color: str) -> str:
    """#FFD700 -> &H00D7FF& (ASS uses &HAABBGGRR)."""
    value = color.strip().lstrip("#")
    if len(value) != 6:
        value = "FFD700"
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H00{b}{g}{r}&"
