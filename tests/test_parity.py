import copy
import itertools
import json
from pathlib import Path
import random
import runpy
import tempfile
import time
import unittest
from unittest.mock import patch

from rostering.classical.__main__ import solve
from rostering.contracts import ROOT
from rostering.evaluate import evaluate
from rostering.llm.api import APIError
from rostering.llm.pipeline import build_request, run_roster


def response(text):
    return {"model": "test", "choices": [{"finish_reason": "stop", "message": {"content": text}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = runpy.run_path(str(ROOT / "scripts/run_comparison.py"))
        cls.plan, cls.cases = cls.runner["load_plan"](ROOT / "config/experiments/parity_v1.json")
        cls.instance = next(iter(cls.cases.values()))
        cls.config = json.loads((ROOT / "config/llm.json").read_text())
        cls.roster, _ = solve(cls.instance)

    def test_selection_has_controlled_history_and_demand_contrasts(self):
        self.assertEqual(len(self.cases), 15)
        for h in range(3):
            self.assertEqual(sum(c["history"] == h for c in self.plan["cases"]), 5)
        for n in self.plan["selection"]["nurse_counts"]:
            group = {c["role"]: c for c in self.plan["cases"] if c["nurses"] == n}
            anchor, history, demand = [group[k] for k in ["anchor", "history_contrast", "demand_contrast"]]
            self.assertEqual(anchor["week_data"], history["week_data"])
            self.assertEqual(anchor["history"], demand["history"])
            self.assertNotEqual(anchor["minimum_staff_days"], demand["minimum_staff_days"])
            left, right = self.cases[anchor["id"]], self.cases[history["id"]]
            self.assertEqual(left["coverage"], right["coverage"])
            changed = 0
            for row in left["coverage"]:
                if row["day"] != "Mon" or not row["minimum"]:
                    continue
                for nurse in left["nurses"]:
                    if row["skill"] not in nurse["skills"]:
                        continue
                    allowed = [row["shift"] not in x["forbidden_successions"].get(x["history"][nurse["id"]]["last_shift"], []) for x in [left, right]]
                    changed += allowed[0] != allowed[1]
            self.assertGreater(changed, 0)

    def test_classical_ignores_soft_and_unused_workload_fields(self):
        changed = copy.deepcopy(self.instance)
        for row in changed["coverage"]:
            row["preferred"] = row["minimum"] + 100
        changed["shift_off_requests"] = [{"nurse_id": n["id"], "day": d, "shift": "Any"}
                                          for n in changed["nurses"] for d in changed["days"]]
        for c in changed["contracts"].values():
            c.update(total_assignments={"min": 0, "max": 0},
                     consecutive_work_days={"min": 0, "max": 0},
                     consecutive_days_off={"min": 0, "max": 0},
                     complete_weekends=not c["complete_weekends"], max_working_weekends=0)
        for h in changed["history"].values():
            h["total_assignments"] = 999
            h["working_weekends"] = 999
        result, metadata = solve(changed)
        self.assertEqual(result["roster"], self.roster["roster"])
        self.assertTrue(evaluate(changed, result)["hard_valid"])
        self.assertEqual(metadata["mode"], "hard_constraints_only")
        self.assertFalse(metadata["optimality_applicable"])

    def test_classical_matches_independent_exhaustive_tiny_instances(self):
        rng = random.Random(4263)
        for case in range(20):
            x = copy.deepcopy(self.instance)
            x["nurses"] = x["nurses"][:2]
            x["history"] = {n["id"]: x["history"][n["id"]] for n in x["nurses"]}
            x["shift_off_requests"] = []
            for n in x["nurses"]:
                n["skills"] = ["Nurse"]
                h = x["history"][n["id"]]
                h["last_shift"] = rng.choice(["Off", "Night", "Early"])
                work = int(h["last_shift"] != "Off")
                h.update(consecutive_work_days=work, consecutive_same_shift=work,
                         consecutive_days_off=1 - work)
            for row in x["coverage"]:
                value = rng.randrange(3) if row["day"] in ["Mon", "Tue"] and row["shift"] in ["Early", "Night"] and row["skill"] == "Nurse" else 0
                row.update(minimum=value, preferred=value)
            feasible = False
            # Independent nurse/day representation; no required-slot reduction.
            for shifts in itertools.product(["Off", "Early", "Night"], repeat=4):
                grid = {(n["id"], d): shifts[i * 2 + j]
                        for i, n in enumerate(x["nurses"]) for j, d in enumerate(["Mon", "Tue"])}
                if any(sum(grid[n["id"], r["day"]] == r["shift"] for n in x["nurses"]) < r["minimum"]
                       for r in x["coverage"] if r["day"] in ["Mon", "Tue"] and r["skill"] == "Nurse"):
                    continue
                if any(grid[n["id"], "Mon"] in x["forbidden_successions"].get(x["history"][n["id"]]["last_shift"], [])
                       or grid[n["id"], "Tue"] in x["forbidden_successions"].get(grid[n["id"], "Mon"], [])
                       for n in x["nurses"]):
                    continue
                feasible = True
                break
            with self.subTest(case=case):
                roster, metadata = solve(x)
                self.assertEqual(roster["status"] == "candidate", feasible)
                self.assertEqual(metadata["infeasibility_proven"], not feasible)
                if feasible:
                    self.assertTrue(evaluate(x, roster)["hard_valid"])

    def test_all_llm_stages_are_hard_only(self):
        outputs = [response(json.dumps(self.roster)), response("No confirmed hard violations."), response(json.dumps(self.roster))]
        with tempfile.TemporaryDirectory() as temp, patch("rostering.llm.pipeline.request_response", side_effect=[(r, 0.1) for r in outputs]) as request:
            _, metadata = run_roster(self.instance, self.config, Path(temp), variant="combined")
        self.assertEqual(metadata["mode"], "hard_constraints_only")
        self.assertEqual(metadata["prompt_version"], "hard_only_v1")
        self.assertIsNone(metadata["timeout_seconds"])
        self.assertIsNone(metadata["total_timeout_seconds"])
        self.assertTrue(all(call.args[2] is None for call in request.call_args_list))
        for call in request.call_args_list:
            prompt = call.args[1]["messages"][0]["content"]
            self.assertNotIn("Minimise the sum", prompt)
            self.assertNotIn("costs 30", prompt)
            self.assertNotIn("minimum and preferred demand", prompt)
        self.assertIn("hard-constraint feasibility only", request.call_args_list[0].args[1]["messages"][0]["content"])

    def test_classical_proves_skill_double_counting_and_monday_conflicts_infeasible(self):
        x = copy.deepcopy(self.instance)
        x["nurses"] = x["nurses"][:1]
        nurse = x["nurses"][0]
        nurse["skills"] = ["Nurse", "HeadNurse"]
        x["history"] = {nurse["id"]: x["history"][nurse["id"]]}
        x["shift_off_requests"] = []
        history = x["history"][nurse["id"]]
        history.update(last_shift="Off", consecutive_work_days=0,
                       consecutive_same_shift=0, consecutive_days_off=1)
        for row in x["coverage"]:
            value = int(row["day"] == "Mon" and row["shift"] == "Early")
            row.update(minimum=value, preferred=value)
        # One multi-skilled nurse cannot simultaneously cover both roles.
        roster, metadata = solve(x)
        self.assertEqual(roster["status"], "infeasible_claim")
        self.assertTrue(metadata["infeasibility_proven"])
        for row in x["coverage"]:
            if row["skill"] == "HeadNurse":
                row.update(minimum=0, preferred=0)
        history.update(last_shift="Night", consecutive_work_days=1,
                       consecutive_same_shift=1, consecutive_days_off=0)
        # The sole nurse is now forbidden from the required Monday Early shift.
        roster, metadata = solve(x)
        self.assertEqual(roster["status"], "infeasible_claim")
        self.assertTrue(metadata["infeasibility_proven"])

    def test_total_trial_budget_is_shared_across_calls(self):
        clock = [0.0]
        outputs = [response(json.dumps(self.roster)), response("No hard violations."), response(json.dumps(self.roster))]
        def fake_request(*args):
            i = fake_request.calls
            fake_request.calls += 1
            clock[0] = [200, 230, 235][i]
            return outputs[i], 1.0
        fake_request.calls = 0
        with tempfile.TemporaryDirectory() as temp, patch("rostering.llm.pipeline.time.perf_counter", side_effect=lambda: clock[0]), patch("rostering.llm.pipeline.request_response", side_effect=fake_request) as request:
            run_roster(self.instance, self.config, Path(temp), variant="combined", total_timeout=240)
        self.assertEqual([c.args[2] for c in request.call_args_list], [240, 40, 10])

    def test_exhausted_total_budget_does_not_start_another_call(self):
        clock = [0.0]
        def fake_request(*args):
            clock[0] = 241
            return response(json.dumps(self.roster)), 241.0
        with tempfile.TemporaryDirectory() as temp, patch("rostering.llm.pipeline.time.perf_counter", side_effect=lambda: clock[0]), patch("rostering.llm.pipeline.request_response", side_effect=fake_request) as request:
            with self.assertRaisesRegex(APIError, "Total trial time budget"):
                run_roster(self.instance, self.config, Path(temp), variant="combined", total_timeout=240)
            self.assertEqual(request.call_count, 1)
            metadata = json.loads(next(Path(temp).glob("*/metadata.json")).read_text())
            self.assertEqual(metadata["api_call_count"], 1)

    def test_report_keeps_failures_and_updates_readme_from_actual_counts(self):
        case = self.plan["cases"][0]
        plan = {**self.plan, "cases": [case], "repetitions": 1}
        rows = []
        for variant in ["classical", "baseline", "structured", "critique", "combined"]:
            rows.append({"case_id": case["id"], "nurses": case["nurses"], "variant": variant,
                         "repetition": 1, "status": "candidate" if variant == "classical" else "api_error",
                         "schema_valid": variant == "classical", "hard_valid": variant == "classical",
                         "hard_violation_counts": {} if variant == "classical" else None,
                         "runtime_seconds": 1, "latency_seconds": None if variant == "classical" else 1,
                         "api_call_count": 0 if variant == "classical" else 1,
                         "total_tokens": None, "usage_incomplete": variant != "classical",
                         "artifact_dir": variant})
        snapshot = self.runner["publish_snapshot"]
        with tempfile.TemporaryDirectory() as temp, patch.dict(snapshot.__globals__, {"ROOT": Path(temp)}):
            root = Path(temp)
            (root / "README.md").write_text("Before\n<!-- parity-results:start -->\nPending\n<!-- parity-results:end -->\nAfter\n")
            (root / "run").mkdir()
            (root / "run/manifest.json").write_text(json.dumps({"plan": plan, "config": {}, "source_hashes": {}}))
            summary = snapshot(root / "run", plan, rows, time.perf_counter())
            self.assertTrue(summary["complete"])
            self.assertEqual(summary["api_calls"], 4)
            self.assertEqual(summary["variants"]["baseline"]["trials"], 1)
            self.assertEqual(summary["variants"]["baseline"]["hard_valid"], 0)
            self.assertEqual(summary["variants"]["baseline"]["token_usage_missing_trials"], 1)
            text = (root / "README.md").read_text()
            self.assertIn("| baseline | 1 | 0/1 |", text)
            self.assertIn("Before", text)
            self.assertIn("After", text)


if __name__ == "__main__":
    unittest.main()
