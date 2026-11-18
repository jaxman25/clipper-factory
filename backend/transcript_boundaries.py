"""Safe transcript-boundary primitives.

This module is intentionally independent of clip selection and rendering.  It
normalises timestamps, joins already-recognised text, and exposes conservative
sentence information so later stages can make boundary decisions without
inventing words, punctuation or timings.

The helpers here never rewrite transcript wording.  Fingerprints are only for
comparison and diagnostics; they are not a replacement for the transcript.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from difflib import SequenceMatcher
from typing import Any

try:
    from backend import transcript_quality
except ImportError:  # pragma: no cover - direct execution
    import transcript_quality  # type: ignore


# Definitive sentence-ending marks.  The set is deliberately a union across
# languages: detected language can be wrong, and a miss is worse than accepting
# a punctuation mark that the current language does not normally use.
_STRONG_MARKS = frozenset(".!?؟。！？।॥．｡")
# An ellipsis can mark a pause or an unfinished thought, so it is never treated
# as proof that a sentence is complete.
_WEAK_MARKS = frozenset("…")
_ALL_MARKS = _STRONG_MARKS | _WEAK_MARKS
_CLOSING_MARKS = frozenset(
    "\"'”’»)]}〉》」』】〙〗〞"
)

_SEGMENT_FIELDS = (
    "id",
    "seek",
    "start",
    "end",
    "text",
    "avg_logprob",
    "no_speech_prob",
    "compression_ratio",
    "temperature",
    "tokens",
    "words",
)
_WORD_FIELDS = ("start", "end", "word", "text", "probability")
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def finite_time(value: Any) -> float | None:
    """Return a finite, non-negative timestamp, or ``None``.

    ``None``, NaN, positive/negative infinity, non-numeric strings and negative
    values are rejected.  This helper never substitutes a timestamp.
    """
    number = transcript_quality.finite_float(value)
    if number is None or number < 0.0:
        return None
    return float(number)


def _payload(item: Any, fields: Sequence[str]) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    result: dict[str, Any] = {}
    for field in fields:
        if hasattr(item, field):
            result[field] = getattr(item, field)
    return result


def _sanitize_word(word: Any) -> dict[str, Any] | None:
    payload = _payload(word, _WORD_FIELDS)
    text = _get(word, "word")
    if text is None:
        # ``viral.Word`` stores its token in ``text`` while Whisper raw words
        # use ``word``.  Supporting both keeps the helper usable for candidate
        # words and raw transcript dictionaries.
        text = _get(word, "text")
    if text is None:
        return None
    text = str(text)
    if not text.strip():
        return None

    start = finite_time(_get(word, "start"))
    end = finite_time(_get(word, "end"))
    if start is None or end is None or end < start:
        return None

    payload["start"] = start
    payload["end"] = end
    payload["word"] = text
    return payload


def sanitize_segments(raw_segments: Sequence[Any] | None) -> list[dict[str, Any]]:
    """Return transcript segments with safe timestamps and valid words.

    Segment text and metadata are copied without rewriting.  Segments with a
    missing, non-finite or reversed time range are omitted.  Words with invalid
    timestamps are omitted from the word list; their text remains in the
    segment's original ``text`` field.  Missing optional fields stay missing.
    """
    if raw_segments is None:
        return []
    try:
        source = list(raw_segments)
    except TypeError:
        return []

    segments: list[dict[str, Any]] = []
    for raw in source:
        start = finite_time(_get(raw, "start"))
        end = finite_time(_get(raw, "end"))
        if start is None or end is None or end <= start:
            continue

        payload = _payload(raw, _SEGMENT_FIELDS)
        payload["start"] = start
        payload["end"] = end

        if isinstance(raw, Mapping):
            has_words = "words" in raw
        else:
            has_words = hasattr(raw, "words")
        if has_words:
            raw_words = _get(raw, "words") or []
            try:
                word_iter = list(raw_words)
            except TypeError:
                word_iter = []
            payload["words"] = [
                word
                for word in (_sanitize_word(item) for item in word_iter)
                if word is not None
            ]
        segments.append(payload)
    return segments


def _language_key(language: Any) -> str:
    return str(language or "").strip().lower().replace("_", "-").split("-", 1)[0]


_NO_SPACE_LANGUAGES = frozenset({"zh", "ja", "th", "lo", "km", "my"})


def _is_no_space_char(char: str) -> bool:
    """Whether a character belongs to a script normally written without spaces."""
    if not char:
        return False
    code = ord(char)
    return (
        0x0E00 <= code <= 0x0E7F  # Thai
        or 0x0E80 <= code <= 0x0EFF  # Lao
        or 0x1000 <= code <= 0x109F  # Myanmar
        or 0x1780 <= code <= 0x17FF  # Khmer
        or 0x3000 <= code <= 0x303F  # CJK punctuation
        or 0x3040 <= code <= 0x30FF  # Hiragana/Katakana
        or 0x3400 <= code <= 0x4DBF  # CJK extension A
        or 0x4E00 <= code <= 0x9FFF  # CJK unified ideographs
        or 0xF900 <= code <= 0xFAFF  # CJK compatibility ideographs
        or 0x20000 <= code <= 0x2FA1F  # CJK extensions B-F
    )


def _no_space_boundary(previous: str, following: str, language: Any) -> bool:
    if not previous or not following:
        return False
    # Script detection is preferred over the language hint because a detected
    # language can be wrong.  Both sides must belong to a no-space script.
    if _is_no_space_char(previous[-1]) and _is_no_space_char(following[0]):
        return True
    # If one side is a no-space script and the other is ordinary word text, a
    # separator remains the safer choice.  The language hint is intentionally
    # conservative: it does not remove a space between mixed scripts.
    key = _language_key(language)
    if key in _NO_SPACE_LANGUAGES:
        return _is_no_space_char(previous[-1]) and _is_no_space_char(following[0])
    return False


def join_segment_text(parts: Iterable[Any] | None, language: Any = None) -> str:
    """Join transcript parts without adding or deleting words.

    Only outer boundary whitespace is removed.  A single separating space is
    used for spaced scripts; adjacent CJK/Thai/Lao/Khmer/Myanmar characters keep
    their natural lack of a space.  Repeated phrases and punctuation are left
    untouched.
    """
    if parts is None:
        return ""
    if isinstance(parts, str):
        parts = [parts]

    cleaned = [str(part).strip() for part in parts if part is not None]
    cleaned = [part for part in cleaned if part]
    if not cleaned:
        return ""

    result = cleaned[0]
    for part in cleaned[1:]:
        separator = "" if _no_space_boundary(result, part, language) else " "
        result += separator + part
    return result


def sentence_marks(language: Any = None) -> frozenset[str]:
    """Return the supported sentence-ending marks.

    A union is returned regardless of ``language`` so an incorrect detection
    does not hide a valid boundary.  Callers must still distinguish strong
    marks from the weak ellipsis via :func:`boundary_strength`.
    """
    return _ALL_MARKS


def _without_closing_marks(text: Any) -> str:
    value = str(text or "").rstrip()
    while value and value[-1] in _CLOSING_MARKS:
        value = value[:-1].rstrip()
    return value


def boundary_strength(text: Any, language: Any = None) -> str:
    """Classify a text ending as ``strong``, ``weak`` or ``none``.

    Closing quotes and brackets are ignored when looking for punctuation.
    Ellipsis is weak; punctuationless text is always ``none``.
    """
    value = _without_closing_marks(text)
    if not value:
        return "none"
    if value.endswith("..."):
        return "weak"
    mark = value[-1]
    if mark in _WEAK_MARKS:
        return "weak"
    if mark in _STRONG_MARKS:
        return "strong"
    return "none"


def terminal_mark(text: Any, language: Any = None) -> str | None:
    """Return the potential terminal punctuation, or ``None``.

    ASCII ``...`` is returned as ``"..."``.  The helper does not claim that the
    text is a complete sentence; use :func:`is_sentence_end` for that.
    """
    value = _without_closing_marks(text)
    if not value:
        return None
    if value.endswith("..."):
        return "..."
    mark = value[-1]
    return mark if mark in _ALL_MARKS else None


def is_sentence_end(text: Any, language: Any = None) -> bool:
    """True only for a definitive sentence-ending mark.

    Ellipsis and punctuationless text return ``False``.
    """
    return boundary_strength(text, language) == "strong"


def _span(
    *,
    start: float,
    end: float,
    text: str,
    source: str,
    language: Any,
) -> dict[str, Any] | None:
    text = text.strip()
    if not text or end <= start:
        return None
    strength = boundary_strength(text, language)
    return {
        "start": start,
        "end": end,
        "text": text,
        "complete": strength == "strong",
        "weak": strength == "weak",
        "source": source,
    }


def sentence_spans(
    segments: Sequence[Any] | None,
    language: Any = None,
) -> list[dict[str, Any]]:
    """Return conservative sentence spans in chronological order.

    Valid word timestamps are used when available.  A sentence can continue
    across Whisper segment boundaries.  Segments without valid word timestamps
    fall back to their own start/end and text.  No punctuation is added, no
    missing word timing is inferred, and punctuationless text is never marked
    complete.
    """
    spans: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def flush_words() -> None:
        if not pending:
            return
        text = join_segment_text(
            [str(word.get("word") or "") for word in pending], language
        )
        span = _span(
            start=float(pending[0]["start"]),
            end=float(pending[-1]["end"]),
            text=text,
            source="words",
            language=language,
        )
        if span is not None:
            spans.append(span)
        pending.clear()

    for segment in sanitize_segments(segments):
        words = segment.get("words") or []
        if words:
            for word in words:
                pending.append(word)
                if boundary_strength(word.get("word"), language) != "none":
                    flush_words()
            continue

        # No usable word timing: keep the segment intact rather than inventing
        # word-level boundaries.
        flush_words()
        start = float(segment["start"])
        end = float(segment["end"])
        text = join_segment_text([segment.get("text") or ""], language)
        span = _span(
            start=start,
            end=end,
            text=text,
            source="segment",
            language=language,
        )
        if span is not None:
            spans.append(span)

    flush_words()
    spans.sort(key=lambda item: item["start"])
    return spans


def _candidate_boundary_words(
    candidate: Any,
    word_context: Sequence[Any] | None,
    allowed_start: float,
    allowed_end: float,
) -> list[dict[str, Any]]:
    raw = word_context if word_context is not None else _get(candidate, "words") or []
    try:
        source = list(raw)
    except TypeError:
        source = []
    words = [word for word in (_sanitize_word(item) for item in source) if word]
    words = [
        word
        for word in words
        if word["start"] >= allowed_start - 1e-6
        and word["end"] <= allowed_end + 1e-6
    ]
    words.sort(key=lambda word: (word["start"], word["end"]))
    return words


def _is_source_start(word: dict[str, Any], allowed_start: float) -> bool:
    return allowed_start <= 0.05 and word["start"] <= allowed_start + 0.05


def _is_sentence_start(
    words: Sequence[dict[str, Any]], index: int, allowed_start: float
) -> bool:
    if index <= 0:
        return _is_source_start(words[0], allowed_start)
    return boundary_strength(words[index - 1].get("word")) == "strong"


def _fallback_refinement(
    candidate: Any,
    words: Sequence[dict[str, Any]],
    allowed_start: float,
    allowed_end: float,
    min_s: float,
    max_s: float,
    language: Any,
    source: str,
) -> dict[str, Any]:
    original_start = finite_time(_get(candidate, "start"))
    original_end = finite_time(_get(candidate, "end"))
    if original_start is None:
        original_start = allowed_start
    if original_end is None:
        original_end = allowed_end
    start = max(allowed_start, min(original_start, allowed_end))
    end = min(allowed_end, max(original_end, start))
    fallback_words = [
        word for word in words if word["end"] > start and word["start"] < end
    ]
    duration = max(0.0, end - start)
    within = end > start and min_s <= duration <= max_s
    return {
        "start": start,
        "end": end,
        "duration": round(duration, 6),
        "words": fallback_words,
        "status": "legacy" if not fallback_words else "unknown",
        "complete": False,
        "weak": False,
        "source": source,
        "start_reason": "original",
        "end_reason": "original",
        "start_complete": False,
        "end_complete": False,
        "within_limits": within,
        "word_count": len(fallback_words),
        "original_start": original_start,
        "original_end": original_end,
        "language": language,
    }


def refine_candidate(
    candidate: Any,
    allowed_start: float,
    allowed_end: float,
    min_s: float,
    max_s: float,
    language: Any = None,
    *,
    word_context: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Refine one candidate to safe word boundaries within strict bounds.

    ``candidate`` may be any object with ``start``, ``end`` and ``words``.
    ``word_context`` can include words from neighbouring segments so a sentence
    can be completed without scanning the whole transcript again.  Only words
    fully inside ``[allowed_start, allowed_end]`` are considered.

    The result is a dictionary with ``start``, ``end``, boundary metadata and
    the valid words intersecting the refined span.  No text is rewritten and no
    timing is invented.  When word data cannot produce a result inside the
    duration limits, the original segment window is returned with
    ``within_limits=False`` rather than fabricating a new one.
    """
    allowed_start = float(allowed_start)
    allowed_end = float(allowed_end)
    min_s = max(0.0, float(min_s))
    max_s = max(0.0, float(max_s))
    if allowed_end <= allowed_start:
        return _fallback_refinement(
            candidate, [], allowed_start, allowed_end, min_s, max_s, language,
            "segment",
        )

    words = _candidate_boundary_words(
        candidate, word_context, allowed_start, allowed_end
    )
    candidate_start = finite_time(_get(candidate, "start"))
    candidate_end = finite_time(_get(candidate, "end"))
    if candidate_start is None or candidate_end is None or candidate_end <= candidate_start:
        return _fallback_refinement(
            candidate, words, allowed_start, allowed_end, min_s, max_s, language,
            "segment",
        )

    anchor_indices = [
        index
        for index, word in enumerate(words)
        if word["end"] > candidate_start and word["start"] < candidate_end
    ]
    if not anchor_indices:
        return _fallback_refinement(
            candidate, words, allowed_start, allowed_end, min_s, max_s, language,
            "segment" if not words else "words",
        )

    first_anchor = anchor_indices[0]
    last_anchor = anchor_indices[-1]
    start_index = first_anchor
    start_reason = (
        "sentence_start"
        if _is_sentence_start(words, first_anchor, allowed_start)
        else ("source_start" if _is_source_start(words[first_anchor], allowed_start) else "word_start")
    )

    # Prefer a sentence start immediately before the candidate if the expanded
    # window still fits the maximum duration.  Otherwise, trim forward to the
    # next sentence start only when context proves the candidate starts in the
    # middle of a sentence.  With no preceding word, keep the first word rather
    # than dropping a potentially complete opening sentence.
    if start_reason == "word_start" and first_anchor > 0:
        for index in range(first_anchor - 1, -1, -1):
            if not _is_sentence_start(words, index, allowed_start):
                continue
            if words[last_anchor]["end"] - words[index]["start"] <= max_s:
                start_index = index
                start_reason = "sentence_start"
                break
        if start_index == first_anchor:
            for index in range(first_anchor + 1, last_anchor + 1):
                if not _is_sentence_start(words, index, allowed_start):
                    continue
                if words[last_anchor]["end"] - words[index]["start"] >= min_s:
                    start_index = index
                    start_reason = "sentence_start"
                    break

    start = words[start_index]["start"]
    if start < allowed_start or start >= allowed_end:
        return _fallback_refinement(
            candidate, words, allowed_start, allowed_end, min_s, max_s, language,
            "words",
        )

    end_index: int | None = None
    end_reason = "word_end"
    # A strong sentence end at or after the original tail is preferred when
    # the extra words still fit both the allowed range and maximum duration.
    for index in range(last_anchor, len(words)):
        word = words[index]
        if word["start"] >= allowed_end - 1e-9 or word["end"] > allowed_end + 1e-9:
            break
        span = word["end"] - start
        if span > max_s + 1e-6:
            break
        if span < min_s:
            continue
        if boundary_strength(word.get("word"), language) == "strong":
            end_index = index
            end_reason = "sentence_end"
            break

    if end_index is None:
        # If the candidate tail itself is unfinished, the latest complete
        # sentence inside the window is a safer end than a partial phrase.
        for index in range(last_anchor, start_index - 1, -1):
            word = words[index]
            span = word["end"] - start
            if span < min_s or span > max_s + 1e-6:
                continue
            strength = boundary_strength(word.get("word"), language)
            if strength == "strong":
                end_index = index
                end_reason = "sentence_end"
                break
            if strength == "weak" and end_index is None:
                end_index = index
                end_reason = "weak_end"

    if end_index is None:
        end_index = last_anchor
        end_reason = "word_end"

    # A start moved forward can leave a span below the minimum.  Extend to the
    # next valid word boundary when possible; otherwise fall back rather than
    # exceeding the configured maximum.
    if words[end_index]["end"] - start < min_s:
        for index in range(end_index + 1, len(words)):
            word = words[index]
            span = word["end"] - start
            if span > max_s + 1e-6:
                break
            if word["end"] > allowed_end + 1e-9:
                break
            if span >= min_s:
                end_index = index
                end_reason = "word_end"
                break

    end = words[end_index]["end"]
    if end > allowed_end + 1e-9:
        end = allowed_end
    duration = end - start
    if duration <= 0 or duration < min_s - 1e-6 or duration > max_s + 1e-6:
        return _fallback_refinement(
            candidate, words, allowed_start, allowed_end, min_s, max_s, language,
            "words",
        )

    refined_words = [
        word
        for word in words
        if word["start"] >= start - 1e-6 and word["end"] <= end + 1e-6
    ]
    if not refined_words:
        return _fallback_refinement(
            candidate, words, allowed_start, allowed_end, min_s, max_s, language,
            "words",
        )

    end_strength = boundary_strength(
        refined_words[-1].get("word"), language
    )
    start_complete = start_reason in {"sentence_start", "source_start"}
    end_complete = end_reason == "sentence_end"
    has_punctuation = any(
        boundary_strength(word.get("word"), language) != "none"
        for word in refined_words
    )
    if not has_punctuation and not end_complete and end_strength != "weak":
        # No punctuation evidence anywhere: do not turn a word-aligned span
        # into a claimed complete sentence.
        status = "unknown"
    elif start_complete and end_complete:
        status = "complete"
    elif end_strength == "weak" and end_reason != "sentence_end":
        status = "weak"
    elif has_punctuation or start_complete or end_complete:
        status = "partial"
    else:
        status = "unknown"

    return {
        "start": start,
        "end": end,
        "duration": round(duration, 6),
        "words": refined_words,
        "status": status,
        "complete": status == "complete",
        "weak": end_strength == "weak",
        "source": "words",
        "start_reason": start_reason,
        "end_reason": end_reason,
        "start_complete": start_complete,
        "end_complete": end_complete,
        "within_limits": True,
        "word_count": len(refined_words),
        "original_start": candidate_start,
        "original_end": candidate_end,
        "language": language,
    }


def _normalised_text(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def normalized_tokens(text: Any) -> list[str]:
    """Return comparison tokens after NFKC normalisation and case folding."""
    return _TOKEN_RE.findall(_normalised_text(text))


def fingerprint(text: Any) -> str:
    """Return a stable comparison fingerprint; empty text has an empty result."""
    return " ".join(normalized_tokens(text))


# Duplicate comparison is deliberately conservative.  A few common words or a
# single shared quotation must never be enough to remove a candidate.
DUPLICATE_MIN_TOKENS = 10
DUPLICATE_MIN_CONTAINMENT = 0.82
DUPLICATE_MIN_SEQUENCE = 0.78
DUPLICATE_MIN_TOKEN_OVERLAP = 0.70
DUPLICATE_MIN_SHARED_NGRAMS = 3
DUPLICATE_MIN_NGRAM_RATIO = 0.50
DUPLICATE_MIN_BLOCK = 6


def _rounded(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)



def text_duplicate_evidence(
    left: Any,
    right: Any,
    *,
    language: Any = None,
    min_tokens: int = DUPLICATE_MIN_TOKENS,
) -> dict[str, Any]:
    """Compare two transcripts and explain whether they substantially overlap.

    Normalization is comparison-only: NFKC, case folding, punctuation removal
    and whitespace collapse happen in :func:`normalized_tokens`.  The source
    text is never modified.

    Empty/missing and very short transcripts are never duplicates.  A pair is
    duplicate only when most of the shorter transcript is covered by matching
    sequence blocks, the overall sequence is similar, and distinctive shared
    4-grams support the match.  Shared topics, names, short quotations and
    isolated refrains therefore do not qualify on their own.
    """
    left_tokens = normalized_tokens(left)
    right_tokens = normalized_tokens(right)
    shorter = min(len(left_tokens), len(right_tokens))
    result: dict[str, Any] = {
        "duplicate": False,
        "compared": False,
        "reason": "missing_transcript",
        "left_tokens": len(left_tokens),
        "right_tokens": len(right_tokens),
        "min_tokens": int(min_tokens),
        "token_overlap": 0.0,
        "token_jaccard": 0.0,
        "containment": 0.0,
        "sequence_similarity": 0.0,
        "shared_4grams": 0,
        "shared_ngram_ratio": 0.0,
        "longest_shared_block": 0,
        "matched_tokens": 0,
        "language": language,
    }

    if not left_tokens or not right_tokens:
        return result
    if shorter < max(1, int(min_tokens)):
        result["reason"] = "too_short"
        return result

    result["compared"] = True
    left_counter = Counter(left_tokens)
    right_counter = Counter(right_tokens)
    shared_token_count = sum((left_counter & right_counter).values())
    left_set = set(left_tokens)
    right_set = set(right_tokens)
    union = left_set | right_set

    matcher = SequenceMatcher(None, left_tokens, right_tokens, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size]
    matched = sum(block.size for block in blocks)
    longest = max((block.size for block in blocks), default=0)
    containment = matched / shorter

    left_ngrams = {
        tuple(left_tokens[index : index + 4])
        for index in range(max(0, len(left_tokens) - 3))
    }
    right_ngrams = {
        tuple(right_tokens[index : index + 4])
        for index in range(max(0, len(right_tokens) - 3))
    }
    shared_ngrams = left_ngrams & right_ngrams
    ngram_denominator = min(len(left_ngrams), len(right_ngrams))

    result.update(
        {
            "token_overlap": _rounded(shared_token_count / max(1, len(left_tokens), len(right_tokens))),
            "token_jaccard": _rounded(len(left_set & right_set) / max(1, len(union))),
            "containment": _rounded(containment),
            "sequence_similarity": _rounded(matcher.ratio()),
            "shared_4grams": len(shared_ngrams),
            "shared_ngram_ratio": _rounded(
                len(shared_ngrams) / max(1, ngram_denominator)
            ),
            "longest_shared_block": longest,
            "matched_tokens": matched,
        }
    )

    if left_tokens == right_tokens:
        result["duplicate"] = True
        result["reason"] = "exact_normalized_text"
        return result

    if (
        containment >= DUPLICATE_MIN_CONTAINMENT
        and result["sequence_similarity"] >= DUPLICATE_MIN_SEQUENCE
        and result["token_overlap"] >= DUPLICATE_MIN_TOKEN_OVERLAP
        and len(shared_ngrams) >= DUPLICATE_MIN_SHARED_NGRAMS
        and result["shared_ngram_ratio"] >= DUPLICATE_MIN_NGRAM_RATIO
        and longest >= DUPLICATE_MIN_BLOCK
    ):
        result["duplicate"] = True
        result["reason"] = "substantial_overlap"
    else:
        result["reason"] = "insufficient_overlap"
    return result
