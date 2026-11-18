"""Stage 3C-2 word-aware boundary-refinement tests.

All fixtures are synthetic and in-memory.  No media, queue record, Whisper
model, network provider or scheduler is touched.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import quality, selection, transcript_boundaries as boundaries, viral  # noqa: E402
import backend.main as main  # noqa: E402


def word(start, end, text):
    return viral.Word(start, end, text)


def candidate(start, end, words=(), score=50.0, **kwargs):
    return viral.Candidate(
        start=start,
        end=end,
        text=kwargs.pop("text", "Synthetic source text."),
        words=list(words),
        score=score,
        **kwargs,
    )


def refine(candidate_obj, allowed_start=0.0, allowed_end=100.0, min_s=5.0, max_s=30.0, **kwargs):
    return boundaries.refine_candidate(
        candidate_obj,
        allowed_start,
        allowed_end,
        min_s,
        max_s,
        **kwargs,
    )


class RefinementBoundaryTests(unittest.TestCase):
    def test_valid_word_timestamps_produce_word_aligned_bounds(self):
        item = candidate(
            0.0,
            20.0,
            [
                word(1.0, 2.0, "Hello"),
                word(2.0, 3.0, "world."),
                word(18.0, 19.0, "Bye"),
            ],
        )
        result = refine(item)
        self.assertEqual((result["start"], result["end"]), (1.0, 19.0))
        self.assertEqual(result["source"], "words")
        self.assertEqual(result["word_count"], 3)
        self.assertTrue(result["within_limits"])

    def test_leading_and_trailing_pauses_are_excluded(self):
        item = candidate(10.0, 30.0, [word(12.0, 13.0, "Start."), word(27.0, 28.0, "End.")])
        result = refine(item, min_s=1.0, max_s=20.0)
        self.assertEqual(result["start"], 12.0)
        self.assertEqual(result["end"], 28.0)

    def test_fixed_padding_does_not_cross_the_next_word(self):
        item = candidate(
            0.0,
            10.0,
            [word(1.0, 2.0, "Hello."), word(2.0, 3.0, "Next")],
        )
        result = refine(item, min_s=1.0, max_s=10.0)
        self.assertLessEqual(result["end"], 3.0)
        self.assertLess(result["end"], 3.1)

    def test_complete_sentence_boundaries_are_preferred(self):
        item = candidate(
            0.0,
            10.0,
            [word(0.0, 1.0, "Hello."), word(1.0, 2.0, "next")],
        )
        context = list(item.words) + [word(2.0, 3.0, "thought.")]
        result = refine(item, min_s=2.0, max_s=20.0, word_context=context)
        self.assertEqual((result["start"], result["end"]), (0.0, 3.0))
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["complete"])

    def test_partial_boundaries_are_reported_honestly(self):
        item = candidate(
            1.0,
            10.0,
            [word(1.0, 2.0, "unfinished"), word(2.0, 3.0, "sentence.")],
        )
        result = refine(item, min_s=1.0, max_s=10.0)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["complete"])
        self.assertEqual(result["start_reason"], "word_start")

    def test_punctuationless_speech_is_unknown(self):
        item = candidate(
            0.0,
            10.0,
            [word(0.0, 1.0, "hello"), word(1.0, 2.0, "there")],
        )
        result = refine(item, min_s=1.0, max_s=10.0)
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["complete"])

    def test_missing_word_timestamps_use_legacy_fallback(self):
        item = candidate(4.0, 24.0, [])
        result = refine(item, min_s=5.0, max_s=30.0)
        self.assertEqual((result["start"], result["end"]), (4.0, 24.0))
        self.assertEqual(result["source"], "segment")
        self.assertEqual(result["status"], "legacy")
        self.assertTrue(result["within_limits"])

    def test_invalid_word_timestamps_do_not_crash(self):
        item = candidate(
            0.0,
            20.0,
            [
                viral.Word(None, 1.0, "missing"),
                viral.Word(2.0, 1.0, "reversed"),
                viral.Word(0.0, 20.0, "valid."),
            ],
        )
        result = refine(item)
        self.assertEqual(result["word_count"], 1)
        self.assertEqual(result["words"][0]["word"], "valid.")

    def test_none_nan_and_infinity_timestamps_are_safe(self):
        item = candidate(
            0.0,
            20.0,
            [
                viral.Word(None, 1.0, "none"),
                viral.Word(math.nan, 2.0, "nan-start"),
                viral.Word(3.0, math.inf, "inf-end"),
                viral.Word(4.0, 5.0, "valid."),
            ],
        )
        result = refine(item)
        self.assertEqual(result["word_count"], 1)
        self.assertEqual(result["words"][0]["word"], "valid.")

    def test_minimum_duration_is_respected(self):
        item = candidate(0.0, 20.0, [word(1.0, 2.0, "Hello."), word(2.0, 3.0, "world.")])
        result = refine(item, min_s=5.0, max_s=30.0)
        self.assertTrue(result["within_limits"])
        self.assertGreaterEqual(result["end"] - result["start"], 5.0)

    def test_maximum_duration_is_respected_or_reported(self):
        item = candidate(
            0.0,
            45.0,
            [word(1.0, 2.0, "Hello."), word(44.0, 45.0, "world.")],
        )
        result = refine(item, min_s=5.0, max_s=20.0)
        if result["within_limits"]:
            self.assertLessEqual(result["end"] - result["start"], 20.0)
        else:
            self.assertFalse(result["within_limits"])


class ViralRefinementTests(unittest.TestCase):
    def _segments(self, count=12, width=5.0):
        segments = []
        for index in range(count):
            start = index * width
            end = start + width
            segments.append(
                viral.Segment(
                    start,
                    end,
                    f"The spirit warned the village in story {index}.",
                    [
                        word(start, start + width / 2, "The"),
                        word(start + width / 2, end, f"story{index}."),
                    ],
                )
            )
        return segments

    def test_viral_refined_candidates_are_chronological(self):
        segments = self._segments(18)
        selected, diagnostics = selection.select_viral(
            segments, [], None, 3, 20, 30, 90.0, language="en"
        )
        self.assertEqual(len(selected), 3)
        self.assertEqual(
            [item.start for item in selected],
            sorted(item.start for item in selected),
        )
        self.assertEqual(diagnostics["shortfall"], 0)
        for item in selected:
            self.assertIsNotNone(item.candidate.boundary)

    def test_viral_overlap_is_rechecked_after_refinement(self):
        first = candidate(
            0.0,
            20.0,
            [word(0.0, 1.0, "First."), word(19.0, 20.0, "partial")],
        )
        second = candidate(
            20.5,
            40.0,
            [word(20.5, 21.5, "Second.")],
        )
        segments = [
            viral.Segment(0.0, 1.0, "First.", [word(0.0, 1.0, "First.")]),
            viral.Segment(20.0, 21.0, "finished.", [word(20.0, 21.0, "finished.")]),
            viral.Segment(20.5, 21.5, "Second.", [word(20.5, 21.5, "Second.")]),
        ]
        with mock.patch.object(selection.viral, "find_candidates", return_value=[first, second]):
            # Rely on the helper's context words by putting them on the candidates
            # and letting selection use the segment context.
            first.words = [word(0.0, 1.0, "First."), word(19.0, 20.0, "partial")]
            selected, _ = selection.select_viral(
                segments, [], None, 2, 20, 30, 40.0, language="en"
            )
        for left, right in zip(selected, selected[1:]):
            self.assertLessEqual(left.end, right.start + 0.4)
        self.assertLessEqual(len(selected), 2)
        # Avoid a false-positive test if the fixture itself was rejected.
        self.assertTrue(selected)


class EqualRefinementTests(unittest.TestCase):
    def _segments(self):
        return [
            viral.Segment(float(start), float(start + 10), f"Thought {start}.", [
                word(float(start), float(start + 5), f"Thought{start}."),
                word(float(start + 5), float(start + 10), f"More{start}."),
            ])
            for start in range(0, 60, 10)
        ]

    def test_equal_refined_clips_remain_inside_their_intervals(self):
        selected, diagnostics = selection.select_equal(
            self._segments(), 60.0, 2, 10, 20, language="en"
        )
        self.assertEqual(len(selected), 2)
        for item in selected:
            low = 0.0 if item.start < 30.0 else 30.0
            high = low + 30.0
            self.assertGreaterEqual(item.start, low - 1e-6)
            self.assertLessEqual(item.end, high + 1e-6)
        self.assertTrue(all(row["boundary"] for row in diagnostics["intervals"] if row["selected"]))

    def test_equal_never_borrows_from_a_neighbouring_interval(self):
        segments = [
            viral.Segment(0.0, 10.0, "Only first interval.", [
                word(0.0, 5.0, "Only"),
                word(5.0, 10.0, "first."),
            ])
        ]
        selected, diagnostics = selection.select_equal(
            segments, 60.0, 3, 10, 20, language="en"
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(len([row for row in diagnostics["intervals"] if not row["selected"]]), 2)
        for item in selected:
            self.assertLess(item.end, 30.0)

    def test_equal_can_use_safe_crossing_padding_when_all_words_are_inside(self):
        segments = [
            viral.Segment(0.0, 20.0, "First thought.", [
                word(0.0, 10.0, "First"),
                word(10.0, 20.0, "thought."),
            ]),
            viral.Segment(20.0, 35.0, "Second thought.", [
                word(20.0, 25.0, "Second"),
                word(25.0, 30.0, "thought."),
            ]),
        ]
        selected, diagnostics = selection.select_equal(
            segments, 60.0, 2, 20, 30, language="en"
        )
        self.assertEqual(len(selected), 1)
        self.assertGreaterEqual(selected[0].start, 0.0)
        self.assertLessEqual(selected[0].end, 30.0)
        self.assertTrue(diagnostics["intervals"][0]["selected"])

    def test_equal_boundary_exclusion_is_reported(self):
        segments = [
            viral.Segment(20.0, 35.0, "Crossing speech.", [
                word(20.0, 25.0, "Crossing"),
                word(25.0, 35.0, "speech."),
            ])
        ]
        selected, diagnostics = selection.select_equal(
            segments, 60.0, 2, 10, 20, language="en"
        )
        self.assertEqual(selected, [])
        self.assertTrue(any("crossed" in row["reason"] for row in diagnostics["intervals"]))
        self.assertGreater(diagnostics["boundary_excluded"], 0)


class TransformRefinementTests(unittest.TestCase):
    def test_transform_windows_stay_within_source_duration_limits(self):
        segments = [
            viral.Segment(float(start), float(start + 10), f"Story {start}.", [
                word(float(start), float(start + 5), f"Story{start}."),
                word(float(start + 5), float(start + 10), f"More{start}."),
            ])
            for start in range(0, 300, 10)
        ]
        selected, diagnostics = selection.select_transform(
            segments, [], None, 300.0, 2, language="en"
        )
        self.assertEqual(len(selected), 2)
        self.assertEqual(diagnostics["shortfall"], 0)
        for item in selected:
            self.assertGreaterEqual(item.end - item.start, 59.5)
            self.assertLessEqual(item.end - item.start, 110.5)
            self.assertLessEqual(item.end, 300.0)

    def test_transform_platform_targets_are_unchanged(self):
        self.assertEqual(
            main.TRANSFORM_FORMATS,
            ((21, "TikTok", "t21"), (30, "Reels", "t30"), (59, "Shorts", "t59")),
        )


class CaptionBoundTests(unittest.TestCase):
    def test_caption_words_outside_the_final_clip_are_excluded(self):
        item = candidate(
            0.0,
            30.0,
            [
                word(5.0, 9.0, "before"),
                word(10.0, 12.0, "inside"),
                word(18.0, 22.0, "also"),
                word(25.0, 26.0, "after"),
            ],
        )
        captions = main._relative_words(item, 10.0, 20.0)
        self.assertEqual([caption.text for caption in captions], ["inside", "also"])
        self.assertEqual(captions[0].start, 0.0)
        self.assertEqual(captions[-1].end, 10.0)

    def test_invalid_caption_word_timestamps_are_skipped(self):
        item = candidate(
            0.0,
            30.0,
            [
                viral.Word(None, 12.0, "missing"),
                viral.Word(math.nan, 12.0, "nan"),
                word(10.0, 12.0, "valid"),
            ],
        )
        captions = main._relative_words(item, 10.0, 20.0)
        self.assertEqual([caption.text for caption in captions], ["valid"])


class FinalTextAlignmentTests(unittest.TestCase):
    @staticmethod
    def _result(start, end, words):
        return {
            "start": start,
            "end": end,
            "within_limits": True,
            "source": "words",
            "words": [
                {"start": item.start, "end": item.end, "word": item.text}
                for item in words
            ],
        }

    def test_trimmed_refinement_updates_text_to_final_words(self):
        words = [word(0.0, 1.0, "First."), word(1.0, 2.0, "Second."), word(2.0, 3.0, "Third.")]
        item = candidate(0.0, 3.0, words, text="First. Second. Third.")
        result = refine(item, allowed_start=1.0, allowed_end=3.0, min_s=1.0, max_s=2.0, language="en")
        selection._apply_refinement(item, result, language="en")
        self.assertEqual((item.start, item.end), (1.0, 3.0))
        self.assertEqual(item.text, "Second. Third.")

    def test_expanded_refinement_updates_text_to_include_new_words(self):
        words = [word(0.0, 1.0, "First."), word(1.0, 2.0, "Second")]
        item = candidate(0.0, 2.0, words, text="First. Second")
        context = words + [word(2.0, 3.0, "sentence.")]
        result = refine(item, allowed_start=0.0, allowed_end=3.0, min_s=1.0, max_s=3.0, language="en", word_context=context)
        selection._apply_refinement(item, result, language="en")
        self.assertEqual(item.text, "First. Second sentence.")

    def test_original_formatting_is_preserved(self):
        words = [word(0.0, 1.0, "“Hello,”"), word(1.0, 2.0, "she"), word(2.0, 3.0, "said.")]
        item = candidate(0.0, 3.0, words, text="“Hello,” she said.")
        selection._apply_refinement(item, self._result(0.0, 3.0, words), language="en")
        self.assertEqual(item.text, "“Hello,” she said.")

    def test_legacy_fallback_keeps_original_text(self):
        item = candidate(5.0, 35.0, [], text="Legacy transcript.")
        result = refine(item, min_s=30.0, max_s=45.0, language="en")
        selection._apply_refinement(item, result, language="en")
        self.assertEqual(item.text, "Legacy transcript.")

    def test_invalid_word_coverage_keeps_original_text(self):
        words = [word(0.0, 1.0, "Hello"), viral.Word(None, 2.0, "world.")]
        item = candidate(0.0, 2.0, words, text="Hello world.")
        result = refine(item, min_s=1.0, max_s=2.0, language="en")
        selection._apply_refinement(item, result, language="en")
        self.assertEqual(item.text, "Hello world.")

    LONG = (
        "The spirit warned the village at midnight and the elders listened "
        "carefully while the moon rose."
    )
    INTRO = "A traveller arrived before dawn and asked about the road."

    @staticmethod
    def _timed_words(start, text):
        return [word(start + index, start + index + 1, token) for index, token in enumerate(text.split())]

    def test_duplicate_detection_uses_final_text(self):
        first_words = self._timed_words(0.0, self.LONG)
        first = candidate(0.0, float(len(first_words)), first_words, text=self.LONG)
        second_text = f"{self.INTRO} {self.LONG}"
        second_words = self._timed_words(0.0, second_text)
        second = candidate(0.0, float(len(second_words)), second_words, text=second_text)
        split = len(self.INTRO.split())
        selection._apply_refinement(first, self._result(0.0, float(len(first_words)), first_words), language="en")
        selection._apply_refinement(
            second,
            self._result(float(split), float(len(second_words)), second_words[split:]),
            language="en",
        )
        self.assertEqual(first.text, self.LONG)
        self.assertEqual(second.text, self.LONG)
        duplicate, evidence, _, _, _ = selection._find_duplicate(
            second, [first], language="en"
        )
        self.assertIs(duplicate, first)
        self.assertTrue(evidence["duplicate"])

    def test_inverse_duplicate_case_compares_distinct_final_text(self):
        first_words = self._timed_words(0.0, self.LONG)
        first = candidate(0.0, float(len(first_words)), first_words, text=self.LONG)
        second_text = f"{self.INTRO} {self.LONG}"
        second_words = self._timed_words(0.0, second_text)
        second = candidate(0.0, float(len(second_words)), second_words, text=second_text)
        split = len(self.INTRO.split())
        selection._apply_refinement(first, self._result(0.0, float(len(first_words)), first_words), language="en")
        selection._apply_refinement(
            second,
            self._result(0.0, float(split), second_words[:split]),
            language="en",
        )
        self.assertEqual(second.text, self.INTRO)
        duplicate, _, _, _, _ = selection._find_duplicate(second, [first], language="en")
        self.assertIsNone(duplicate)

    def test_cjk_reconstruction_does_not_insert_spaces(self):
        words = [viral.Word(0.0, 1.0, "你好世界。"), viral.Word(1.0, 2.0, "再见世界。")]
        item = candidate(0.0, 2.0, words, text="你好世界。 再见世界。")
        selection._apply_refinement(item, self._result(0.0, 2.0, words), language="zh")
        self.assertEqual(item.text, "你好世界。再见世界。")


class Stage3BAndLegacyIntegrationTests(unittest.TestCase):
    def test_quality_assessment_is_unchanged_before_refinement(self):
        segments = viral.build_segments([
            {
                "start": 0.0,
                "end": 30.0,
                "text": "The spirit warned the village at midnight.",
                "avg_logprob": -0.2,
                "no_speech_prob": 0.02,
                "compression_ratio": 1.1,
                "temperature": 0.0,
                "words": [
                    {"start": 0.0, "end": 1.0, "word": "The", "probability": 0.95}
                ],
            }
        ])
        self.assertEqual(quality.assess_segments(segments)["status"], "good")

    def test_legacy_candidate_without_words_still_works(self):
        item = candidate(5.0, 35.0, [], text="Legacy transcript.")
        result = refine(item, min_s=30.0, max_s=45.0)
        self.assertTrue(result["within_limits"])
        self.assertEqual(result["source"], "segment")
        start, end = main._trim_to_words(item, 100.0, 30.0, 45.0)
        self.assertEqual((start, end), (5.0, 35.0))


if __name__ == "__main__":
    unittest.main()
