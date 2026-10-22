"""Viral moment detection for African-tales style storytelling.

A candidate window is scored from three signals:

1. Story keywords   - ``warned``, ``forbidden``, ``spirit``, ``curse``, ``night``,
                      ``disappeared``, ``village`` ... (configurable in config.json)
2. Delivery         - questions, exclamations, first-person hooks, spoken words
                      per second, and a bonus for a strong opening line.
3. Audio energy     - RMS volume spikes against the rolling median, which is a
                      decent proxy for shouts, gasps and dramatic beats.

The result is a 0-100 "viral score" plus human-readable reasons that the
dashboard displays next to each clip.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

DEFAULT_KEYWORDS = [
    "warned", "forbidden", "spirit", "curse", "night", "disappeared", "village",
    "grandmother", "grandfather", "chief", "witch", "ghost", "mermaid", "ancestors",
    "ritual", "taboo", "sacrifice", "forest", "river", "moon", "secret", "never",
    "don't", "do not", "blood", "death", "died", "buried", "grave", "midnight",
    "prophecy", "dream", "hunter", "lion", "snake", "magic", "medicine man",
    "disappear", "vanished", "screaming", "haunted", "cursed", "blessing", "elders",
    "tradition", "legend", "myth", "true story", "happened", "terrifying", "warning",
]

# Words that almost always sit inside a strong hook sentence.
POWER_WORDS = {
    "warned", "forbidden", "curse", "cursed", "spirit", "ghost", "witch", "blood",
    "death", "died", "disappeared", "vanished", "disappear", "secret", "never",
    "terrifying", "haunted", "sacrifice", "taboo", "midnight", "grave", "buried",
}

SENTENCE_END = re.compile(r"[.!?][\"')\]]?$")


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Sentence:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Candidate:
    start: float
    end: float
    text: str
    words: list[Word]
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)

    def summary(self) -> dict:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "duration": self.duration,
            "viral_score": round(self.score, 1),
            "reasons": self.reasons,
            "text": self.text.strip(),
        }


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text.lower())


def compute_rms(wav_path: str, bucket: float = 0.5) -> list[float]:
    """Per-bucket RMS energy of a 16-bit mono WAV (uses only the stdlib)."""
    import array
    import wave

    try:
        with wave.open(wav_path, "rb") as wf:
            if wf.getsampwidth() != 2:
                return []
            rate = wf.getframerate()
            frames_per_bucket = max(1, int(rate * bucket))
            energies: list[float] = []
            while True:
                chunk = wf.readframes(frames_per_bucket)
                if not chunk:
                    break
                samples = array.array("h")
                samples.frombytes(chunk)
                if not samples:
                    break
                acc = 0.0
                for value in samples:
                    acc += value * value
                energies.append(math.sqrt(acc / len(samples)) / 32768.0)
            return energies
    except (OSError, wave.Error):
        return []


def _rms_at(rms: Sequence[float], start: float, end: float, bucket: float = 0.5) -> float:
    if not rms:
        return 0.0
    lo = max(0, int(start / bucket))
    hi = min(len(rms), max(lo + 1, int(end / bucket)))
    window = rms[lo:hi]
    return sum(window) / len(window) if window else 0.0


def _audio_spike(rms: Sequence[float], start: float, end: float) -> float:
    """How much louder the window's peaks are versus the rest of the source."""
    if not rms:
        return 0.0
    window = rms[max(0, int(start / 0.5)): int(end / 0.5)] or list(rms)
    peak = max(window)
    median = sorted(rms)[len(rms) // 2] or 1e-6
    ratio = peak / median
    return max(0.0, min(1.0, (ratio - 1.0) / 2.5))


def _score_text(text: str, keywords: Iterable[str], audio_peak: float) -> tuple[float, list[str]]:
    lower = text.lower()
    tokens = _word_tokens(text)
    if not tokens:
        return 0.0, []

    score = 0.0
    reasons: list[str] = []

    keyword_hits = [k for k in keywords if k and k in lower]
    if keyword_hits:
        weight = sum(2.6 if k in POWER_WORDS else 1.6 for k in keyword_hits)
        score += min(24.0, weight)
        reasons.append("story keywords: " + ", ".join(sorted(set(keyword_hits))[:6]))

    question_marks = text.count("?")
    if question_marks:
        score += min(9.0, question_marks * 4.5)
        reasons.append("question hook")

    exclamations = text.count("!")
    if exclamations:
        score += min(6.0, exclamations * 2.0)

    if re.search(r"\b(i|my|me|we|our)\b", lower):
        score += 4.0
        reasons.append("first-person storytelling")

    if re.search(r"\b\d{2,}\b|\b(one|two|three|seven|hundred|thousand)\b", lower):
        score += 2.0

    if lower.count("you") >= 2:
        score += 2.0
        reasons.append("direct address")

    # A strong opening line is what stops the scroll.
    opener = " ".join(tokens[:12])
    if any(w in opener for w in POWER_WORDS):
        score += 8.0
        reasons.append("opens on a high-tension beat")

    density = len(tokens) / max(5.0, len(text) / 14.0)
    score += min(6.0, density * 1.2)

    score += audio_peak * 14.0
    if audio_peak > 0.45:
        reasons.append("volume spike")

    return score, reasons


def build_segments(raw_segments: Sequence[dict]) -> list[Segment]:
    """Normalise faster-whisper output into Segment/Word objects."""
    segments: list[Segment] = []
    for raw in raw_segments:
        text = (raw.get("text") or "").strip()
        start = float(raw.get("start", 0.0))
        end = float(raw.get("end", start))
        if not text or end <= start:
            continue
        words = [
            Word(float(w.get("start", start)), float(w.get("end", end)), (w.get("word") or "").strip())
            for w in raw.get("words") or []
            if w.get("word")
        ]
        segments.append(Segment(start, end, text, words))
    return segments


def _join(segments: Sequence[Segment]) -> str:
    return " ".join(s.text.strip() for s in segments).strip()


def _words_between(segments: Sequence[Segment]) -> list[Word]:
    words: list[Word] = []
    for seg in segments:
        words.extend(seg.words)
    return words


def find_candidates(
    segments: Sequence[Segment],
    rms: Sequence[float],
    keywords: Sequence[str] | None = None,
    min_seconds: float = 30.0,
    max_seconds: float = 45.0,
) -> list[Candidate]:
    keywords = list(keywords or DEFAULT_KEYWORDS)
    candidates: list[Candidate] = []

    for i in range(len(segments)):
        window: list[Segment] = []
        for j in range(i, len(segments)):
            window.append(segments[j])
            duration = window[-1].end - window[0].start
            if duration < min_seconds:
                continue
            if duration > max_seconds:
                break
            text = _join(window)
            spike = _audio_spike(rms, window[0].start, window[-1].end)
            score, reasons = _score_text(text, keywords, spike)
            # Prefer windows that land on a sentence end and fill the 30-45s slot.
            if SENTENCE_END.search(window[-1].text.strip()):
                score += 4.0
                reasons.append("ends on a complete beat")
            score += 4.0 * (1 - abs(duration - 37.5) / 20.0)
            if duration >= 34:
                reasons.append("full-length story beat")
            candidates.append(
                Candidate(
                    start=window[0].start,
                    end=window[-1].end,
                    text=text,
                    words=_words_between(window),
                    score=max(0.0, min(100.0, score * 2.1)),
                    reasons=reasons,
                )
            )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def _overlaps(candidate: Candidate, chosen: Sequence[Candidate], gap: float = 0.4) -> bool:
    for other in chosen:
        if candidate.start < other.end + gap and other.start - gap < candidate.end:
            return True
    return False


def select_top(
    candidates: Sequence[Candidate],
    count: int,
    min_seconds: float = 30.0,
    max_seconds: float = 45.0,
) -> list[Candidate]:
    """Greedy non-overlapping selection, best viral score first."""
    chosen: list[Candidate] = []
    for cand in candidates:
        if len(chosen) >= count:
            break
        if cand.duration < min_seconds - 0.5 or cand.duration > max_seconds + 0.5:
            continue
        if _overlaps(cand, chosen):
            continue
        chosen.append(cand)
    chosen.sort(key=lambda c: c.start)
    return chosen


def fallback_windows(
    duration: float,
    count: int,
    min_seconds: float = 30.0,
    max_seconds: float = 45.0,
) -> list[Candidate]:
    """Evenly spaced windows used when the transcript is unusable."""
    if duration <= 5:
        return []
    length = max(min_seconds, min(max_seconds, duration))
    length = min(length, max(8.0, duration))
    slots = max(1, count)
    step = max(length + 1.0, (duration - length) / slots)
    out: list[Candidate] = []
    for i in range(slots):
        start = min(i * step, max(0.0, duration - length))
        end = min(duration, start + length)
        if end - start < min(8.0, duration):
            continue
        out.append(
            Candidate(
                start=start,
                end=end,
                text="",
                words=[],
                score=round(max(20.0, 60.0 - i * 3.0), 1),
                reasons=["no speech detected - visual highlight"],
            )
        )
    return out


def hook_text(candidate: Candidate, max_chars: int = 62) -> str:
    """Short, punchy overlay used for the first two seconds."""
    text = (candidate.text or "").strip()
    if not text:
        return "WAIT FOR THE END"
    sentence = re.split(r"(?<=[.!?])\s+", text)[0]
    if len(sentence) > max_chars:
        sentence = sentence[: max_chars - 1].rsplit(" ", 1)[0] + "..."
    return sentence.upper()


def social_caption(candidate: Candidate, hashtags: str) -> str:
    text = re.sub(r"\s+", " ", candidate.text or "").strip()
    if len(text) > 180:
        text = text[:177].rsplit(" ", 1)[0] + "..."
    tags = hashtags.strip()
    return f"{text}\n\n{tags}" if text and tags else (text or tags)
