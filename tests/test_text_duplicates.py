"""Stage 3C-3 conservative text-level duplicate detection tests.

All fixtures are synthetic and in-memory.  No media, queue record, Whisper
model, network provider or scheduler is touched.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import quality, selection, transcript_boundaries as boundaries, viral  # noqa: E402


LONG = (
    "The spirit warned the village at midnight and the elders listened "
    "carefully while the moon rose over the silent river."
)
LONG_VARIANT = (
    "The spirit warned the village at midnight and the elders listened "
    "carefully while the moon rose over the silent river and the children slept."
)


def word(start, end, text):
    return viral.Word(start, end, text)


def candidate(start, end, text, *, score=50.0, quality_value=None, words=()):
    return viral.Candidate(
        start=start,
        end=end,
        text=text,
        words=list(words),
        score=score,
        quality=quality_value,
    )


def duplicate_evidence(left, right, **kwargs):
    return boundaries.text_duplicate_evidence(left, right, **kwargs)


class NormalizationTests(unittest.TestCase):
    def test_capitalization_is_ignored_for_comparison(self):
        evidence = duplicate_evidence(LONG.lower(), LONG.upper())
        self.assertTrue(evidence["duplicate"])
        self.assertEqual(evidence["reason"], "exact_normalized_text")

    def test_punctuation_is_ignored_for_comparison(self):
        punctuated = "The spirit warned, the village at midnight; the elders listened carefully!"
        plain = "The spirit warned the village at midnight the elders listened carefully"
        self.assertTrue(duplicate_evidence(punctuated, plain)["duplicate"])

    def test_extra_whitespace_is_ignored_for_comparison(self):
        spaced = (
            "  The\tspirit\n warned   the village at midnight and the elders "
            "listened carefully while the moon rose over the silent river.  "
        )
        self.assertTrue(duplicate_evidence(spaced, LONG)["duplicate"])

    def test_unicode_normalization_is_applied(self):
        composed = "Café au lait près de la rivière le soir " * 2
        decomposed = "Cafe\u0301 au lait pre\u0300s de la rivie\u0300re le soir " * 2
        self.assertTrue(duplicate_evidence(composed, decomposed)["duplicate"])

    def test_arabic_text_is_compared_safely(self):
        text = "مرحبا بكم في القرية الليلة قال الجد حكاية قديمة عن الروح"
        evidence = duplicate_evidence(text, text.replace("،", ""))
        self.assertTrue(evidence["duplicate"])
        self.assertGreater(evidence["right_tokens"], 5)

    def test_cjk_text_is_compared_safely(self):
        text = "灵 在 午夜 警告 了 村民 长老 们 都 听见 了"
        self.assertTrue(duplicate_evidence(text, text)["duplicate"])

    def test_punctuationless_text_is_compared_safely(self):
        text = "the spirit warned the village at midnight and the elders listened carefully"
        self.assertTrue(duplicate_evidence(text, text)["duplicate"])


class TrueDuplicateTests(unittest.TestCase):
    def test_identical_transcripts_are_duplicates(self):
        self.assertTrue(duplicate_evidence(LONG, LONG)["duplicate"])

    def test_same_transcript_at_different_timestamps_is_a_duplicate(self):
        first = candidate(0.0, 30.0, LONG)
        second = candidate(120.0, 150.0, LONG)
        evidence = duplicate_evidence(first.text, second.text)
        self.assertTrue(evidence["duplicate"])
        self.assertEqual(evidence["reason"], "exact_normalized_text")

    def test_minor_punctuation_changes_are_duplicates(self):
        punctuated = (
            "The spirit warned the village at midnight, and the elders listened "
            "carefully while the moon rose over the silent river!"
        )
        self.assertTrue(duplicate_evidence(LONG, punctuated)["duplicate"])

    def test_substantially_overlapping_long_transcripts_are_duplicates(self):
        evidence = duplicate_evidence(LONG, LONG_VARIANT)
        self.assertTrue(evidence["duplicate"])
        self.assertGreaterEqual(evidence["containment"], 0.88)

    def test_same_distinctive_sentence_with_minor_surroundings_is_a_duplicate(self):
        core = (
            "The spirit warned the village at midnight and the elders listened "
            "carefully while the moon rose."
        )
        left = f"Before dawn {core} Then the river was quiet."
        right = f"At dusk {core} Then the river went silent."
        evidence = duplicate_evidence(left, right)
        self.assertTrue(evidence["duplicate"])


class FalsePositiveProtectionTests(unittest.TestCase):
    def test_same_topic_with_different_wording_is_not_a_duplicate(self):
        left = (
            "The old farmer explained how rain arrives late in the dry season "
            "and why the harvest must wait for the soil to soften."
        )
        right = (
            "Villagers gathered near the well to discuss the changing weather "
            "and agreed that planting should begin after the first storm."
        )
        self.assertFalse(duplicate_evidence(left, right)["duplicate"])

    def test_common_short_phrases_are_not_duplicates(self):
        left = (
            "We will rise again after the long night and the village will rebuild "
            "its market before the next season begins."
        )
        right = (
            "We will rise again was painted on the old wall, but the children "
            "were talking about school and the broken bridge."
        )
        self.assertFalse(duplicate_evidence(left, right)["duplicate"])

    def test_shared_names_are_not_duplicates(self):
        left = (
            "Amara carried water to the elders and described the strange tracks "
            "she found beside the northern field after sunrise."
        )
        right = (
            "Amara repaired the roof before the storm and laughed with her "
            "brother about the noisy goats in the yard."
        )
        self.assertFalse(duplicate_evidence(left, right)["duplicate"])

    def test_shared_short_quotations_are_not_duplicates(self):
        left = (
            "The teacher wrote the river remembers everything on the board and "
            "asked the class to explain the lesson in their own words."
        )
        right = (
            "A traveller repeated the river remembers everything at the market "
            "while selling baskets, cloth and small copper bells."
        )
        self.assertFalse(duplicate_evidence(left, right)["duplicate"])

    def test_repeated_choruses_or_refrains_are_not_automatically_duplicates(self):
        chorus = "we will rise again we will rise again we will rise again tonight"
        left = f"The first verse tells about hunger and fear. {chorus}. The ending asks for courage."
        right = f"A different verse describes the harvest and rain. {chorus}. The ending names the river."
        self.assertFalse(duplicate_evidence(left, right)["duplicate"])

    def test_short_transcripts_with_misleading_similarity_are_not_duplicates(self):
        evidence = duplicate_evidence("we will rise again", "we will rise again")
        self.assertFalse(evidence["duplicate"])
        self.assertEqual(evidence["reason"], "too_short")

    def test_empty_transcripts_are_not_duplicates(self):
        evidence = duplicate_evidence("", "")
        self.assertFalse(evidence["duplicate"])
        self.assertFalse(evidence["compared"])
        self.assertEqual(evidence["reason"], "missing_transcript")

    def test_missing_transcripts_are_not_duplicates(self):
        self.assertFalse(duplicate_evidence(None, LONG)["duplicate"])
        self.assertFalse(duplicate_evidence(LONG, None)["duplicate"])

    def test_unknown_language_does_not_raise(self):
        evidence = duplicate_evidence(LONG, LONG_VARIANT, language="zz-unknown")
        self.assertTrue(evidence["duplicate"])
        self.assertEqual(evidence["language"], "zz-unknown")

    def test_similar_opening_with_different_remainder_is_not_a_duplicate(self):
        left = (
            "At the edge of the forest the hunter found a broken gate and "
            "followed the muddy path toward the abandoned mill."
        )
        right = (
            "At the edge of the forest the children built a small shelter and "
            "told stories about a friendly goat until sunset."
        )
        self.assertFalse(duplicate_evidence(left, right)["duplicate"])


class ViralDuplicateSelectionTests(unittest.TestCase):
    def test_viral_retains_the_stronger_ranked_duplicate(self):
        strong = candidate(0.0, 30.0, LONG, score=90.0)
        weak = candidate(100.0, 130.0, LONG, score=50.0)
        with mock.patch.object(
            selection.viral, "find_candidates", return_value=[strong, weak]
        ):
            selected, diagnostics = selection.select_viral(
                [viral.Segment(0.0, 1.0, "x")],
                [],
                None,
                2,
                30,
                45,
                200.0,
                language="en",
            )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].start, 0.0)
        self.assertEqual(diagnostics["duplicates_excluded"], 1)
        self.assertEqual(diagnostics["shortfall"], 1)
        self.assertEqual(diagnostics["duplicate_rejections"][0]["duplicate_of"]["start"], 0.0)

    def test_viral_output_remains_chronological_after_duplicate_filtering(self):
        later = candidate(100.0, 130.0, LONG, score=90.0)
        earlier = candidate(
            0.0,
            30.0,
            "A different story about the market, the rain and the old bridge "
            "where traders gathered before sunrise.",
            score=80.0,
        )
        with mock.patch.object(
            selection.viral, "find_candidates", return_value=[later, earlier]
        ):
            selected, _ = selection.select_viral(
                [], [], None, 2, 30, 45, 200.0, language="en"
            )
        self.assertEqual([item.start for item in selected], [0.0, 100.0])

    def test_viral_duplicate_shortfall_is_reported_honestly(self):
        first = candidate(0.0, 30.0, LONG, score=90.0)
        second = candidate(40.0, 70.0, LONG, score=80.0)
        third = candidate(80.0, 110.0, LONG, score=70.0)
        with mock.patch.object(
            selection.viral, "find_candidates", return_value=[first, second, third]
        ):
            selected, diagnostics = selection.select_viral(
                [], [], None, 3, 30, 45, 200.0, language="en"
            )
        self.assertEqual(len(selected), 1)
        self.assertEqual(diagnostics["shortfall"], 2)
        self.assertEqual(diagnostics["duplicates_excluded"], 2)

    def test_existing_point_four_second_overlap_protection_is_unchanged(self):
        first = candidate(0.0, 30.0, LONG, score=90.0)
        overlapping = candidate(30.3, 60.3, LONG_VARIANT, score=80.0)
        separate = candidate(
            30.5,
            60.5,
            "A separate account of the market and the rain that arrived after "
            "the traders had already closed their stalls.",
            score=70.0,
        )
        with mock.patch.object(
            selection.viral, "find_candidates", return_value=[first, overlapping, separate]
        ):
            selected, _ = selection.select_viral(
                [], [], None, 3, 30, 45, 200.0, language="en"
            )
        self.assertEqual([item.start for item in selected], [0.0, 30.5])


class EqualDuplicateSelectionTests(unittest.TestCase):
    def _segment(self, start, text):
        return viral.Segment(
            float(start),
            float(start + 20),
            text,
            [
                word(float(start), float(start + 10), text.split()[0]),
                word(float(start + 10), float(start + 20), text.split()[-1]),
            ],
        )

    def test_equal_never_borrows_across_intervals(self):
        segments = [
            self._segment(5.0, LONG),
            self._segment(35.0, LONG),
        ]
        selected, diagnostics = selection.select_equal(
            segments, 60.0, 2, 10, 20, language="en"
        )
        self.assertEqual(len(selected), 1)
        self.assertLess(selected[0].end, 30.0)
        self.assertEqual(diagnostics["duplicates_excluded"], 1)
        self.assertFalse(diagnostics["intervals"][1]["selected"])
        self.assertIn("duplicate", diagnostics["intervals"][1]["reason"])

    def test_equal_does_not_reject_merely_similar_topics(self):
        segments = [
            self._segment(
                5.0,
                "The farmer explained how the rain arrives late in the dry season "
                "and why the harvest must wait.",
            ),
            self._segment(
                35.0,
                "Villagers gathered near the well to discuss the changing weather "
                "and agreed to plant after the first storm.",
            ),
        ]
        selected, diagnostics = selection.select_equal(
            segments, 60.0, 2, 10, 20, language="en"
        )
        self.assertEqual(len(selected), 2)
        self.assertEqual(diagnostics["duplicates_excluded"], 0)


class TransformDuplicateSelectionTests(unittest.TestCase):
    def test_transform_avoids_duplicate_source_pieces(self):
        first = candidate(0.0, 70.0, LONG, score=90.0)
        second = candidate(100.0, 170.0, LONG, score=80.0)
        with mock.patch.object(
            selection.viral, "find_candidates", return_value=[first, second]
        ):
            selected, diagnostics = selection.select_transform(
                [], [], None, 200.0, 2, language="en"
            )
        self.assertEqual(len(selected), 1)
        self.assertEqual(diagnostics["duplicates_excluded"], 1)
        self.assertEqual(diagnostics["shortfall"], 1)


class PreservedBehaviorTests(unittest.TestCase):
    def test_stage_3b_quality_filtering_remains_unchanged(self):
        poor = candidate(
            0.0,
            30.0,
            LONG,
            score=90.0,
            quality_value={"status": "poor", "available": True, "reasons": ["synthetic"]},
        )
        good = candidate(50.0, 80.0, LONG_VARIANT, score=60.0)
        with mock.patch.object(
            selection.viral, "find_candidates", return_value=[poor, good]
        ):
            selected, diagnostics = selection.select_viral(
                [], [], None, 1, 30, 45, 200.0, language="en"
            )
        self.assertEqual([item.start for item in selected], [50.0])
        self.assertEqual(diagnostics["quality_rejected"], 1)

    def test_stage_3c_2_boundary_refinement_remains_unchanged(self):
        item = candidate(
            0.0,
            20.0,
            "Hello world. Goodbye now.",
            words=[
                word(1.0, 2.0, "Hello."),
                word(2.0, 3.0, "world."),
                word(18.0, 19.0, "Goodbye."),
            ],
        )
        result = boundaries.refine_candidate(item, 0.0, 30.0, 1.0, 20.0, language="en")
        self.assertEqual((result["start"], result["end"]), (1.0, 19.0))
        self.assertTrue(result["within_limits"])

    def test_legacy_candidates_without_word_timestamps_remain_compatible(self):
        legacy = candidate(5.0, 35.0, LONG)
        with mock.patch.object(
            selection.viral, "find_candidates", return_value=[legacy]
        ):
            selected, diagnostics = selection.select_viral(
                [], [], None, 1, 30, 45, 60.0, language="en"
            )
        self.assertEqual(len(selected), 1)
        self.assertEqual((selected[0].start, selected[0].end), (5.0, 35.0))
        self.assertEqual(diagnostics["shortfall"], 0)


if __name__ == "__main__":
    unittest.main()
