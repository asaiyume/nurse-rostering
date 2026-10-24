import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from rostering.llm.api import APIError, completed, output_text, token_usage
from rostering.llm.batch import aggregate
from rostering.contracts import ROOT
from rostering.evaluate import evaluate
from rostering.llm.pipeline import build_request, run_roster
from rostering.llm.safeguards import roster_generation_schema


def response(text):
    return {"model": "x-test-2", "choices": [{"finish_reason": "stop", "message": {"content": text}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


class SafeguardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.instance = json.loads((ROOT / "data/instances/n005w4_h0_wd1.json").read_text())
        from rostering.inrc2 import read_reference
        cls.roster = read_reference(cls.instance, ROOT / "inrc2/n005w4/Solution_H_0-WD_1-2-3-3/Sol-n005w4-1-0.txt")
        cls.config = json.loads((ROOT / "config/llm.json").read_text())

    def test_schema_has_case_enums_and_matches_api_syntax(self):
        schema = roster_generation_schema(self.instance)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        self.assertFalse(list(validator.iter_errors(self.roster)))
        wrong = copy.deepcopy(self.roster)
        wrong["roster"][0]["nurse_id"] = "Invented"
        self.assertTrue(list(validator.iter_errors(wrong)))
        for style, field in [("responses", "text"), ("chat_completions", "response_format")]:
            _, baseline = build_request(self.instance, {**self.config, "api_style": style}, 16000)
            _, structured = build_request(self.instance, {**self.config, "api_style": style}, 16000, "structured")
            self.assertNotIn(field, baseline)
            self.assertIn(field, structured)
            if style == "chat_completions":
                self.assertEqual(structured["response_format"]["json_schema"]["schema"], schema)
            else:
                self.assertEqual(structured["text"]["format"]["schema"], schema)

    def test_combined_has_three_bounded_calls_and_no_evaluator_feedback(self):
        returned = [(response(json.dumps(self.roster)), 1.0), (response("Check Patrick's history-to-Monday transition; all counts otherwise agree."), 2.0), (response(json.dumps(self.roster)), 3.0)]
        observed_call_counts = []
        with tempfile.TemporaryDirectory() as temp, patch("rostering.llm.pipeline.request_response", side_effect=returned) as request:
            def observed_evaluate(*args):
                observed_call_counts.append(request.call_count)
                return evaluate(*args)
            with patch("rostering.llm.pipeline.evaluate", side_effect=observed_evaluate):
                directory, metadata = run_roster(self.instance, self.config, Path(temp), variant="combined")
            self.assertEqual(request.call_count, 3)
            self.assertEqual(observed_call_counts, [3, 3])
            self.assertEqual(metadata["api_call_count"], 3)
            self.assertEqual(metadata["usage"]["total_tokens"], 450)
            self.assertEqual(metadata["latency_seconds"], 6.0)
            requests = [call.args[1] for call in request.call_args_list]
            self.assertIn("response_format", requests[0])
            self.assertNotIn("response_format", requests[1])
            self.assertIn("response_format", requests[2])
            self.assertTrue((directory / "stages/generation/evaluation.json").exists())

    def test_failed_generation_does_not_trigger_critic_retry(self):
        with tempfile.TemporaryDirectory() as temp, patch("rostering.llm.pipeline.request_response", return_value=(response(""), 1.0)) as request:
            _, metadata = run_roster(self.instance, self.config, Path(temp), variant="critique")
            self.assertEqual(request.call_count, 1)
            self.assertEqual(metadata["status"], "empty_response")
            self.assertIn("critique_skipped", metadata)

    def test_api_normalisation(self):
        value = response("OK")
        self.assertEqual(output_text(value), "OK")
        self.assertTrue(completed(value))
        self.assertEqual(token_usage(value), {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
        value["choices"][0]["finish_reason"] = "length"
        self.assertFalse(completed(value))

    def test_api_failure_usage_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp, patch("rostering.llm.pipeline.request_response", side_effect=APIError("HTTP failure")):
            with self.assertRaises(APIError):
                run_roster(self.instance, self.config, Path(temp))
            metadata = json.loads(next(Path(temp).glob("*/metadata.json")).read_text())
            self.assertEqual(metadata["status"], "api_error")
            self.assertIsNone(metadata["usage"])
            self.assertTrue(metadata["usage_incomplete"])

    def test_aggregation_keeps_failures_in_denominator(self):
        base = {"variant": "baseline", "case_id": "test", "latency_seconds": 1, "total_tokens": 10, "hard_violation_counts": {"minimum_coverage": 0}, "partial_soft_score": 10}
        rows = [{**base, "status": "valid_roster", "schema_valid": True, "hard_valid": True}, {**base, "status": "api_error", "schema_valid": None, "hard_valid": False, "partial_soft_score": None}]
        summary = aggregate(rows)["baseline"]
        self.assertEqual(summary["trials"], 2)
        self.assertEqual(summary["validity_rate_all_attempts"], 0.5)
        self.assertEqual(summary["mean_partial_soft_score_valid_only"], 10)


if __name__ == "__main__":
    unittest.main()
