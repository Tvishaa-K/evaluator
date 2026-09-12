"""Regression tests for app.score.score_transcript() JSON normalization.

The scorer parses LLM output, so it has to survive every shape the model
plausibly emits — not just the one the prompt asked for.

Run: venv/bin/python -m unittest discover tests -v
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SARVAM_API_KEY", "test-key-not-used")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import score  # noqa: E402

DIMS = ["resolution_rate", "compliance", "customer_understanding", "dead_air",
        "fact_checking", "data_confirmation", "interruption_handling",
        "escalation_analysis"]


def payload(**overrides):
    scores = {d: {"score": 5, "reasoning": "x"} for d in DIMS}
    scores.update(overrides)
    return json.dumps({
        "scores": scores,
        "composite_score": 999,          # deliberately wrong; we recompute
        "summary": "a call happened",
        "fraud_flags": [],
        "critical_failure": False,
    })


def run(raw, fact_check=None):
    with patch.object(score, "chat", return_value=raw):
        return score.score_transcript("transcript", 0.0, fact_check or {})


class ScoreNormalizationTests(unittest.TestCase):

    def test_null_dimension_does_not_crash(self):
        """The call4 production bug. When no factual claims were made, the
        prompt says to null out fact_checking and the model emits
        "fact_checking": null instead of {"score": null}. That used to raise
        AttributeError: 'NoneType' object has no attribute 'get'."""
        result = run(payload(fact_checking=None))

        self.assertEqual(result["scores"]["fact_checking"]["score"], None)
        # 7 remaining dimensions at 5 each; the null one is excluded, not zeroed.
        self.assertEqual(result["composite_score"], 35)

    def test_call_with_nothing_to_factcheck_is_not_punished(self):
        """The null dimension is dropped from the numerator AND the
        denominator: 35/70, not 35/80. Scoring it as a 0 out of 80 would
        penalise a call for having no claims to check."""
        result = run(payload(fact_checking=None), fact_check={"claims_checked": 0})

        self.assertEqual(result["composite_score"], 35)
        self.assertEqual(result["max_possible"], 70)
        self.assertAlmostEqual(result["composite_score"] / result["max_possible"], 0.5)

    def test_bare_number_dimension_keeps_its_score(self):
        """Model drops the wrapper object and returns just the number. The
        score is still usable, so keep it rather than nulling the dimension."""
        result = run(payload(compliance=7))
        self.assertEqual(result["scores"]["compliance"]["score"], 7)
        self.assertEqual(result["composite_score"], 40 - 5 + 7)

    def test_composite_is_recomputed_not_trusted(self):
        """The model claimed 999. We sum the dimensions ourselves."""
        self.assertEqual(run(payload())["composite_score"], 40)

    def test_max_possible_reflects_whether_claims_were_checked(self):
        no_claims = run(payload(), fact_check={"claims_checked": 0})
        checked = run(payload(), fact_check={"claims_checked": 3, "mismatches": []})
        self.assertEqual(no_claims["max_possible"], 70)
        self.assertEqual(checked["max_possible"], 80)

    def test_fields_misnested_inside_scores_are_lifted_out(self):
        """Malformed JSON drops top-level fields in among the dimensions."""
        raw = json.loads(payload())
        raw["scores"]["fraud_flags"] = ["asked for OTP"]
        raw["scores"]["critical_failure"] = True
        del raw["fraud_flags"], raw["critical_failure"]

        result = run(json.dumps(raw))

        self.assertEqual(result["fraud_flags"], ["asked for OTP"])
        self.assertTrue(result["critical_failure"])
        self.assertEqual(set(result["scores"]), set(DIMS))

    def test_prompt_spells_out_the_null_object_shape(self):
        """The wording that caused the crash asked for 'dimension 5 as null'."""
        prompt = score.build_prompt("t", 0.0, {"claims_checked": 0})
        self.assertIn('{"score": null', prompt)
        self.assertIn("Do not set fact_checking itself to null", prompt)


if __name__ == "__main__":
    unittest.main()
