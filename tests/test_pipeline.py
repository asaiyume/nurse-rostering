import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from jsonschema import Draft202012Validator

from rostering.llm.api import APIError, output_text, request_response
from rostering.contracts import ROOT, load_schema, validate_instance
from rostering.evaluate import evaluate
from rostering.inrc2 import convert, read_reference
from rostering.llm.pipeline import run_roster


class RosterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = ROOT / "inrc2/n005w4"
        cls.instance = convert(folder / "Sc-n005w4.txt", folder / "H0-n005w4-0.txt", folder / "WD-n005w4-1.txt")
        cls.reference = read_reference(cls.instance, folder / "Solution_H_0-WD_1-2-3-3/Sol-n005w4-1-0.txt")

    def row(self, roster, nurse, day):
        return next(row for row in roster["roster"] if row["nurse_id"] == nurse and row["day"] == day)

    def test_schemas_are_valid(self):
        for name in ["instance", "roster"]:
            Draft202012Validator.check_schema(load_schema(name))

    def test_parser_preserves_contract_and_history_semantics(self):
        data = self.instance
        self.assertEqual(data["contracts"]["FullTime"]["total_assignments"], {"min": 15, "max": 22})
        self.assertEqual(data["history"]["Patrick"]["last_shift"], "Night")
        self.assertEqual(data["history"]["Stefaan"]["last_shift"], "Off")
        self.assertEqual(data["forbidden_successions"]["Night"], ["Early", "Late"])
        self.assertEqual(len(data["coverage"]), 42)
        self.assertTrue(any(r["minimum"] == 0 and r["preferred"] == 1 for r in data["coverage"]))

    def test_all_scenario_families_parse(self):
        for folder in sorted((ROOT / "inrc2").iterdir()):
            if not folder.is_dir():
                continue
            with self.subTest(scenario=folder.name):
                name = folder.name
                data = convert(folder / f"Sc-{name}.txt", folder / f"H0-{name}-0.txt", folder / f"WD-{name}-1.txt")
                self.assertEqual(len(data["nurses"]), int(name[1:4]))
                self.assertEqual(len(data["coverage"]), 7 * len(data["skills"]) * len(data["shift_types"]))

    def test_mismatched_scenario_and_incomplete_coverage_are_rejected(self):
        folder = ROOT / "inrc2/n005w4"
        with self.assertRaises(ValueError):
            convert(folder / "Sc-n005w4.txt", ROOT / "inrc2/n012w8/H0-n012w8-0.txt", folder / "WD-n005w4-1.txt")
        data = copy.deepcopy(self.instance)
        data["coverage"].pop()
        with self.assertRaises(ValueError):
            validate_instance(data)

    def test_supplied_reference_is_valid_with_known_weekly_costs(self):
        report = evaluate(self.instance, self.reference)
        self.assertTrue(report["hard_valid"])
        self.assertEqual(sum(report["hard_violation_counts"].values()), 0)
        self.assertEqual(report["soft_score"], {"preferred_coverage": 120, "shift_off_requests": 30, "complete_weekends": 0, "partial_total": 150})
        self.assertFalse(report["soft_scope"]["is_full_inrc2_score"])

    def test_history_to_monday_transition_is_checked(self):
        roster = copy.deepcopy(self.reference)
        self.row(roster, "Patrick", "Mon")["shift"] = "Early"
        report = evaluate(self.instance, roster)
        self.assertTrue(any(v["type"] == "shift_succession" and v["day"] == "Mon" and v["nurse_id"] == "Patrick" for v in report["hard_violations"]))
        self.assertIsNone(report["soft_score"])

    def test_off_breaks_succession(self):
        roster = copy.deepcopy(self.reference)
        self.row(roster, "Patrick", "Mon").update(shift="Off", skill=None)
        self.row(roster, "Patrick", "Tue").update(shift="Early", skill="Nurse")
        report = evaluate(self.instance, roster)
        self.assertFalse(any(v["type"] == "shift_succession" and v["nurse_id"] == "Patrick" for v in report["hard_violations"]))

    def test_missing_nurse_day_is_not_implicitly_off(self):
        roster = copy.deepcopy(self.reference)
        roster["roster"].remove(self.row(roster, "Patrick", "Tue"))
        report = evaluate(self.instance, roster)
        self.assertFalse(report["roster_complete"])
        self.assertFalse(report["hard_valid"])
        self.assertTrue(any(v["type"] == "missing_nurse_day" for v in report["output_issues"]))

    def test_duplicate_assignments_do_not_fill_two_coverage_slots(self):
        roster = copy.deepcopy(self.reference)
        duplicate = copy.deepcopy(self.row(roster, "Patrick", "Mon"))
        duplicate["skill"] = "HeadNurse"
        roster["roster"].append(duplicate)
        report = evaluate(self.instance, roster)
        self.assertEqual(report["hard_violation_counts"]["single_assignment"], 1)
        self.assertGreater(report["hard_violation_counts"]["minimum_coverage"], 0)
        self.assertFalse(report["hard_valid"])

    def test_missing_skill_cannot_satisfy_coverage(self):
        roster = copy.deepcopy(self.reference)
        self.row(roster, "Nguyen", "Mon")["skill"] = "HeadNurse"
        report = evaluate(self.instance, roster)
        self.assertEqual(report["hard_violation_counts"]["required_skill"], 1)
        self.assertGreater(report["hard_violation_counts"]["minimum_coverage"], 0)

    def test_hallucinated_nurse_cannot_satisfy_coverage(self):
        roster = copy.deepcopy(self.reference)
        self.row(roster, "Nguyen", "Mon")["nurse_id"] = "InventedNurse"
        report = evaluate(self.instance, roster)
        self.assertFalse(report["hard_valid"])
        self.assertGreater(report["hard_violation_counts"]["minimum_coverage"], 0)
        self.assertTrue(any(v["type"] == "unknown_nurse" for v in report["output_issues"]))

    def test_multiskilled_nurse_counts_only_for_assigned_role(self):
        roster = copy.deepcopy(self.reference)
        self.row(roster, "Stefaan", "Mon")["skill"] = "Nurse"
        report = evaluate(self.instance, roster)
        self.assertTrue(any(v["type"] == "minimum_coverage" and v["day"] == "Mon" and v["shift"] == "Night" and v["skill"] == "HeadNurse" for v in report["hard_violations"]))

    def test_schema_failure_and_abstention_are_not_scored_as_valid(self):
        for value in [None, [], {"status": "candidate"}, {"schema_version": "1.0", "status": "infeasible_claim", "explanation": "No roster found", "roster": []}]:
            with self.subTest(value=value):
                report = evaluate(self.instance, value)
                self.assertFalse(report["hard_valid"])
                self.assertIsNone(report["hard_violation_counts"])
                self.assertIsNone(report["soft_score"])

    def test_reference_never_enters_prompt_and_dry_run_never_calls_api(self):
        config = json.loads((ROOT / "config/llm.json").read_text())
        with tempfile.TemporaryDirectory() as temp, patch("rostering.llm.pipeline.request_response") as request:
            directory, metadata = run_roster(self.instance, config, Path(temp), dry_run=True)
            request.assert_not_called()
            prompt = (directory / "prompt.txt").read_text()
            self.assertNotIn("Solution_H_", prompt)
            self.assertNotIn("Sol-n005w4", prompt)
            self.assertNotIn("tools", json.loads((directory / "request.json").read_text()))
            self.assertEqual(metadata["status"], "dry_run")

    def test_failed_model_outputs_are_saved_without_repair_or_retry(self):
        config = json.loads((ROOT / "config/llm.json").read_text())
        for text, response_status, expected in [("", "completed", "empty_response"), ("```json\n{}\n```", "completed", "invalid_json"), (json.dumps(self.reference), "incomplete", "incomplete_response")]:
            response = {"model": "x-test-2", "status": response_status, "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
            with tempfile.TemporaryDirectory() as temp, patch("rostering.llm.pipeline.request_response", return_value=(response, 0.1)) as request:
                directory, metadata = run_roster(self.instance, config, Path(temp))
                self.assertEqual(request.call_count, 1)
                self.assertEqual(metadata["status"], expected)
                self.assertEqual((directory / "response.txt").read_text(), text)
                self.assertFalse(json.loads((directory / "evaluation.json").read_text())["hard_valid"])


class APITests(unittest.TestCase):
    def test_text_extraction_skips_reasoning(self):
        self.assertEqual(output_text({"output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]}), "OK")

    def test_api_errors_do_not_echo_credentials_or_error_bodies(self):
        config = {"api_style": "responses", "base_url": "https://example.invalid/v1", "api_key_env": "SOCLAAS_API_KEY"}
        secret = "secret-test-value"
        error = urllib.error.HTTPError("https://example.invalid", 401, secret, {}, io.BytesIO(secret.encode()))
        with patch.dict(os.environ, {"SOCLAAS_API_KEY": secret}), patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(APIError) as caught:
                request_response(config, {"model": "test"})
            self.assertNotIn(secret, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
