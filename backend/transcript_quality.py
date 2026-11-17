"""Summaries of the Whisper evidence we keep for a transcript.

Stage 3A deliberately does not classify or reject clips.  This module only
reports what the transcript actually contains: available confidence metrics,
word probabilities, repetition indicators, and speech coverage.  Missing
values stay missing; nothing here guesses a metric or applies a threshold.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable, Sequence

_METRIC_KEYS = (
    "avg_logprob",
    "no_speech_prob",
    "compression_ratio",
    "temperature",
    "word_probability",
    "duration_after_vad",
    "language_probability",
    "all_language_probs",
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?؟。！？])\s+")
_TOKEN_SPLIT = re.compile(r"[^\w']+", re.UNICODE)


def finite_float(value: Any) -> float | None:
    """Return a finite float, or ``None`` for absent/non-numeric values."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def optional_int(value: Any) -> int | None:
    """Return an int when the source value is genuinely integral."""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number


def _get(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _iter_words(segments: Sequence[Any]) -> Iterable[Any]:
    for segment in segments:
        for word in _get(segment, "words") or []:
            yield word


def _normalise(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _tokens(text: Any) -> list[str]:
    return [token for token in _TOKEN_SPLIT.split(_normalise(text)) if token]


def _summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def _repeat_summary(segments: Sequence[Any]) -> dict[str, Any]:
    texts = [_normalise(_get(segment, "text")) for segment in segments]
    nonempty = [text for text in texts if text]

    duplicate_segments = sum(count - 1 for count in Counter(nonempty).values() if count > 1)

    longest_run = 0
    current_run = 0
    previous = ""
    for text in nonempty:
        if text and text == previous:
            current_run += 1
        else:
            current_run = 1
        longest_run = max(longest_run, current_run)
        previous = text

    sentences: list[str] = []
    for segment in segments:
        for sentence in _SENTENCE_SPLIT.split(str(_get(segment, "text") or "")):
            normalised = _normalise(sentence)
            if normalised:
                sentences.append(normalised)
    sentence_counts = Counter(sentences)
    duplicate_sentences = sum(
        count - 1
        for sentence, count in sentence_counts.items()
        if count > 1 and len(_tokens(sentence)) >= 2
    )

    all_tokens: list[str] = []
    for segment in segments:
        all_tokens.extend(_tokens(_get(segment, "text")))
    trigrams = [tuple(all_tokens[index : index + 3]) for index in range(max(0, len(all_tokens) - 2))]
    repeated_trigrams = len(trigrams) - len(set(trigrams)) if trigrams else 0
    repeated_ratio = repeated_trigrams / len(trigrams) if trigrams else 0.0

    return {
        "duplicate_segments": duplicate_segments,
        "duplicate_sentences": duplicate_sentences,
        "longest_consecutive_run": longest_run,
        "repeated_3gram_ratio": round(repeated_ratio, 6),
        "text_token_count": len(all_tokens),
    }


def _language_summary(
    language_probability: Any,
    all_language_probs: Any,
) -> dict[str, Any]:
    probabilities: list[float] = []
    if isinstance(all_language_probs, (list, tuple)):
        for entry in all_language_probs:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            probability = finite_float(entry[1])
            if probability is not None:
                probabilities.append(probability)

    direct = finite_float(language_probability)
    ranked = sorted(probabilities, reverse=True)
    top = direct if direct is not None else (ranked[0] if ranked else None)
    second = ranked[1] if len(ranked) > 1 else None
    margin = round(top - second, 6) if top is not None and second is not None else None
    return {
        "probability": direct,
        "top_probability": top,
        "second_probability": second,
        "margin": margin,
        "all_probabilities_count": len(probabilities),
        "all_probabilities_available": bool(probabilities),
    }


def summarize_transcript(
    segments: Sequence[Any],
    *,
    duration: Any = None,
    duration_after_vad: Any = None,
    language_probability: Any = None,
    all_language_probs: Any = None,
) -> dict[str, Any]:
    """Return a JSON-safe summary of the evidence present in ``segments``.

    ``segments`` may contain dicts (as returned by ``transcribe``) or objects
    with matching attributes.  No thresholds are applied and no missing value
    is inferred from another field.
    """
    segments = list(segments or [])
    words = list(_iter_words(segments))

    avg_logprobs = [
        value
        for value in (finite_float(_get(segment, "avg_logprob")) for segment in segments)
        if value is not None
    ]
    no_speech = [
        value
        for value in (finite_float(_get(segment, "no_speech_prob")) for segment in segments)
        if value is not None
    ]
    compression = [
        value
        for value in (finite_float(_get(segment, "compression_ratio")) for segment in segments)
        if value is not None
    ]
    temperatures = [
        value
        for value in (finite_float(_get(segment, "temperature")) for segment in segments)
        if value is not None
    ]
    word_probabilities = [
        value
        for value in (finite_float(_get(word, "probability")) for word in words)
        if value is not None
    ]

    duration_value = finite_float(duration)
    vad_duration = finite_float(duration_after_vad)
    coverage = None
    if duration_value is not None and duration_value > 0 and vad_duration is not None:
        coverage = {
            "source_duration": round(duration_value, 6),
            "duration_after_vad": round(vad_duration, 6),
            "ratio": round(max(0.0, min(1.0, vad_duration / duration_value)), 6),
        }

    language = _language_summary(language_probability, all_language_probs)

    available = {
        "avg_logprob": bool(avg_logprobs),
        "no_speech_prob": bool(no_speech),
        "compression_ratio": bool(compression),
        "temperature": bool(temperatures),
        "word_probability": bool(word_probabilities),
        "duration_after_vad": vad_duration is not None,
        "language_probability": language["probability"] is not None,
        "all_language_probs": language["all_probabilities_available"],
    }
    missing = [key for key in _METRIC_KEYS if not available[key]]

    return {
        "segment_count": len(segments),
        "word_count": len(words),
        "available_metrics": available,
        "missing_metrics": missing,
        "avg_logprob": _summary(avg_logprobs),
        "no_speech_prob": _summary(no_speech),
        "compression_ratio": _summary(compression),
        "temperature": {
            "count": len(temperatures),
            "values": sorted(set(round(value, 6) for value in temperatures)),
        },
        "word_probability": _summary(word_probabilities),
        "speech_coverage": coverage,
        "language": language,
        "repeated_text": _repeat_summary(segments),
    }
