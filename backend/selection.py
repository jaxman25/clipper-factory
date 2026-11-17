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

from dataclasses import dataclass
from typing import Any, Sequence

try:
    from backend import quality, viral
except ImportError:  # pragma: no cover - direct execution
    import quality  # type: ignore
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


def select_viral(
    segments: Sequence[viral.Segment],
    rms: Sequence[float],
    keywords: Sequence[str] | None,
    count: int,
    min_seconds: float,
    max_seconds: float,
    duration: float,
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
    acceptable.sort(key=lambda item: (quality.rank(item), -item.score))
    chosen = viral.select_top(acceptable, count, min_seconds, max_seconds)
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
    }
    return selected, diagnostics


def select_equal(
    segments: Sequence[viral.Segment],
    duration: float,
    count: int,
    min_seconds: float,
    max_seconds: float,
    keywords: Sequence[str] | None = None,
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
    if duration <= 0:
        return [], {"requested": count, "selected": 0, "empty": count, "intervals": report}

    width = duration / count
    for index in range(count):
        low = index * width
        high = min(duration, (index + 1) * width)
        best: tuple[int, float, list[viral.Segment], list[str], dict[str, Any]] | None = None
        poor_seen = 0
        for first, segment in enumerate(segments):
            if segment.start < low or segment.end > high:
                continue
            window: list[viral.Segment] = []
            for next_index in range(first, len(segments)):
                following = segments[next_index]
                if following.end > high:
                    break
                window.append(following)
                span = window[-1].end - window[0].start
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
            reason = (
                "only poor-quality speech candidates in this interval"
                if poor_seen
                else "no complete speech segment within the duration limits"
            )
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
                }
            )
            continue
        rank, score, window, reasons, assessment = best
        candidate = viral.Candidate(
            start=window[0].start,
            end=window[-1].end,
            text=viral._join(window),
            words=viral._words_between(window),
            score=max(0.0, min(100.0, score * 2.1)),
            reasons=[f"equal interval {index + 1}/{count}"] + reasons,
            quality=assessment,
        )
        selected.append(Selected(candidate))
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
        "intervals": report,
    }
    return _sorted(selected), diagnostics


def select_transform(
    segments: Sequence[viral.Segment],
    rms: Sequence[float],
    keywords: Sequence[str] | None,
    duration: float,
    count: int,
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
    acceptable.sort(key=lambda item: (quality.rank(item), -item.score))
    chosen = viral.select_top(
        acceptable, count, TRANSFORM_WINDOW_MIN, TRANSFORM_WINDOW_MAX
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
    }
    return selected, diagnostics
