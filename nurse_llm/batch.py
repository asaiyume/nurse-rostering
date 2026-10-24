"""Run a frozen pilot plan, preserving every attempt and explicit denominators."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import statistics
import time
import uuid

from .api import APIError
from .contracts import ROOT
from .evaluate import evaluate
from .inrc2 import convert, read_reference
from .pipeline import build_request, run_baseline, write_json
from .safeguards import VARIANTS


def aggregate(rows: list[dict]) -> dict:
    groups = {}
    for variant in sorted({r["variant"] for r in rows}):
        values = [r for r in rows if r["variant"] == variant]
        valid = [r for r in values if r["hard_valid"]]
        scored = [r for r in values if r["schema_valid"] is not None]
        latency = [r["latency_seconds"] for r in values if r["latency_seconds"] is not None]
        hard_counts = {}
        for r in values:
            for key, value in (r["hard_violation_counts"] or {}).items():
                hard_counts[key] = hard_counts.get(key, 0) + value
        groups[variant] = {
            "trials": len(values), "hard_valid": len(valid), "validity_rate_all_attempts": len(valid) / len(values),
            "schema_valid": sum(bool(r["schema_valid"]) for r in values), "schema_evaluated_trials": len(scored),
            "status_counts": {status: sum(r["status"] == status for r in values) for status in sorted({r["status"] for r in values})},
            "hard_violation_units_by_type": hard_counts,
            "mean_latency_seconds": statistics.mean(latency) if latency else None,
            "total_tokens_reported": sum(r["total_tokens"] or 0 for r in values),
            "token_usage_missing_trials": sum(r["total_tokens"] is None or r.get("usage_incomplete", False) for r in values),
            "revision_outcomes": {outcome: sum(r.get("revision_outcome") == outcome for r in values) for outcome in ["repaired", "regressed", "remained_valid", "remained_invalid"]},
            "mean_partial_soft_score_valid_only": statistics.mean(r["partial_soft_score"] for r in valid) if valid else None,
            "per_case": {case: {"trials": sum(r["case_id"] == case for r in values), "valid": sum(r["case_id"] == case for r in valid)} for case in sorted({r["case_id"] for r in values})},
        }
    return groups


def write_summary(directory: Path, rows: list[dict], planned: int, elapsed: float) -> None:
    summary = {"planned_trials": planned, "completed_trials": len(rows), "wall_seconds": elapsed, "variants": aggregate(rows), "notes": ["Validity denominator includes API failures, empty responses, invalid JSON and abstentions.", "Soft scores cover three pilot categories, not full INRC2 cost.", "Independent repetitions are not deterministic seeds.", "Feasibility is unlabelled unless a supplied witness was independently validated."]}
    write_json(directory / "summary.json", summary)
    write_json(directory / "results.json", sorted(rows, key=lambda r: (r["case_id"], r["variant"], r["repetition"])))
    fields = ["case_id", "repetition", "variant", "feasibility_label", "status", "schema_valid", "hard_valid", "partial_soft_score", "latency_seconds", "total_tokens", "api_call_count", "run_dir"]
    with (directory / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["case_id"], r["variant"], r["repetition"])))
    text = ["# Five nurse pilot results", "", f"Completed {len(rows)}/{planned} planned trials. Wall time: {elapsed:.1f} seconds.", "", "| Variant | Valid / attempted | Mean latency (s) | Reported tokens | Mean partial soft cost on valid rosters |", "| --- | --- | --- | --- | --- |"]
    for variant, stats in summary["variants"].items():
        latency = stats["mean_latency_seconds"]
        text.append(f"| {variant} | {stats['hard_valid']}/{stats['trials']} | {latency:.1f} | {stats['total_tokens_reported']} | {stats['mean_partial_soft_score_valid_only']} |" if latency is not None else f"| {variant} | {stats['hard_valid']}/{stats['trials']} | unavailable | {stats['total_tokens_reported']} | unavailable |")
    text += ["", "These are pilot observations with repeated trials on a small set of cases. The soft score excludes consecutive-day and full-horizon penalties. No optimality or UNSAT-detection claim is made. Raw requests, responses, evaluations and metadata are retained per trial.", ""]
    (directory / "summary.md").write_text("\n".join(text))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "config/experiments/pilot_baseline_v1.json")
    parser.add_argument("--config", type=Path, default=ROOT / "config/llm.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/experiments")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    config = json.loads(args.config.read_text())
    if not plan["cases"] or plan["repetitions"] < 1 or not 1 <= plan["workers"] <= 4 or not plan["variants"] or not set(plan["variants"]) <= set(VARIANTS):
        raise ValueError("Invalid experiment plan")
    if len({case["id"] for case in plan["cases"]}) != len(plan["cases"]):
        raise ValueError("Duplicate case identifiers")
    directory = args.output_dir / (plan["name"] + "_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    cases = {}
    manifest_cases = []
    folder = ROOT / plan["scenario_dir"]
    for case in plan["cases"]:
        name = folder.name
        instance = convert(folder / f"Sc-{name}.txt", folder / f"H0-{name}-{case['history']}.txt", folder / f"WD-{name}-{case['week_data']}.txt")
        label = "unlabelled"
        if case.get("feasible_witness"):
            witness = read_reference(instance, ROOT / case["feasible_witness"])
            if not evaluate(instance, witness)["hard_valid"]:
                raise ValueError("Supplied feasibility witness failed validation")
            label = "known_feasible"
        write_json(directory / "inputs" / (case["id"] + ".json"), instance)
        cases[case["id"]] = (instance, label)
        _, payload = build_request(instance, config, plan["max_output_tokens"])
        manifest_cases.append({**case, "feasibility_label": label, "minimum_staff_days": sum(r["minimum"] for r in instance["coverage"]), "preferred_staff_days": sum(r["preferred"] for r in instance["coverage"]), "requests": len(instance["shift_off_requests"]), "baseline_request_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()})
    safe_config = {key: config[key] for key in ["provider", "base_url", "model", "api_style", "reasoning_effort"] if key in config}
    write_json(directory / "manifest.json", {"plan": plan, "config": safe_config, "cases": manifest_cases, "prompt_sha256": hashlib.sha256((ROOT / "prompts/baseline.txt").read_bytes()).hexdigest(), "scheduling_seed": 4263, "repetitions_are_independent_calls": True})
    # Freeze the prompt used in the suite so its version is reviewable alongside results.
    (directory / "baseline_prompt.txt").write_text((ROOT / "prompts/baseline.txt").read_text())
    jobs = [(case["id"], variant, repeat) for case in plan["cases"] for variant in plan["variants"] for repeat in range(1, plan["repetitions"] + 1)]
    random.Random(4263).shuffle(jobs)

    def trial(case_id: str, variant: str, repetition: int) -> dict:
        instance, label = cases[case_id]
        trial_root = directory / "runs" / case_id / variant / str(repetition)
        try:
            run_dir, metadata = run_baseline(instance, config, trial_root, max_output_tokens=plan["max_output_tokens"], timeout=plan["timeout_seconds"], variant=variant)
        except APIError:
            paths = list(trial_root.glob("*/metadata.json"))
            if not paths:
                raise
            run_dir = paths[0].parent
            metadata = json.loads(paths[0].read_text())
        report_path = run_dir / "evaluation.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        initial_path = run_dir / "stages/generation/evaluation.json"
        initial = json.loads(initial_path.read_text()) if initial_path.exists() else {}
        revision_outcome = None
        if variant in {"critique", "combined"} and any(stage["name"] == "revision" for stage in metadata["stages"]) and initial and report:
            before, after = initial["hard_valid"], report["hard_valid"]
            revision_outcome = "remained_valid" if before and after else "regressed" if before else "repaired" if after else "remained_invalid"
        return {"case_id": case_id, "variant": variant, "repetition": repetition, "feasibility_label": label, "status": metadata["status"], "schema_valid": report.get("schema_valid"), "hard_valid": report.get("hard_valid", False), "hard_violation_counts": report.get("hard_violation_counts"), "partial_soft_score": (report.get("soft_score") or {}).get("partial_total"), "initial_hard_valid": initial.get("hard_valid"), "revision_outcome": revision_outcome, "latency_seconds": metadata.get("latency_seconds"), "total_tokens": (metadata.get("usage") or {}).get("total_tokens"), "usage_incomplete": metadata.get("usage_incomplete", False), "api_call_count": metadata.get("api_call_count"), "run_dir": str(run_dir)}

    rows = []
    started = time.perf_counter()
    print(json.dumps({"suite_dir": str(directory), "planned_trials": len(jobs), "workers": plan["workers"]}), flush=True)
    with ThreadPoolExecutor(max_workers=plan["workers"]) as pool:
        futures = [pool.submit(trial, *job) for job in jobs]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            write_summary(directory, rows, len(jobs), time.perf_counter() - started)
            print(json.dumps({"completed": len(rows), "planned": len(jobs), **row}), flush=True)
    print(json.dumps({"suite_dir": str(directory), "summary": aggregate(rows)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
