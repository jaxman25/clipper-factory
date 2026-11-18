"""Stage 3C-1 tests for transcript-boundary normalization.

All fixtures are in-memory; no Whisper model, media, queue record or provider is
touched.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import quality, transcript_boundaries as boundaries, viral  # noqa: E402


class TimestampTests(unittest.TestCase):
    def test_valid_timestamps(self):
        self.assertEqual(boundaries.finite_time(0), 0.0)
        self.assertEqual(boundaries.finite_time(12.5), 12.5)
        self.assertEqual(boundaries.finite_time("3.25"), 3.25)

    def test_none_timestamps(self):
        self.assertIsNone(boundaries.finite_time(None))
        self.assertIsNone(boundaries.finite_time("not-a-number"))

    def test_nan_timestamps(self):
        self.assertIsNone(boundaries.finite_time(float("nan")))
        self.assertIsNone(boundaries.finite_time("nan"))

    def test_positive_and_negative_infinity(self):
        self.assertIsNone(boundaries.finite_time(float("inf")))
        self.assertIsNone(boundaries.finite_time(float("-inf")))
        self.assertIsNone(boundaries.finite_time("inf"))

    def test_negative_timestamps(self):
        self.assertIsNone(boundaries.finite_time(-0.01))
        self.assertIsNone(boundaries.finite_time(-100))


class SegmentSanitizationTests(unittest.TestCase):
    def test_reversed_segment_ranges_are_rejected(self):
        raw = [
            {"start": 5.0, "end": 4.0, "text": "reversed"},
            {"start": 2.0, "end": 2.0, "text": "empty"},
            {"start": 0.0, "end": 1.0, "text": "valid"},
        ]
        sanitized = boundaries.sanitize_segments(raw)
        self.assertEqual([item["text"] for item in sanitized], ["valid"])

    def test_text_and_metadata_are_preserved(self):
        raw = [
            {
                "start": 0,
                "end": 2,
                "text": "  Hello,  world!  ",
                "avg_logprob": -0.2,
                "temperature": 0.0,
                "custom_field": "kept",
            }
        ]
        sanitized = boundaries.sanitize_segments(raw)
        self.assertEqual(sanitized[0]["text"], "  Hello,  world!  ")
        self.assertEqual(sanitized[0]["avg_logprob"], -0.2)
        self.assertEqual(sanitized[0]["temperature"], 0.0)
        self.assertEqual(sanitized[0]["custom_field"], "kept")
        self.assertNotIn("words", sanitized[0])

    def test_missing_word_timestamps_are_not_invented(self):
        raw = [{"start": 0, "end": 3, "text": "No word timings here."}]
        sanitized = boundaries.sanitize_segments(raw)
        self.assertNotIn("words", sanitized[0])
        span = boundaries.sentence_spans(raw)[0]
        self.assertEqual(span["source"], "segment")
        self.assertEqual(span["start"], 0.0)
        self.assertEqual(span["end"], 3.0)

    def test_invalid_word_timestamps_are_filtered(self):
        raw = [
            {
                "start": 0,
                "end": 5,
                "text": "Hello world.",
                "words": [
                    {"start": 0, "end": 1, "word": "Hello", "probability": 0.9},
                    {"start": None, "end": 2, "word": "world"},
                    {"start": 3, "end": 2, "word": "reversed"},
                    {"start": 2, "end": math.inf, "word": "infinite"},
                    {"start": 3, "end": 4, "word": "again.", "probability": 0.8},
                ],
            }
        ]
        sanitized = boundaries.sanitize_segments(raw)
        self.assertEqual(
            [word["word"] for word in sanitized[0]["words"]],
            ["Hello", "again."],
        )
        self.assertEqual(sanitized[0]["words"][0]["probability"], 0.9)


class TextJoiningTests(unittest.TestCase):
    def test_ordinary_english_joining(self):
        self.assertEqual(
            boundaries.join_segment_text(["  Hello", "world.  "]),
            "Hello world.",
        )

    def test_arabic_joining(self):
        self.assertEqual(
            boundaries.join_segment_text(["مرحبا", "بالعالم."], language="ar"),
            "مرحبا بالعالم.",
        )

    def test_cjk_joining_without_inappropriate_spaces(self):
        self.assertEqual(
            boundaries.join_segment_text(["你好", "世界。"], language="zh"),
            "你好世界。",
        )
        self.assertEqual(
            boundaries.join_segment_text(["こんにちは", "世界。"], language="ja"),
            "こんにちは世界。",
        )

    def test_mixed_script_text(self):
        self.assertEqual(
            boundaries.join_segment_text(["Hello", "世界。"]),
            "Hello 世界。",
        )
        self.assertEqual(
            boundaries.join_segment_text(["مرحبا", "world"]),
            "مرحبا world",
        )

    def test_legitimate_repeated_phrases_are_unchanged(self):
        self.assertEqual(
            boundaries.join_segment_text(["I do.", "I do."]),
            "I do. I do.",
        )
        self.assertEqual(
            boundaries.normalized_tokens("I do. I do."),
            ["i", "do", "i", "do"],
        )


class PunctuationTests(unittest.TestCase):
    def test_arabic_question_mark(self):
        self.assertTrue(boundaries.is_sentence_end("ماذا حدث؟"))
        self.assertEqual(boundaries.boundary_strength("ماذا حدث؟"), "strong")

    def test_cjk_sentence_punctuation(self):
        for text in ("你好。", "真的吗？", "小心！"):
            with self.subTest(text=text):
                self.assertTrue(boundaries.is_sentence_end(text))

    def test_indic_punctuation(self):
        self.assertTrue(boundaries.is_sentence_end("नमस्ते।"))
        self.assertTrue(boundaries.is_sentence_end("समाप्त॥"))

    def test_ellipsis_is_weak_not_complete(self):
        for text in ("Wait…", "Wait...", "Wait…\""):
            with self.subTest(text=text):
                self.assertFalse(boundaries.is_sentence_end(text))
                self.assertEqual(boundaries.boundary_strength(text), "weak")
                self.assertIsNotNone(boundaries.terminal_mark(text))

    def test_closing_quotes_and_brackets(self):
        self.assertTrue(boundaries.is_sentence_end('He said "go."'))
        self.assertTrue(boundaries.is_sentence_end("(Really?)"))
        self.assertTrue(boundaries.is_sentence_end("Finished.]"))
        self.assertFalse(boundaries.is_sentence_end("unfinished)"))

    def test_punctuationless_text_is_unknown(self):
        self.assertEqual(boundaries.boundary_strength("hello there"), "none")
        self.assertFalse(boundaries.is_sentence_end("hello there"))
        self.assertIsNone(boundaries.terminal_mark("hello there"))


class SentenceSpanTests(unittest.TestCase):
    def test_word_spans_can_cross_whisper_segments(self):
        segments = [
            {
                "start": 0.0,
                "end": 1.2,
                "text": "Hello",
                "words": [{"start": 0.0, "end": 0.4, "word": "Hello"}],
            },
            {
                "start": 1.2,
                "end": 2.5,
                "text": "world. Next",
                "words": [
                    {"start": 1.2, "end": 1.8, "word": "world."},
                    {"start": 2.0, "end": 2.5, "word": "Next"},
                ],
            },
        ]
        spans = boundaries.sentence_spans(segments)
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0]["text"], "Hello world.")
        self.assertEqual((spans[0]["start"], spans[0]["end"]), (0.0, 1.8))
        self.assertTrue(spans[0]["complete"])
        self.assertEqual(spans[1]["text"], "Next")
        self.assertFalse(spans[1]["complete"])

    def test_punctuationless_word_text_remains_unknown(self):
        segments = [
            {
                "start": 0,
                "end": 2,
                "text": "hello there",
                "words": [
                    {"start": 0, "end": 1, "word": "hello"},
                    {"start": 1, "end": 2, "word": "there"},
                ],
            }
        ]
        spans = boundaries.sentence_spans(segments)
        self.assertEqual(len(spans), 1)
        self.assertFalse(spans[0]["complete"])
        self.assertFalse(spans[0]["weak"])

    def test_legacy_segments_use_segment_boundaries(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Legacy sentence."},
            {"start": 2.0, "end": 4.0, "text": "Another thought"},
        ]
        spans = boundaries.sentence_spans(segments)
        self.assertEqual([span["source"] for span in spans], ["segment", "segment"])
        self.assertTrue(spans[0]["complete"])
        self.assertFalse(spans[1]["complete"])
        self.assertEqual((spans[0]["start"], spans[0]["end"]), (0.0, 2.0))

    def test_chronological_sentence_spans(self):
        segments = [
            {
                "start": 10.0,
                "end": 11.0,
                "text": "Second.",
                "words": [{"start": 10.0, "end": 11.0, "word": "Second."}],
            },
            {
                "start": 0.0,
                "end": 1.0,
                "text": "First.",
                "words": [{"start": 0.0, "end": 1.0, "word": "First."}],
            },
        ]
        spans = boundaries.sentence_spans(segments)
        self.assertEqual([span["start"] for span in spans], [0.0, 10.0])
        self.assertEqual([span["text"] for span in spans], ["First.", "Second."])


class FingerprintTests(unittest.TestCase):
    def test_unicode_normalization_and_case_folding(self):
        self.assertEqual(
            boundaries.normalized_tokens("Ｈｅｌｌｏ，  WORLD!"),
            ["hello", "world"],
        )
        self.assertEqual(
            boundaries.normalized_tokens("Café, CAFÉ"),
            ["café", "café"],
        )
        self.assertEqual(
            boundaries.fingerprint("  The Spirit,  the spirit! "),
            "the spirit the spirit",
        )

    def test_empty_text_has_empty_fingerprint(self):
        self.assertEqual(boundaries.normalized_tokens("..."), [])
        self.assertEqual(boundaries.fingerprint(None), "")


class ViralIntegrationTests(unittest.TestCase):
    def test_invalid_segment_timestamps_do_not_crash_build_segments(self):
        raw = [
            {"start": None, "end": 1, "text": "none"},
            {"start": 0, "end": math.nan, "text": "nan"},
            {"start": 0, "end": math.inf, "text": "inf"},
            {"start": 2, "end": 3, "text": "valid"},
        ]
        segments = viral.build_segments(raw)
        self.assertEqual([segment.text for segment in segments], ["valid"])

    def test_invalid_word_timestamps_are_ignored_by_build_segments(self):
        raw = [
            {
                "start": 0,
                "end": 2,
                "text": "Hello world.",
                "words": [
                    {"start": None, "end": 1, "word": "Hello"},
                    {"start": 1, "end": 2, "word": "world."},
                ],
            }
        ]
        segments = viral.build_segments(raw)
        self.assertEqual([word.text for word in segments[0].words], ["world."])

    def test_legacy_segments_keep_their_shape(self):
        raw = [
            {
                "start": 0.0,
                "end": 40.0,
                "text": "The spirit warned the village.",
                "words": [],
            }
        ]
        segments = viral.build_segments(raw)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].start, 0.0)
        self.assertEqual(segments[0].end, 40.0)
        self.assertEqual(segments[0].text, "The spirit warned the village.")
        self.assertEqual(segments[0].words, [])


class Stage3BRegressionTests(unittest.TestCase):
    def test_quality_status_is_unchanged_for_legacy_and_metric_backed_segments(self):
        legacy = viral.build_segments(
            [{"start": 0.0, "end": 40.0, "text": "Legacy transcript.", "words": []}]
        )
        self.assertEqual(quality.assess_segments(legacy)["status"], "review")

        modern = viral.build_segments(
            [
                {
                    "start": 0.0,
                    "end": 40.0,
                    "text": "The spirit warned the village at midnight.",
                    "avg_logprob": -0.2,
                    "no_speech_prob": 0.02,
                    "compression_ratio": 1.1,
                    "temperature": 0.0,
                    "words": [
                        {
                            "start": 0.0,
                            "end": 1.0,
                            "word": "The",
                            "probability": 0.95,
                        }
                    ],
                }
            ]
        )
        self.assertEqual(quality.assess_segments(modern)["status"], "good")
        self.assertFalse(quality.assess_segments(modern)["language_confidence_used"])


if __name__ == "__main__":
    unittest.main()
