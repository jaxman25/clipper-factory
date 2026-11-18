"""Mode-specific clip selection shared by the generator and the tests.

Each generation mode has its own strategy, and none of them may fabricate a
scored viral moment:

* ``viral``     - score transcript windows, rank them, keep distinct clips.
                  An evenly spaced visual window is only used when there is no
                  transcript at all, and it is returned as ``fallback=True`` so
                  the queue never carries an invented viral score.
* ``equal``     - split the full source duration into ``count`` search
                  intervals and pick the best complete speech segment inside
                  each one. Intervals are search regions, not clip lengths.
* ``transform`` - pick ``count`` long source windows (one per transformed
                  piece), each long enough to narrate every platform target.

The module is side-effect free: it takes transcript segments plus the source
duration and returns ``Selected`` records with diagnostics, so the selection
logic can be unit-tested without ffmpeg, whisper or the network.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Sequence

try:
    from backend import quality, transcript_boundaries, viral
except ImportError:  # pragma: no cover - direct execution
    import quality  # type: ignore
    import transcript_boundaries  # type: ignore
    import viral  # type: ignore

DEFAULT_MIN_SECONDS = 30.0
DEFAULT_MAX_SECONDS = 45.0
# A window must be at least this wide for find_candidates to build one: it
# grows a window from < min to > max, so max == min can never produce a hit.
MIN_WINDOW_SPAN = 5.0
# Transform pieces must be long enough to narrate the 59 s Shorts target at
# 1.1-1.2x footage speed without falling back to extreme slow motion.
TRANSFORM_WINDOW_MIN = 60.0
TRANSFORM_WINDOW_MAX = 110.0
TRANSFORM_TARGETS = (21, 30, 59)


@dataclass
class Selected:
    """One chosen source window plus why it was chosen."""

    candidate: viral.Candidate
    fallback: bool = False
    reason: str = ""

    @property
    def start(self) -> float:
        return float(self.candidate.start)

    @property
    def end(self) -> float:
        return float(self.candidate.end)

    @property
    def quality_status(self) -> str:
        return quality.status_of(self.candidate)


def duration_bounds(cfg: dict[str, Any]) -> tuple[float, float]:
    """Return ``(min, max)`` clip seconds, never an inverted or zero window.

    ``config.json`` ships 30/45. A stale per-job override (the dashboard used
    to force ``--clip-max-seconds 25``) or a hand-edited config must not make
    ``viral.find_candidates`` return zero candidates, which is exactly what a
    max below min did. When the window is inverted or empty it is widened by
    ``MIN_WINDOW_SPAN`` so the minimum stays authoritative.
    """
    try:
        min_s = float(cfg.get("clip_min_seconds", DEFAULT_MIN_SECONDS) or DEFAULT_MIN_SECONDS)
    except (TypeError, ValueError):
        min_s = DEFAULT_MIN_SECONDS
    try:
        max_s = float(cfg.get("clip_max_seconds", DEFAULT_MAX_SECONDS) or DEFAULT_MAX_SECONDS)
    except (TypeError, ValueError):
        max_s = DEFAULT_MAX_SECONDS
    if min_s <= 0:
        min_s = DEFAULT_MIN_SECONDS
    if max_s <= 0:
        max_s = min_s + 15.0
    if max_s < min_s or max_s - min_s < 0.5:
        max_s = min_s + MIN_WINDOW_SPAN
    return min_s, max_s


def apply_user_config(cfg: dict[str, Any], data: Any) -> dict[str, Any]:
    """Apply saved browser preferences to a run's config.

    Called before the explicit per-job CLI flags, so an explicit request value
    always wins over a stored preference. Only known keys are copied; unknown
    keys are ignored so a stale localStorage payload cannot inject settings.
    """
    if not isinstance(data, dict):
        return cfg
    for key in (
        "shorts_per_video",
        "clip_min_seconds",
        "clip_max_seconds",
        "playback_speed",
        "drum_volume_db",
        "caption_words_per_card",
        "hook_seconds",
        "outro_seconds",
    ):
        if data.get(key) is None:
            continue
        try:
            cfg[key] = float(data[key])
        except (TypeError, ValueError):
            continue
    for key in (
        "timezone",
        "outro_text",
        "hashtags",
        "caption_color",
        "original_channel",
    ):
        if isinstance(data.get(key), str):
            cfg[key] = data[key].strip()
    times = data.get("posting_times")
    if isinstance(times, list):
        cleaned = [str(value).strip() for value in times if str(value).strip()]
        if cleaned:
            cfg["posting_times"] = cleaned
    platforms = cfg.setdefault("platforms", {})
    for key in ("instagram", "tiktok"):
        if isinstance(data.get(key), bool):
            platforms[key] = data[key]
    if isinstance(data.get("youtube_auto_post"), bool):
        cfg["youtube_auto_post"] = data["youtube_auto_post"]
    return cfg


def _overlap(a: viral.Candidate, b: viral.Candidate, gap: float = 0.4) -> bool:
    return a.start < b.end + gap and b.start - gap < a.end


def _sorted(selected: list[Selected]) -> list[Selected]:
    selected.sort(key=lambda item: item.candidate.start)
    return selected


def _quality_counts(candidates: Sequence[viral.Candidate]) -> dict[str, int]:
    counts = {"good": 0, "review": 0, "poor": 0}
    for candidate in candidates:
        counts[quality.status_of(candidate)] += 1
    return counts


def _boundary_metadata(result: dict[str, Any], applied: bool) -> dict[str, Any]:
    """Structured boundary evidence without the potentially large word list."""
    metadata = {key: value for key, value in result.items() if key != "words"}
    metadata["applied"] = applied
    return metadata


_REFINEMENT_TOLERANCE = 1e-6
TEXT_ALIGNMENT_FALLBACK = "text_alignment_unverified"


def _word_text(word: Any) -> str:
    if isinstance(word, dict):
        value = word.get("word")
        if value is None:
            value = word.get("text")
    else:
        value = getattr(word, "text", None)
        if value is None:
            value = getattr(word, "word", None)
    return str(value or "").strip()


def _word_bounds(word: Any) -> tuple[float | None, float | None]:
    if isinstance(word, dict):
        start, end = word.get("start"), word.get("end")
    else:
        start, end = getattr(word, "start", None), getattr(word, "end", None)
    return transcript_boundaries.finite_time(start), transcript_boundaries.finite_time(
        end
    )


def _joined_word_text(words: Sequence[Any], language: str | None) -> str:
    return transcript_boundaries.join_segment_text(
        [_word_text(word) for word in words], language
    )


def _joined_word_tokens(words: Sequence[Any], language: str | None) -> list[str]:
    return transcript_boundaries.normalized_tokens(
        _joined_word_text(words, language)
    )


def _punctuation_signature(text: Any) -> str:
    """Return the ordered punctuation characters after NFKC normalization."""
    normalised = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(
        char for char in normalised if unicodedata.category(char).startswith("P")
    )


def _contains_contiguous_sequence(
    sequence: Sequence[str], part: Sequence[str]
) -> bool:
    if not part or len(part) > len(sequence):
        return False
    for index in range(len(sequence) - len(part) + 1):
        if sequence[index : index + len(part)] == list(part):
            return True
    return False


def _final_text_from_refinement(
    candidate: viral.Candidate,
    result: dict[str, Any],
    language: str | None,
) -> str | None:
    """Return final text only when refinement has reliable word coverage.

    Coverage requires the full original candidate text to be represented by
    valid candidate words, every refined word to have a finite positive range
    inside the final bounds, and the first/last refined words to align with
    those bounds.  Candidate words retained inside the final window must also
    appear continuously in the refined sequence.  Anything less conservative
    is left on the original text rather than exposing a partial transcript.
    """
    if result.get("source") != "words":
        return None
    refined_words = list(result.get("words") or [])
    if not refined_words:
        return None

    start = transcript_boundaries.finite_time(result.get("start"))
    end = transcript_boundaries.finite_time(result.get("end"))
    if start is None or end is None or end <= start:
        return None

    refined_bounds = []
    for word in refined_words:
        text = _word_text(word)
        word_start, word_end = _word_bounds(word)
        if (
            not text
            or word_start is None
            or word_end is None
            or word_end <= word_start
            or word_start < start - _REFINEMENT_TOLERANCE
            or word_end > end + _REFINEMENT_TOLERANCE
        ):
            return None
        refined_bounds.append((word_start, word_end))

    if (
        abs(refined_bounds[0][0] - start) > _REFINEMENT_TOLERANCE
        or abs(refined_bounds[-1][1] - end) > _REFINEMENT_TOLERANCE
    ):
        return None

    candidate_words = list(candidate.words or [])
    if not candidate_words:
        return None

    inside_words = []
    for word in candidate_words:
        text = _word_text(word)
        word_start, word_end = _word_bounds(word)
        if (
            not text
            or word_start is None
            or word_end is None
            or word_end <= word_start
        ):
            return None
        if (
            word_start >= start - _REFINEMENT_TOLERANCE
            and word_end <= end + _REFINEMENT_TOLERANCE
        ):
            inside_words.append(word)

    original_tokens = transcript_boundaries.normalized_tokens(candidate.text)
    if not original_tokens:
        return None
    joined_candidate_text = _joined_word_text(candidate_words, language)
    if original_tokens != transcript_boundaries.normalized_tokens(
        joined_candidate_text
    ):
        return None
    if _punctuation_signature(candidate.text) != _punctuation_signature(
        joined_candidate_text
    ):
        return None
    if not inside_words:
        return None

    inside_tokens = _joined_word_tokens(inside_words, language)
    refined_tokens = _joined_word_tokens(refined_words, language)
    if not _contains_contiguous_sequence(refined_tokens, inside_tokens):
        return None
    return _joined_word_text(refined_words, language)


def _apply_refinement(
    candidate: viral.Candidate,
    result: dict[str, Any],
    *,
    language: str | None = None,
) -> bool:
    """Apply boundaries, words and text together, or preserve the original."""
    if not bool(result.get("within_limits")):
        candidate.boundary = _boundary_metadata(result, False)
        return False

    final_text = _final_text_from_refinement(candidate, result, language)
    refined_words = result.get("words") or []
    new_words = [
        viral.Word(
            float(word["start"]),
            float(word["end"]),
            str(word.get("word") or "").strip(),
            word.get("probability"),
        )
        for word in refined_words
        if str(word.get("word") or "").strip()
    ]
    if final_text is None or not new_words:
        metadata = _boundary_metadata(result, False)
        metadata["text_alignment"] = "unverified"
        metadata["fallback"] = TEXT_ALIGNMENT_FALLBACK
        candidate.boundary = metadata
        return False

    candidate.start = float(result["start"])
    candidate.end = float(result["end"])
    candidate.words = new_words
    candidate.text = final_text
    candidate.boundary = _boundary_metadata(result, True)
    return True


def _refine_candidates(
    candidates: Sequence[viral.Candidate],
    *,
    segments: Sequence[viral.Segment],
    allowed_start: float,
    allowed_end: float,
    min_seconds: float,
    max_seconds: float,
    language: str | None,
) -> None:
    context = viral._words_between(segments)
    for candidate in candidates:
        result = transcript_boundaries.refine_candidate(
            candidate,
            allowed_start,
            allowed_end,
            min_seconds,
            max_seconds,
            language=language,
            word_context=context,
        )
        _apply_refinement(candidate, result, language=language)


def _duplicate_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    """Compact, text-free duplicate evidence suitable for diagnostics."""
    return {
        "reason": evidence.get("reason"),
        "left_tokens": evidence.get("left_tokens"),
        "right_tokens": evidence.get("right_tokens"),
        "containment": evidence.get("containment"),
        "sequence_similarity": evidence.get("sequence_similarity"),
        "token_overlap": evidence.get("token_overlap"),
        "shared_4grams": evidence.get("shared_4grams"),
        "longest_shared_block": evidence.get("longest_shared_block"),
    }


def _duplicate_record(
    candidate: viral.Candidate,
    accepted: viral.Candidate,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "start": round(float(candidate.start), 3),
        "end": round(float(candidate.end), 3),
        "duplicate_of": {
            "start": round(float(accepted.start), 3),
            "end": round(float(accepted.end), 3),
        },
        **_duplicate_summary(evidence),
    }


def _find_duplicate(
    candidate: viral.Candidate,
    accepted_items: Sequence[Any],
    *,
    language: str | None,
) -> tuple[Any | None, dict[str, Any] | None, bool, str | None, int]:
    """Compare one candidate with earlier accepted candidates.

    Returns ``(accepted_item, evidence, compared_any, not_compared_reason,
    pair_count)``.  A missing or very short transcript is never rejected.
    """
    compared_any = False
    not_compared: str | None = None
    pairs = 0
    for accepted_item in accepted_items:
        accepted = (
            accepted_item[0] if isinstance(accepted_item, tuple) else accepted_item
        )
        evidence = transcript_boundaries.text_duplicate_evidence(
            candidate.text,
            accepted.text,
            language=language,
        )
        pairs += 1
        if not evidence.get("compared"):
            if not_compared is None:
                not_compared = str(evidence.get("reason") or "missing_transcript")
            continue
        compared_any = True
        if evidence.get("duplicate"):
            return accepted_item, evidence, True, None, pairs
    return None, None, compared_any, not_compared, pairs


def _select_distinct(
    candidates: Sequence[viral.Candidate],
    count: int,
    min_seconds: float,
    max_seconds: float,
    *,
    language: str | None,
) -> tuple[
    list[viral.Candidate],
    list[dict[str, Any]],
    int,
    dict[str, int],
]:
    """Greedy rank-order selection with overlap and duplicate protection.

    Candidates arrive best-ranked first.  An overlapping or strongly
    duplicated candidate is skipped, so the stronger accepted candidate is
    always the one retained.  The returned order is chronological.
    """
    chosen: list[viral.Candidate] = []
    rejections: list[dict[str, Any]] = []
    not_compared = {"missing_transcript": 0, "too_short": 0}
    compared_candidates = 0
    for candidate in candidates:
        if len(chosen) >= count:
            break
        if (
            candidate.duration < min_seconds - 0.5
            or candidate.duration > max_seconds + 0.5
        ):
            continue
        if any(_overlap(candidate, accepted) for accepted in chosen):
            continue
        duplicate, evidence, compared_any, missing_reason, _ = _find_duplicate(
            candidate, chosen, language=language
        )
        if compared_any:
            compared_candidates += 1
        elif missing_reason:
            not_compared[missing_reason] = not_compared.get(missing_reason, 0) + 1
        if duplicate is not None and evidence is not None:
            rejections.append(_duplicate_record(candidate, duplicate, evidence))
            continue
        chosen.append(candidate)
    chosen.sort(key=lambda item: item.start)
    return chosen, rejections, compared_candidates, not_compared


def select_viral(
    segments: Sequence[viral.Segment],
    rms: Sequence[float],
    keywords: Sequence[str] | None,
    count: int,
    min_seconds: float,
    max_seconds: float,
    duration: float,
    language: str | None = None,
) -> tuple[list[Selected], dict[str, Any]]:
    """Rank transcript windows and keep the strongest distinct moments.

    Fewer valid moments are reported as a shortfall, never padded with
    duplicate or forged candidates. Only a genuinely transcript-less source
    gets evenly spaced visual windows, and those are flagged ``fallback``.
    """
    count = max(1, int(count))
    candidates = viral.find_candidates(segments, rms, keywords, min_seconds, max_seconds)
    counts = _quality_counts(candidates)
    # Clearly poor transcript windows are never presented as viral moments.
    # Good candidates outrank review candidates; review stays selectable, so a
    # legacy transcript with no metrics keeps its previous score-based order.
    acceptable = [candidate for candidate in candidates if not quality.is_poor(candidate)]
    _refine_candidates(
        acceptable,
        segments=segments,
        allowed_start=0.0,
        allowed_end=max(0.0, float(duration)),
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        language=language,
    )
    acceptable.sort(key=lambda item: (quality.rank(item), -item.score))
    # Overlap and text-level duplicates are checked on the refined boundaries
    # and in rank order, so the stronger moment always survives.  Chronology is
    # restored only after selection.
    chosen, duplicate_rejections, duplicate_compared, duplicate_not_compared = (
        _select_distinct(
            acceptable,
            count,
            min_seconds,
            max_seconds,
            language=language,
        )
    )
    selected = [Selected(candidate) for candidate in chosen]
    fallback = 0
    if not segments:
        for candidate in viral.fallback_windows(
            duration, count, min_seconds, max_seconds
        ):
            if len(selected) >= count:
                break
            if any(_overlap(candidate, item.candidate) for item in selected):
                continue
            candidate.quality = quality.unavailable(
                "no transcript available; visual fallback is not a transcript-quality judgment"
            )
            selected.append(
                Selected(candidate, True, "no transcript available for this source")
            )
            fallback += 1
    _sorted(selected)
    diagnostics = {
        "requested": count,
        "candidates": len(candidates),
        "selected": len(selected),
        "fallback": fallback,
        "shortfall": max(0, count - len(selected)),
        "quality": counts,
        "quality_rejected": counts.get("poor", 0),
        "duplicate_compared": duplicate_compared,
        "duplicates_excluded": len(duplicate_rejections),
        "duplicate_rejections": duplicate_rejections,
        "duplicate_not_compared": duplicate_not_compared,
    }
    return selected, diagnostics


def select_equal(
    segments: Sequence[viral.Segment],
    duration: float,
    count: int,
    min_seconds: float,
    max_seconds: float,
    keywords: Sequence[str] | None = None,
    language: str | None = None,
) -> tuple[list[Selected], dict[str, Any]]:
    """Pick one complete speech segment from each of ``count`` intervals.

    ``width = duration / count`` defines the search regions. A clip never
    crosses an interval boundary, so clips cannot overlap or duplicate, and
    the output stays chronological. An interval with no segment inside the
    configured duration limits is reported instead of being filled from
    another interval.
    """
    count = max(1, int(count))
    report: list[dict[str, Any]] = []
    selected: list[Selected] = []
    accepted_intervals: list[tuple[viral.Candidate, int]] = []
    duplicate_rejections: list[dict[str, Any]] = []
    duplicate_compared = 0
    duplicate_not_compared = {"missing_transcript": 0, "too_short": 0}
    if duration <= 0:
        return [], {"requested": count, "selected": 0, "empty": count, "intervals": report}

    width = duration / count
    for index in range(count):
        low = index * width
        high = min(duration, (index + 1) * width)
        best: tuple[int, float, list[viral.Segment], list[str], dict[str, Any]] | None = None
        poor_seen = 0
        crossing_seen = 0

        def usable(segment: viral.Segment) -> bool:
            """A crossing segment is safe only when all its words are inside."""
            if segment.start >= low - 1e-6 and segment.end <= high + 1e-6:
                return True
            words = [
                word
                for word in segment.words
                if low - 1e-6 <= word.start and word.end <= high + 1e-6
            ]
            return bool(words) and len(words) == len(segment.words)

        def effective_start(segment: viral.Segment) -> float:
            if segment.start >= low - 1e-6:
                return segment.start
            starts = [
                word.start
                for word in segment.words
                if low - 1e-6 <= word.start and word.end <= high + 1e-6
            ]
            return min(starts) if starts else segment.start

        def effective_end(segment: viral.Segment) -> float:
            if segment.end <= high + 1e-6:
                return segment.end
            ends = [
                word.end
                for word in segment.words
                if low - 1e-6 <= word.start and word.end <= high + 1e-6
            ]
            return max(ends) if ends else segment.end

        for first, segment in enumerate(segments):
            if not usable(segment):
                if segment.start < high and segment.end > low:
                    crossing_seen += 1
                continue
            window: list[viral.Segment] = []
            for next_index in range(first, len(segments)):
                following = segments[next_index]
                if not usable(following):
                    if following.start < high and following.end > low:
                        crossing_seen += 1
                    break
                window.append(following)
                span = effective_end(window[-1]) - effective_start(window[0])
                if span < min_seconds:
                    continue
                if span > max_seconds:
                    break
                score, reasons = viral._score_text(
                    viral._join(window), keywords or viral.DEFAULT_KEYWORDS, 0.0
                )
                if viral.SENTENCE_END.search(window[-1].text.strip()):
                    score += 4.0
                    reasons.append("ends on a complete beat")
                if first > 0 and viral.SENTENCE_END.search(segments[first - 1].text.strip()):
                    score += 3.0
                    reasons.append("starts a complete thought")
                score += 4.0 * (
                    1 - abs(span - (min_seconds + max_seconds) / 2) / 20.0
                )
                assessment = quality.assess_segments(window, text=viral._join(window))
                if assessment["status"] == "poor":
                    poor_seen += 1
                    continue
                rank = 0 if assessment["status"] == "good" else 1
                key = (rank, -score)
                if best is None or key < (best[0], -best[1]):
                    # Copy the window: it keeps growing on the next iteration,
                    # and storing the live list would turn the chosen 30 s
                    # segment into whatever length the loop ended on.
                    best = (rank, score, list(window), reasons, assessment)
        if best is None:
            if poor_seen:
                reason = "only poor-quality speech candidates in this interval"
            elif crossing_seen:
                reason = (
                    "speech crossed this interval boundary and was excluded "
                    "without a safe word-level trim"
                )
            else:
                reason = "no complete speech segment within the duration limits"
            report.append(
                {
                    "index": index + 1,
                    "start": round(low, 3),
                    "end": round(high, 3),
                    "selected": False,
                    "reason": reason,
                    "quality": {
                        "status": "poor" if poor_seen else "unavailable",
                        "rejected_poor": poor_seen,
                    },
                    "quality_rejected_poor": poor_seen,
                    "boundary_rejected": crossing_seen,
                }
            )
            continue
        rank, score, window, reasons, assessment = best
        candidate = viral.Candidate(
            start=effective_start(window[0]),
            end=effective_end(window[-1]),
            text=viral._join(window),
            words=viral._words_between(window),
            score=max(0.0, min(100.0, score * 2.1)),
            reasons=[f"equal interval {index + 1}/{count}"] + reasons,
            quality=assessment,
        )
        _refine_candidates(
            [candidate],
            segments=segments,
            allowed_start=low,
            allowed_end=high,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
            language=language,
        )
        if not (
            candidate.end > candidate.start
            and candidate.start >= low - 1e-6
            and candidate.end <= high + 1e-6
        ):
            report.append(
                {
                    "index": index + 1,
                    "start": round(low, 3),
                    "end": round(high, 3),
                    "selected": False,
                    "reason": "refined speech could not fit safely inside this interval",
                    "quality": quality.compact(assessment),
                    "quality_rejected_poor": poor_seen,
                    "boundary_rejected": crossing_seen + 1,
                }
            )
            continue
        duplicate, evidence, compared_any, missing_reason, _ = _find_duplicate(
            candidate, accepted_intervals, language=language
        )
        if compared_any:
            duplicate_compared += 1
        elif missing_reason:
            duplicate_not_compared[missing_reason] = (
                duplicate_not_compared.get(missing_reason, 0) + 1
            )
        if duplicate is not None and evidence is not None:
            duplicate_candidate, duplicate_interval = duplicate
            duplicate_rejections.append(
                _duplicate_record(candidate, duplicate_candidate, evidence)
            )
            report.append(
                {
                    "index": index + 1,
                    "start": round(low, 3),
                    "end": round(high, 3),
                    "selected": False,
                    "reason": (
                        "duplicate transcript content already selected in "
                        f"interval {duplicate_interval + 1}"
                    ),
                    "quality": quality.compact(assessment),
                    "quality_rejected_poor": poor_seen,
                    "boundary_rejected": crossing_seen,
                    "duplicate_of_interval": duplicate_interval + 1,
                    "duplicate": _duplicate_summary(evidence),
                }
            )
            continue
        selected.append(Selected(candidate))
        accepted_intervals.append((candidate, index))
        report.append(
            {
                "index": index + 1,
                "start": round(low, 3),
                "end": round(high, 3),
                "selected": True,
                "reason": (
                    f"clip {candidate.start:.1f}-{candidate.end:.1f}s "
                    f"(score {candidate.score:.0f})"
                ),
                "quality": quality.compact(assessment),
                "quality_rejected_poor": poor_seen,
                "boundary_rejected": crossing_seen,
                "boundary": (
                    {key: value for key, value in candidate.boundary.items() if key != 'words'}
                    if candidate.boundary
                    else None
                ),
            }
        )

    if not segments:
        # Whisper found no speech at all. Keep the old visual-slice behaviour
        # but label it honestly instead of pretending it was speech-driven.
        selected = []
        report = []
        for index in range(count):
            low = index * width
            high = min(duration, (index + 1) * width)
            if high - low < 3.0:
                report.append(
                    {
                        "index": index + 1,
                        "start": round(low, 3),
                        "end": round(high, 3),
                        "selected": False,
                        "reason": "interval too short to render",
                    }
                )
                continue
            span = min(high - low, max(3.0, min_seconds))
            candidate = viral.Candidate(
                start=round(low, 3),
                end=round(min(high, low + span), 3),
                text="",
                words=[],
                score=0.0,
                reasons=["fallback: visual window (no transcript)"],
                quality=quality.unavailable(
                    "no transcript available; visual fallback is not a transcript-quality judgment"
                ),
            )
            selected.append(
                Selected(candidate, True, "no transcript available for this source")
            )
            report.append(
                {
                    "index": index + 1,
                    "start": round(low, 3),
                    "end": round(high, 3),
                    "selected": True,
                    "reason": "fallback: visual window (no transcript)",
                    "quality": quality.compact(candidate.quality),
                }
            )

    empty = [row for row in report if not row["selected"]]
    counts = {"good": 0, "review": 0, "poor": 0}
    for item in selected:
        counts[item.quality_status] += 1
    diagnostics = {
        "requested": count,
        "selected": len(selected),
        "empty": len(empty),
        "fallback": sum(1 for item in selected if item.fallback),
        "quality": counts,
        "quality_rejected": sum(
            int(row.get("quality_rejected_poor") or 0) for row in report
        ),
        "boundary_excluded": sum(
            int(row.get("boundary_rejected") or 0) for row in report
        ),
        "duplicate_compared": duplicate_compared,
        "duplicates_excluded": len(duplicate_rejections),
        "duplicate_rejections": duplicate_rejections,
        "duplicate_not_compared": duplicate_not_compared,
        "intervals": report,
    }
    return _sorted(selected), diagnostics


def select_transform(
    segments: Sequence[viral.Segment],
    rms: Sequence[float],
    keywords: Sequence[str] | None,
    duration: float,
    count: int,
    language: str | None = None,
) -> tuple[list[Selected], dict[str, Any]]:
    """Pick ``count`` distinct long source windows, one per transformed piece.

    Deliberately different from Viral Moments: the window is 60-110 s so the
    longest platform narration fits, and the selection is best-first with
    overlap rejection, so two pieces never reuse the same footage.
    """
    count = max(1, int(count))
    candidates = viral.find_candidates(
        segments, rms, keywords, TRANSFORM_WINDOW_MIN, TRANSFORM_WINDOW_MAX
    )
    counts = _quality_counts(candidates)
    acceptable = [candidate for candidate in candidates if not quality.is_poor(candidate)]
    _refine_candidates(
        acceptable,
        segments=segments,
        allowed_start=0.0,
        allowed_end=max(0.0, float(duration)),
        min_seconds=TRANSFORM_WINDOW_MIN,
        max_seconds=TRANSFORM_WINDOW_MAX,
        language=language,
    )
    acceptable.sort(key=lambda item: (quality.rank(item), -item.score))
    chosen, duplicate_rejections, duplicate_compared, duplicate_not_compared = (
        _select_distinct(
            acceptable,
            count,
            TRANSFORM_WINDOW_MIN,
            TRANSFORM_WINDOW_MAX,
            language=language,
        )
    )
    selected = [Selected(candidate) for candidate in chosen]
    fallback = 0
    rejections: list[dict[str, Any]] = [
        {
            "start": round(candidate.start, 3),
            "end": round(candidate.end, 3),
            "reason": "candidate failed quality assessment",
            "quality": quality.compact(candidate.quality),
        }
        for candidate in candidates
        if quality.is_poor(candidate)
    ]
    fallback_rejections: list[dict[str, Any]] = []
    if len(selected) < count:
        for candidate in viral.fallback_windows(
            duration, count, TRANSFORM_WINDOW_MIN, TRANSFORM_WINDOW_MAX
        ):
            if len(selected) >= count:
                break
            if any(_overlap(candidate, item.candidate) for item in selected):
                continue
            overlap = [
                segment
                for segment in segments
                if segment.start < candidate.end and segment.end > candidate.start
            ]
            text = " ".join(segment.text.strip() for segment in overlap).strip()
            if not text:
                continue
            assessment = quality.assess_segments(overlap, text=text)
            if assessment["status"] == "poor":
                # A rejected piece is reported, never silently replaced by a
                # different source window that happens to be lying around.
                fallback_rejections.append(
                    {
                        "start": round(candidate.start, 3),
                        "end": round(candidate.end, 3),
                        "reason": "fallback window failed quality assessment",
                        "quality": quality.compact(assessment),
                    }
                )
                continue
            candidate.text = text
            candidate.quality = assessment
            candidate.reasons = ["fallback: evenly spaced source window"]
            candidate.words = viral._words_between(overlap)
            _refine_candidates(
                [candidate],
                segments=segments,
                allowed_start=0.0,
                allowed_end=max(0.0, float(duration)),
                min_seconds=TRANSFORM_WINDOW_MIN,
                max_seconds=TRANSFORM_WINDOW_MAX,
                language=language,
            )
            # The fallback window may have moved to word boundaries.
            if any(_overlap(candidate, item.candidate) for item in selected):
                continue
            duplicate, evidence, compared_any, missing_reason, _ = _find_duplicate(
                candidate, [item.candidate for item in selected], language=language
            )
            if compared_any:
                duplicate_compared += 1
            elif missing_reason:
                duplicate_not_compared[missing_reason] = (
                    duplicate_not_compared.get(missing_reason, 0) + 1
                )
            if duplicate is not None and evidence is not None:
                duplicate_rejections.append(
                    _duplicate_record(candidate, duplicate, evidence)
                )
                continue
            selected.append(
                Selected(
                    candidate,
                    True,
                    "no distinct transcript window left; fallback window passed quality review",
                )
            )
            fallback += 1
    _sorted(selected)
    diagnostics = {
        "requested": count,
        "candidates": len(candidates),
        "selected": len(selected),
        "fallback": fallback,
        "shortfall": max(0, count - len(selected)),
        "quality": counts,
        "quality_rejected": len(rejections) + len(fallback_rejections),
        "quality_rejections": rejections + fallback_rejections,
        "duplicate_compared": duplicate_compared,
        "duplicates_excluded": len(duplicate_rejections),
        "duplicate_rejections": duplicate_rejections,
        "duplicate_not_compared": duplicate_not_compared,
    }
    return selected, diagnostics
