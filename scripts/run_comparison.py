"""Run the frozen, matched hard-only benchmark; save every attempt and resume safely."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rostering.classical.__main__ import solve
from rostering.contracts import validate_instance
from rostering.evaluate import evaluate
from rostering.llm.api import APIError
from rostering.llm.pipeline import run_roster
from rostering.llm.safeguards import VARIANTS


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def source_hashes():
    paths = [ROOT / "scripts/run_comparison.py", ROOT / "uv.lock"]
    for pattern in ["rostering/**/*.py", "schemas/*.json", "prompts/*.txt"]:
        paths.extend(ROOT.glob(pattern))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def load_plan(path):
    plan = json.loads(path.read_text())
    if (plan["mode"] != "hard_constraints_only" or plan["prompt_version"] != "hard_only_v1"
            or plan["repetitions"] < 1 or set(plan["variants"]) != set(VARIANTS)
            or not 1 <= plan["workers"] <= 8
            or (plan["time_limit_seconds"] is not None and not 0 < plan["time_limit_seconds"] < float("inf"))
            or plan["max_output_tokens"] < 1 or plan["audit_output_tokens"] < 1 or not plan["cases"]):
        raise ValueError("Invalid comparison plan")
    cases = {}
    for case in plan["cases"]:
        raw = (ROOT / case["instance"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != case["sha256"]:
            raise ValueError("Input fingerprint changed: " + case["id"])
        instance = json.loads(raw)
        validate_instance(instance)
        if len(instance["nurses"]) != case["nurses"] or case["id"] in cases:
            raise ValueError("Duplicate or mismatched case")
        cases[case["id"]] = instance
    return plan, cases


def classical_trial(case, instance, directory, budget):
    target = directory / "classical" / case["id"]
    existing = target / "result.json"
    if existing.exists():
        return json.loads(existing.read_text())
    result, metadata = solve(instance, time_limit=budget, exhaustive=budget is None)
    report = evaluate(instance, result)
    for name, value in [("roster", result), ("metadata", metadata), ("evaluation", report)]:
        save_json(target / (name + ".json"), value)
    row = {"case_id": case["id"], "nurses": case["nurses"], "variant": "classical",
           "repetition": 1, "status": result["status"], "schema_valid": report["schema_valid"],
           "hard_valid": report["hard_valid"], "hard_violation_counts": report["hard_violation_counts"],
           "runtime_seconds": metadata["runtime_seconds"], "latency_seconds": None,
           "api_call_count": 0, "total_tokens": None, "usage_incomplete": False,
           "infeasibility_proven": metadata["infeasibility_proven"],
           "artifact_dir": target.relative_to(directory).as_posix()}
    save_json(existing, row)
    return row


def llm_trial(case, instance, variant, repetition, config, plan, directory):
    target = directory / "llm" / case["id"] / variant / str(repetition)
    existing = target / "result.json"
    if existing.exists():
        return json.loads(existing.read_text())
    saved = list(target.glob("*/metadata.json"))
    if saved:
        # Never replay an interrupted or uncertain request: keep it as an attempt.
        run_dir = saved[0].parent
        metadata = json.loads(saved[0].read_text())
        if metadata["status"] == "started":
            metadata["status"] = "interrupted"
            metadata["usage_incomplete"] = True
            save_json(run_dir / "metadata.json", metadata)
    else:
        try:
            run_dir, metadata = run_roster(
                instance, config, target, variant=variant,
                max_output_tokens=plan["max_output_tokens"],
                audit_output_tokens=plan["audit_output_tokens"],
                timeout=plan["time_limit_seconds"], total_timeout=plan["time_limit_seconds"])
        except APIError:
            saved = list(target.glob("*/metadata.json"))
            if not saved:
                raise
            run_dir = saved[0].parent
            metadata = json.loads(saved[0].read_text())
    report_path = run_dir / "evaluation.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    initial_path = run_dir / "stages/generation/evaluation.json"
    initial = json.loads(initial_path.read_text()) if initial_path.exists() else {}
    outcome = None
    if any(s["name"] == "revision" for s in metadata["stages"]) and initial and report:
        before, after = initial["hard_valid"], report["hard_valid"]
        outcome = ("remained_valid" if before and after else "regressed" if before
                   else "repaired" if after else "remained_invalid")
    row = {"case_id": case["id"], "nurses": case["nurses"], "variant": variant,
           "repetition": repetition, "status": metadata["status"],
           "schema_valid": report.get("schema_valid"),
           "hard_valid": bool(report.get("hard_valid")) and metadata["status"] == "valid_roster",
           "hard_violation_counts": report.get("hard_violation_counts"),
           "runtime_seconds": metadata.get("runtime_seconds"),
           "latency_seconds": metadata.get("latency_seconds"),
           "api_call_count": metadata["api_call_count"],
           "total_tokens": (metadata.get("usage") or {}).get("total_tokens"),
           "usage_incomplete": metadata.get("usage_incomplete", False),
           "returned_model": metadata.get("returned_model"),
           "initial_hard_valid": initial.get("hard_valid"), "revision_outcome": outcome,
           "artifact_dir": run_dir.relative_to(directory).as_posix()}
    save_json(existing, row)
    return row


def aggregate(rows):
    groups = {}
    for variant in ["classical", *VARIANTS]:
        selected = [r for r in rows if r["variant"] == variant]
        if not selected:
            continue
        runtimes = [r["runtime_seconds"] for r in selected if r["runtime_seconds"] is not None]
        latencies = [r["latency_seconds"] for r in selected if r["latency_seconds"] is not None]
        counts = Counter()
        for row in selected:
            counts.update(row["hard_violation_counts"] or {})
        groups[variant] = {
            "trials": len(selected), "hard_valid": sum(r["hard_valid"] for r in selected),
            "cases_tested": len({r["case_id"] for r in selected}),
            "cases_with_any_valid": len({r["case_id"] for r in selected if r["hard_valid"]}),
            "schema_valid": sum(bool(r["schema_valid"]) for r in selected),
            "status_counts": dict(Counter(r["status"] for r in selected)),
            "mean_runtime_seconds": statistics.mean(runtimes) if runtimes else None,
            "mean_model_latency_seconds": statistics.mean(latencies) if latencies else None,
            "api_calls": sum(r["api_call_count"] for r in selected),
            "reported_tokens": sum(r["total_tokens"] or 0 for r in selected),
            "token_usage_missing_trials": sum(r["total_tokens"] is None or r["usage_incomplete"] for r in selected) if variant != "classical" else 0,
            "evaluated_candidate_trials": sum(r["hard_violation_counts"] is not None for r in selected),
            "hard_violation_units": dict(counts),
            "revision_outcomes": dict(Counter(r["revision_outcome"] for r in selected if r.get("revision_outcome"))),
        }
    return groups


def protocol_text(plan, config):
    budget = plan["time_limit_seconds"]
    deadline = ("No client or whole-trial time limit is imposed; classical search also runs without a time limit. "
                if budget is None else
                f"Classical search and each LLM trial have a {budget:g}-second time limit; "
                "each request is bounded by the remaining trial budget. ")
    return (deadline + f"Token caps are {plan['max_output_tokens']:,} per roster stage and "
            f"{plan['audit_output_tokens']:,} for the audit, including reasoning and answer tokens. "
            f"All four variants request reasoning effort {config.get('reasoning_effort', 'provider default')}. ")


def report_text(summary, plan):
    groups = summary["variants"]
    lines = ["# Matched hard-only comparison", "",
             f"Status: **{'complete' if summary['complete'] else 'in progress'}**. "
             f"{summary['completed_trials']}/{summary['planned_trials']} saved trials; "
             f"{summary['api_calls']} model calls recorded.", "",
             f"The same {len(plan['cases'])} input files are used by both solutions across "
             f"{len({c['nurses'] for c in plan['cases']})} nurse-count strata. "
             f"Solution A runs once per input; each LLM variant runs {plan['repetitions']} times per input. "
             "All inputs represent one independent seven-day week at week zero.", "",
             "Both solve hard-constraint feasibility only: minimum coverage, qualified skills, "
             "at most one working shift per nurse-day, and legal successions including history into Monday. "
             "Complete nurse-day output and valid identifiers are also required. Surplus staffing is allowed. "
             "Neither optimizes preferences, weekends, fairness or workload. Evaluator soft scores are diagnostic only.", "",
             protocol_text(plan, summary['execution']['config']) +
             "LLM latency includes all model calls; runtime also includes local "
             "pipeline work. Classical runs finish before the LLM batch to avoid local CPU contention. "
             f"LLM jobs are shuffled with scheduling seed {plan['scheduling_seed']}; this does not seed model sampling.", "",
             "| Method | Cases covered | Hard-valid trials / attempted | Output-schema valid | Mean runtime (s) | Mean model latency (s) | API calls | Reported tokens |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    def number(value):
        return "—" if value is None else f"{value:.3f}"
    for name in ["classical", *VARIANTS]:
        if name not in groups:
            continue
        s = groups[name]
        lines.append(f"| {name} | {s['cases_tested']}/{len(plan['cases'])} | {s['hard_valid']}/{s['trials']} | {s['schema_valid']}/{s['trials']} | "
                     f"{number(s['mean_runtime_seconds'])} | {number(s['mean_model_latency_seconds'])} | "
                     f"{s['api_calls']} | {'—' if name == 'classical' else format(s['reported_tokens'], ',')} |")
    lines += ["", "Counts include every saved attempt, including errors, incomplete outputs and abstentions. "
              "A classical infeasibility proof is a resolved decision, not a hard-valid roster. "
              f"The classical denominator is {len(plan['cases'])}; each LLM denominator is "
              f"{len(plan['cases']) * plan['repetitions']} at completion. "
              "Model repetitions on one input do not create different benchmark instances.", "",
              "## Validity by nurse count", "",
              "| Nurses | Classical | Baseline | Structured | Critique | Combined |",
              "| --- | --- | --- | --- | --- | --- |"]
    for n in sorted({c["nurses"] for c in plan["cases"]}):
        counts = []
        for v in ["classical", *VARIANTS]:
            selected = [r for r in summary["rows"] if r["nurses"] == n and r["variant"] == v]
            counts.append(f"{sum(r['hard_valid'] for r in selected)}/{len(selected)}")
        lines.append(f"| {n} | " + " | ".join(counts) + " |")
    lines += ["", "## Cases and decision outcomes", "",
              "| Case | Role | Minimum staff-days | Classical status | B valid baseline / structured / critique / combined |",
              "| --- | --- | --- | --- | --- |"]
    for case in plan["cases"]:
        a = next((r for r in summary["rows"] if r["case_id"] == case["id"] and r["variant"] == "classical"), {})
        counts = []
        for v in VARIANTS:
            rs = [r for r in summary["rows"] if r["case_id"] == case["id"] and r["variant"] == v]
            counts.append(f"{sum(r['hard_valid'] for r in rs)}/{len(rs)}")
        lines.append(f"| {case['id']} | {case['role']} | {case['minimum_staff_days']} | {a.get('status', 'pending')} | " + " / ".join(counts) + " |")
    lines += ["", "## Violations and uncertainty", "",
              "| Method | Evaluable candidates | Coverage shortage | Forbidden transitions | Skill violations | Extra working assignments |",
              "| --- | --- | --- | --- | --- | --- |"]
    for name, s in groups.items():
        h = s["hard_violation_units"]
        lines.append(f"| {name} | {s['evaluated_candidate_trials']} | {h.get('minimum_coverage', 0)} | "
                     f"{h.get('shift_succession', 0)} | {h.get('required_skill', 0)} | {h.get('single_assignment', 0)} |")
    lines += ["", "Violation totals cover evaluable candidates only; unavailable counts are not zero. "
              "Categories can overlap. These totals should not replace all-attempt validity rates.", "",
              "### Infeasibility claims", ""]
    for name, counts in summary["infeasibility_claims"].items():
        lines.append(f"- {name}: {counts['false_on_a_feasible']} false on A-validated feasible inputs; "
                     f"{counts['agrees_with_a_proof']} agree with an A infeasibility proof; "
                     f"{counts['unverified']} unverified because A did not resolve feasibility.")
    lines += ["", f"This purposive {len(plan['cases'])}-case subset is not representative of every INRC2 instance. "
              "Nurse count varies alongside skill/shift mix, so differences across sizes are descriptive. "
              "History contrasts hold weekly demand fixed; demand contrasts hold history fixed, but weekly "
              "demand distributions change as well as their totals. Four/eight-week labels are source metadata: "
              "no multiweek progression is tested. No optimality, monetary-cost or demographic-fairness claim is made. "
              "Raw traces remain under ignored outputs; portable aggregate metrics and all-trial records accompany this report.", ""]
    return "\n".join(lines)


def publish_snapshot(directory, plan, rows, started):
    rows = sorted(rows, key=lambda r: (r["case_id"], r["variant"], r["repetition"]))
    planned = len(plan["cases"]) * (1 + len(VARIANTS) * plan["repetitions"])
    classical = {r["case_id"]: r for r in rows if r["variant"] == "classical"}
    claims = {}
    for variant in VARIANTS:
        counts = dict(false_on_a_feasible=0, agrees_with_a_proof=0, unverified=0)
        for r in rows:
            if r["variant"] != variant or r["status"] != "infeasible_claim":
                continue
            a = classical.get(r["case_id"], {})
            key = "false_on_a_feasible" if a.get("hard_valid") else "agrees_with_a_proof" if a.get("infeasibility_proven") else "unverified"
            counts[key] += 1
        claims[variant] = counts
    summary = {"name": plan["name"], "mode": plan["mode"], "prompt_version": plan["prompt_version"],
               "complete": len(rows) == planned, "planned_trials": planned,
               "completed_trials": len(rows), "api_calls": sum(r["api_call_count"] for r in rows),
               "max_planned_api_calls": len(plan["cases"]) * plan["repetitions"] * 8,
               "current_process_wall_seconds": time.perf_counter() - started,
               "execution": json.loads((directory / "manifest.json").read_text()),
               "run_id": directory.name,
               "hardware": {"architecture": platform.machine(), "platform": platform.system(),
                            "python": sys.version.split()[0]},
               "cases": plan["cases"], "variants": aggregate(rows),
               "infeasibility_claims": claims, "rows": rows}
    save_json(directory / "summary.json", summary)
    report = ROOT / "reports" / plan["name"]
    save_json(report.with_suffix(".json"), summary)
    fields = ["case_id", "nurses", "variant", "repetition", "status", "schema_valid", "hard_valid",
              "runtime_seconds", "latency_seconds", "api_call_count", "total_tokens", "usage_incomplete",
              "infeasibility_proven", "initial_hard_valid", "revision_outcome", "returned_model", "artifact_dir"]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    report.with_suffix(".csv").write_text(stream.getvalue())
    report.with_suffix(".md").write_text(report_text(summary, plan))
    if summary["complete"]:
        readme = ROOT / "README.md"
        text = readme.read_text()
        begin, end = "<!-- parity-results:start -->", "<!-- parity-results:end -->"
        if begin not in text or end not in text:
            raise ValueError("README comparison markers missing")
        section = ["", "## Matched results", "",
                   f"Same {len(plan['cases'])} inputs and four hard constraints; 1 classical run and "
                   f"{plan['repetitions']} repetitions per LLM variant per case. Both seek feasibility only. "
                   + protocol_text(plan, summary['execution']['config'])
                   + f"See [case selection](docs/benchmark.md) and [full results](reports/{plan['name']}.md).", "",
                   "| Method | Cases tested | Hard-valid trials / attempted | Mean runtime (s) | API calls |",
                   "| --- | --- | --- | --- | --- |"]
        for name, stats in summary["variants"].items():
            duration = stats["mean_runtime_seconds"]
            section.append(f"| {name} | {stats['cases_tested']} | {stats['hard_valid']}/{stats['trials']} | "
                           f"{duration:.3f} | {stats['api_calls']} |" if duration is not None else
                           f"| {name} | {stats['cases_tested']} | {stats['hard_valid']}/{stats['trials']} | unavailable | {stats['api_calls']} |")
        section += ["", "All attempts remain in the denominator. Runtime includes local processing; LLM runtime also includes "
                    "remote service and network time. The purposive sample supports descriptive comparisons, not a causal claim "
                    "about nurse count or a full-horizon INRC2 result. Soft scores are not optimization targets.", ""]
        left, rest = text.split(begin, 1)
        _, right = rest.split(end, 1)
        readme.write_text(left + begin + "\n".join(section) + end + right)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "config/experiments/parity_v1.json")
    parser.add_argument("--config", type=Path, default=ROOT / "config/llm.json")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args()
    plan, cases = load_plan(args.plan)
    if args.list_only:
        for case in plan["cases"]:
            print(case["id"], case["role"], case["minimum_staff_days"])
        print(f"{len(cases)} classical runs; {len(cases)*4*plan['repetitions']} LLM trials; up to {len(cases)*8*plan['repetitions']} model calls")
        return
    config = json.loads(args.config.read_text())
    safe_config = {k: config[k] for k in ["provider", "base_url", "model", "api_style", "reasoning_effort"] if k in config}
    frozen = {"plan": plan, "config": safe_config, "source_hashes": source_hashes()}
    if args.resume:
        directory = args.resume
        if json.loads((directory / "manifest.json").read_text()) != frozen:
            raise ValueError("Plan, inputs, source or model settings differ; cannot resume")
    else:
        directory = ROOT / "outputs/comparison" / (plan["name"] + "_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        directory.mkdir(parents=True, exist_ok=False)
        save_json(directory / "manifest.json", frozen)
        for name in frozen["source_hashes"]:
            snapshot = directory / "source_snapshot" / name
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes((ROOT / name).read_bytes())
    print(json.dumps({"run_dir": str(directory), "mode": plan["mode"],
                      "max_calls": len(cases) * 8 * plan["repetitions"]}), flush=True)
    started = time.perf_counter()
    rows = []
    # A is deterministic; evaluate it once per input before scheduling remote calls.
    for case in plan["cases"]:
        row = classical_trial(case, cases[case["id"]], directory, plan["time_limit_seconds"])
        rows.append(row)
        print(json.dumps({"classical": case["id"], "status": row["status"], "valid": row["hard_valid"], "seconds": row["runtime_seconds"]}), flush=True)
    publish_snapshot(directory, plan, rows, started)
    jobs = [(case, v, r) for case in plan["cases"] for v in plan["variants"] for r in range(1, plan["repetitions"] + 1)]
    random.Random(plan["scheduling_seed"]).shuffle(jobs)
    with ThreadPoolExecutor(max_workers=plan["workers"]) as pool:
        futures = [pool.submit(llm_trial, case, cases[case["id"]], v, r, config, plan, directory)
                   for case, v, r in jobs]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            summary = publish_snapshot(directory, plan, rows, started)
            print(json.dumps({"completed": len(rows), "planned": summary["planned_trials"],
                              "calls": summary["api_calls"], "case": row["case_id"],
                              "variant": row["variant"], "status": row["status"],
                              "valid": row["hard_valid"]}), flush=True)
    print(json.dumps({"complete": True, "api_calls": summary["api_calls"], "variants": summary["variants"]}), flush=True)


if __name__ == "__main__":
    main()
