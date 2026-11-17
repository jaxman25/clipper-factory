"""Descriptive quality assessment for transcript-backed clip candidates.

This module turns the Whisper evidence preserved in Stage 3A into one of three
outcomes:

* ``good``   - enough independent evidence is available and nothing looks
               unreliable.
* ``review`` - evidence is mixed, incomplete, or only weakly concerning.  A
               review candidate is still usable: missing metrics never become
               an automatic rejection.
* ``poor``   - at least two independent warning indicators agree that the
               transcript window is unreliable.

The thresholds below are provisional engineering guards, not calibrated
accuracy estimates.  They are intentionally conservative and explain every
warning in ``assessment["warnings"]``.  Language-identification confidence is
deliberately *not* used: it says which language Whisper heard, not how
accurately it recognized individual words.
"""
from __future__ import annotations

from typing import Any, Sequence

try:
    from backend import transcript_quality
except ImportError:  # pragma: no cover - direct execution
    import transcript_quality  # type: ignore

# Provisional thresholds.  They are deliberately round numbers and are not
# presented as scientifically calibrated.
AVG_LOGPROB_WARN = -1.0
AVG_LOGPROB_SEVERE = -1.5
NO_SPEECH_WARN = 0.60
NO_SPEECH_SEVERE = 0.85
COMPRESSION_WARN = 2.4
COMPRESSION_SEVERE = 3.0
TEMPERATURE_WARN = 0.60
TEMPERATURE_SEVERE = 0.90
WORD_PROBABILITY_WARN = 0.50
WORD_PROBABILITY_SEVERE = 0.35
LOW_WORD_FRACTION_WARN = 0.30
REPEATED_3GRAM_WARN = 0.35
REPEATED_RUN_WARN = 3

SEGMENT_METRICS = (
    "avg_logprob",
    "no_speech_prob",
    "compression_ratio",
    "temperature",
    "word_probability",
)


def _get(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _word_probabilities(segments: Sequence[Any]) -> list[float]:
    values: list[float] = []
    for segment in segments:
        for word in _get(segment, "words") or []:
            value = transcript_quality.finite_float(_get(word, "probability"))
            if value is not None:
                values.append(value)
    return values


def _warning(
    code: str,
    metric: str,
    value: float,
    threshold: float,
    severity: str,
    message: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "metric": metric,
        "value": round(value, 6),
        "threshold": threshold,
        "severity": severity,
        "message": message,
    }


def unavailable(reason: str = "no transcript quality evidence available") -> dict[str, Any]:
    """Explicit assessment for a candidate that has no metrics to inspect."""
    return {
        "status": "review",
        "available": False,
        "provisional": True,
        "reasons": [reason],
        "warnings": [],
        "evidence": {},
        "missing_metrics": list(SEGMENT_METRICS),
        "language_confidence_used": False,
    }


def assess_segments(
    segments: Sequence[Any],
    *,
    text: str | None = None,
) -> dict[str, Any]:
    """Assess one candidate window from the segments that produced it.

    ``segments`` may be :class:`backend.viral.Segment` objects or the raw
    dictionaries returned by ``transcribe``.  No text is invented or rewritten.
    """
    window = list(segments or [])
    if not window:
        return unavailable("no transcript segments in this candidate")

    summary = transcript_quality.summarize_transcript(window)
    repeated = summary["repeated_text"]
    word_values = _word_probabilities(window)
    warnings: list[dict[str, Any]] = []

    avg = summary["avg_logprob"]["mean"]
    if avg is not None:
        if avg <= AVG_LOGPROB_SEVERE:
            warnings.append(
                _warning(
                    "low_avg_logprob",
                    "avg_logprob",
                    avg,
                    AVG_LOGPROB_SEVERE,
                    "severe",
                    "Whisper's average token confidence is very low.",
                )
            )
        elif avg <= AVG_LOGPROB_WARN:
            warnings.append(
                _warning(
                    "uncertain_avg_logprob",
                    "avg_logprob",
                    avg,
                    AVG_LOGPROB_WARN,
                    "warning",
                    "Whisper's average token confidence is below the review guard.",
                )
            )

    no_speech = summary["no_speech_prob"]["mean"]
    if no_speech is not None:
        if no_speech >= NO_SPEECH_SEVERE:
            warnings.append(
                _warning(
                    "high_no_speech_prob",
                    "no_speech_prob",
                    no_speech,
                    NO_SPEECH_SEVERE,
                    "severe",
                    "The window contains strong no-speech evidence.",
                )
            )
        elif no_speech >= NO_SPEECH_WARN:
            warnings.append(
                _warning(
                    "elevated_no_speech_prob",
                    "no_speech_prob",
                    no_speech,
                    NO_SPEECH_WARN,
                    "warning",
                    "The window contains elevated no-speech evidence.",
                )
            )

    compression = summary["compression_ratio"]["max"]
    if compression is not None:
        if compression >= COMPRESSION_SEVERE:
            warnings.append(
                _warning(
                    "high_compression_ratio",
                    "compression_ratio",
                    compression,
                    COMPRESSION_SEVERE,
                    "severe",
                    "Text compression suggests repeated or degenerate decoding.",
                )
            )
        elif compression >= COMPRESSION_WARN:
            warnings.append(
                _warning(
                    "elevated_compression_ratio",
                    "compression_ratio",
                    compression,
                    COMPRESSION_WARN,
                    "warning",
                    "Text compression is above the review guard.",
                )
            )

    temperatures = summary["temperature"]["values"]
    temperature = max(temperatures) if temperatures else None
    if temperature is not None:
        if temperature >= TEMPERATURE_SEVERE:
            warnings.append(
                _warning(
                    "high_temperature",
                    "temperature",
                    temperature,
                    TEMPERATURE_SEVERE,
                    "severe",
                    "The window needed a high-temperature fallback decode.",
                )
            )
        elif temperature >= TEMPERATURE_WARN:
            warnings.append(
                _warning(
                    "elevated_temperature",
                    "temperature",
                    temperature,
                    TEMPERATURE_WARN,
                    "warning",
                    "The window needed a non-zero fallback decode temperature.",
                )
            )

    word_mean = summary["word_probability"]["mean"]
    low_words = [value for value in word_values if value < WORD_PROBABILITY_SEVERE]
    low_fraction = len(low_words) / len(word_values) if word_values else 0.0
    if word_mean is not None:
        if word_mean <= WORD_PROBABILITY_SEVERE:
            warnings.append(
                _warning(
                    "low_word_probability",
                    "word_probability",
                    word_mean,
                    WORD_PROBABILITY_SEVERE,
                    "severe",
                    "Average word probability is very low.",
                )
            )
        elif word_mean < WORD_PROBABILITY_WARN:
            warnings.append(
                _warning(
                    "uncertain_word_probability",
                    "word_probability",
                    word_mean,
                    WORD_PROBABILITY_WARN,
                    "warning",
                    "Average word probability is below the review guard.",
                )
            )
        elif low_fraction >= LOW_WORD_FRACTION_WARN:
            warnings.append(
                _warning(
                    "many_low_probability_words",
                    "word_probability",
                    low_fraction,
                    LOW_WORD_FRACTION_WARN,
                    "warning",
                    "A large share of words are individually low-confidence.",
                )
            )

    repeated_ratio = float(repeated.get("repeated_3gram_ratio") or 0.0)
    longest_run = int(repeated.get("longest_consecutive_run") or 0)
    duplicate_segments = int(repeated.get("duplicate_segments") or 0)
    if (
        repeated_ratio >= REPEATED_3GRAM_WARN
        or longest_run >= REPEATED_RUN_WARN
        or duplicate_segments >= 2
    ):
        warnings.append(
            _warning(
                "repetition",
                "repeated_text",
                max(repeated_ratio, float(longest_run)),
                max(REPEATED_3GRAM_WARN, float(REPEATED_RUN_WARN)),
                "warning",
                "Repetition indicators are elevated; this alone never rejects a "
                "candidate because legitimate repeated phrases exist.",
            )
        )

    token_count = int(repeated.get("text_token_count") or 0)
    reasons: list[str] = []
    if token_count < 3:
        status = "review"
        reasons.append("too little transcript text to assess reliably")
    else:
        severe_count = sum(1 for item in warnings if item["severity"] == "severe")
        if severe_count >= 2 or (severe_count >= 1 and len(warnings) >= 2):
            status = "poor"
            reasons.append("multiple independent warning indicators agree")
        elif warnings:
            status = "review"
            reasons.append("at least one warning indicator needs review")
        else:
            core_available = sum(
                1
                for key in ("avg_logprob", "no_speech_prob", "compression_ratio")
                if summary["available_metrics"].get(key)
            )
            word_available = summary["available_metrics"].get("word_probability", False)
            if core_available >= 2 or (core_available >= 1 and word_available):
                status = "good"
                reasons.append("available confidence indicators are within guards")
            else:
                status = "review"
                reasons.append("limited metric coverage; missing values are not treated as poor")

    if warnings:
        reasons.extend(item["message"] for item in warnings)

    missing = [
        key for key in SEGMENT_METRICS if not summary["available_metrics"].get(key)
    ]
    if missing:
        reasons.append("missing optional metrics: " + ", ".join(missing))
    evidence = {
        "segment_count": len(window),
        "text_token_count": token_count,
        "avg_logprob": summary["avg_logprob"],
        "no_speech_prob": summary["no_speech_prob"],
        "compression_ratio": summary["compression_ratio"],
        "temperature": summary["temperature"],
        "word_probability": summary["word_probability"],
        "low_word_fraction": round(low_fraction, 6),
        "repeated_text": repeated,
    }
    return {
        "status": status,
        "available": bool(
            summary["avg_logprob"]["count"]
            or summary["no_speech_prob"]["count"]
            or summary["compression_ratio"]["count"]
            or summary["temperature"]["count"]
            or summary["word_probability"]["count"]
        ),
        "provisional": True,
        "reasons": reasons,
        "warnings": warnings,
        "evidence": evidence,
        "missing_metrics": missing,
        "language_confidence_used": False,
    }


def status_of(candidate: Any) -> str:
    """Return a candidate's status, defaulting to review for old objects."""
    assessment = _get(candidate, "quality")
    if isinstance(assessment, dict):
        status = assessment.get("status")
        if status in {"good", "review", "poor"}:
            return str(status)
    return "review"


def is_poor(candidate: Any) -> bool:
    return status_of(candidate) == "poor"


def rank(candidate: Any) -> int:
    """Sort rank: good first, then review.  Poor is filtered before this."""
    return 0 if status_of(candidate) == "good" else 1


def compact(assessment: Any) -> dict[str, Any]:
    """Small queue/manifest view of an assessment, retaining its evidence."""
    if not isinstance(assessment, dict):
        return unavailable("candidate was not assessed")
    return {
        "status": assessment.get("status", "review"),
        "available": assessment.get("available", False),
        "provisional": True,
        "reasons": list(assessment.get("reasons") or []),
        "warnings": list(assessment.get("warnings") or []),
        "missing_metrics": list(assessment.get("missing_metrics") or []),
        "language_confidence_used": False,
        "evidence": {
            key: value
            for key, value in (assessment.get("evidence") or {}).items()
            if key
            in {
                "segment_count",
                "text_token_count",
                "avg_logprob",
                "no_speech_prob",
                "compression_ratio",
                "temperature",
                "word_probability",
                "low_word_fraction",
                "repeated_text",
            }
        },
    }
