import contextlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from nurse_llm.contracts import ROOT
from nurse_llm.inrc2 import read_reference
from nurse_llm.pipeline import run_baseline, write_json


class ReportTests(unittest.TestCase):
    def test_matched_report_replays_outputs_without_api_calls(self):
        instance = json.loads((ROOT / "data/instances/n005w4_h0_wd1.json").read_text())
        reference = read_reference(instance, ROOT / "inrc2/n005w4/Solution_H_0-WD_1-2-3-3/Sol-n005w4-1-0.txt")
        config = json.loads((ROOT / "config/llm.json").read_text())
        response = {"model": "x-test-2", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(reference)}}], "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}}
        main = runpy.run_path(str(ROOT / "scripts/summarize_ablation.py"))["main"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = []
            for variant in ["baseline", "structured", "critique", "combined"]:
                with patch("nurse_llm.pipeline.request_response", return_value=(response, 0.1)):
                    directory, metadata = run_baseline(instance, config, root / "runs", variant=variant)
                rows.append({"case_id": "one", "variant": variant, "repetition": 1, "feasibility_label": "known_feasible", "status": "valid_roster", "schema_valid": True, "hard_valid": True, "hard_violation_counts": {"minimum_coverage": 0}, "partial_soft_score": 150, "latency_seconds": metadata["latency_seconds"], "total_tokens": metadata["usage"]["total_tokens"], "api_call_count": metadata["api_call_count"], "run_dir": str(directory)})
            manifest = {"config": config, "prompt_sha256": "same", "cases": [{"id": "one", "baseline_request_sha256": "same"}], "plan": {"repetitions": 1, "max_output_tokens": 16000, "timeout_seconds": 240, "workers": 1}}
            for kind in ["baseline", "safeguards"]:
                write_json(root / kind / "manifest.json", manifest)
                write_json(root / kind / "results.json", [r for r in rows if (r["variant"] == "baseline") == (kind == "baseline")])
            argv = ["summarize_ablation.py", "--baseline", str(root / "baseline"), "--safeguards", str(root / "safeguards"), "--out", str(root / "report")]
            with patch("sys.argv", argv), patch("nurse_llm.pipeline.request_response") as request, contextlib.redirect_stdout(io.StringIO()):
                main()
                request.assert_not_called()
            result = json.loads((root / "report.json").read_text())
            self.assertEqual(result["total_trials"], 4)
            self.assertEqual(result["total_api_calls"], 8)
            self.assertEqual(result["generation_schema_conformance"]["checked_stages"], 3)
            self.assertEqual(result["generation_schema_conformance"]["conforming_stages"], 3)
            self.assertEqual(result["variants"]["combined"]["revision_outcomes"]["remained_valid"], 1)
            self.assertTrue((root / "report.csv").exists())

    def test_mismatched_model_configurations_are_rejected(self):
        main = runpy.run_path(str(ROOT / "scripts/summarize_ablation.py"))["main"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / "a/manifest.json", {"config": {"model": "A"}, "prompt_sha256": "same"})
            write_json(root / "b/manifest.json", {"config": {"model": "B"}, "prompt_sha256": "same"})
            with patch("sys.argv", ["summarize_ablation.py", "--baseline", str(root / "a"), "--safeguards", str(root / "b")]):
                with self.assertRaises(ValueError):
                    main()


if __name__ == "__main__":
    unittest.main()
