"""Merge matched pilot suites and re-evaluate saved outputs without model calls."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rostering.llm.batch import aggregate
from rostering.llm.api import output_text
from rostering.evaluate import evaluate
from rostering.io import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--safeguards", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "reports/pilot_chat_v1")
    args = parser.parse_args()
    baseline_manifest = json.loads((args.baseline / "manifest.json").read_text())
    safeguard_manifest = json.loads((args.safeguards / "manifest.json").read_text())
    if baseline_manifest["config"] != safeguard_manifest["config"] or baseline_manifest["prompt_sha256"] != safeguard_manifest["prompt_sha256"]:
        raise ValueError("Configuration or generation prompt differs between suites")
    left = {c["id"]: c["baseline_request_sha256"] for c in baseline_manifest["cases"]}
    right = {c["id"]: c["baseline_request_sha256"] for c in safeguard_manifest["cases"]}
    if left != right:
        raise ValueError("Case inputs or baseline request settings differ")
    for key in ["repetitions", "max_output_tokens", "timeout_seconds", "workers"]:
        if baseline_manifest["plan"][key] != safeguard_manifest["plan"][key]:
            raise ValueError(f"Mismatched suite setting: {key}")
    rows = json.loads((args.baseline / "results.json").read_text()) + json.loads((args.safeguards / "results.json").read_text())
    seen = set()
    errors = Counter()
    exemplars = []
    constrained_stages = 0
    constrained_failures = []
    infeasibility_claims = []
    for row in rows:
        key = (row["case_id"], row["variant"], row["repetition"])
        if key in seen:
            raise ValueError("Duplicate trial in merged results")
        seen.add(key)
        directory = Path(row["run_dir"])
        evaluation_path = directory / "evaluation.json"
        if not evaluation_path.exists():
            continue
        instance = json.loads((directory / "instance.json").read_text())
        saved = json.loads(evaluation_path.read_text())
        output = json.loads((directory / "roster.json").read_text()) if (directory / "roster.json").exists() else None
        checked = evaluate(instance, output)
        # A truncated service response is never accepted, even if partial JSON parses.
        if row["status"] != "incomplete_response":
            for field in ["schema_valid", "hard_valid", "hard_violation_counts", "soft_score"]:
                if saved[field] != checked[field]:
                    raise ValueError(f"Saved evaluator result differs for {key}: {field}")
        for issue in saved["output_issues"]:
            errors[row["variant"] + ":" + issue["type"]] += 1
        initial_path = directory / "stages/generation/evaluation.json"
        initial = json.loads(initial_path.read_text()) if initial_path.exists() else {}
        row["initial_hard_valid"] = initial.get("hard_valid")
        metadata = json.loads((directory / "metadata.json").read_text())
        if isinstance(output, dict) and output.get("status") == "infeasible_claim":
            infeasibility_claims.append({"case_id": row["case_id"], "variant": row["variant"], "repetition": row["repetition"], "initial_feasibility_label": row["feasibility_label"], "schema_valid": saved["schema_valid"]})
        for stage_dir in (directory / "stages").iterdir():
            request = json.loads((stage_dir / "request.json").read_text())
            schema = request.get("response_format", {}).get("json_schema", {}).get("schema")
            if schema is None:
                continue
            response_path = stage_dir / "response.json"
            if not response_path.exists():
                continue
            constrained_stages += 1
            try:
                generated = json.loads(output_text(json.loads(response_path.read_text())))
                schema_failures = [str(e.message)[:200] for e in Draft202012Validator(schema).iter_errors(generated)]
            except ValueError:
                schema_failures = ["Invalid JSON"]
            if schema_failures:
                constrained_failures.append({"case_id": row["case_id"], "variant": row["variant"], "stage": stage_dir.name, "errors": schema_failures[:3]})
        if row["variant"] in {"critique", "combined"} and any(s["name"] == "revision" for s in metadata["stages"]) and initial:
            before, after = initial["hard_valid"], saved["hard_valid"]
            row["revision_outcome"] = "remained_valid" if before and after else "regressed" if before else "repaired" if after else "remained_invalid"
        if row["variant"] == "baseline" and row["feasibility_label"] == "known_feasible" and saved["hard_violations"] and len(exemplars) < 2:
            exemplars.append({"case_id": row["case_id"], "repetition": row["repetition"], "model_explanation": output.get("explanation") if isinstance(output, dict) else None, "violations": saved["hard_violations"][:3], "run_dir": row["run_dir"]})
    stats = aggregate(rows)
    repetitions = baseline_manifest["plan"]["repetitions"]
    expected = len(left) * repetitions
    if set(stats) != {"baseline", "structured", "critique", "combined"} or any(s["trials"] != expected for s in stats.values()):
        raise ValueError("Matched four-arm batch is incomplete")
    summary = {
        "total_trials": len(rows), "cases": baseline_manifest["cases"], "repetitions_per_case_per_variant": repetitions,
        "config": baseline_manifest["config"], "variants": stats, "output_issue_counts": dict(errors),
        "total_api_calls": sum(r["api_call_count"] for r in rows), "exemplars": exemplars,
        "generation_schema_conformance": {"checked_stages": constrained_stages, "conforming_stages": constrained_stages - len(constrained_failures), "failures": constrained_failures},
        "infeasibility_claims": infeasibility_claims,
        "baseline_suite": str(args.baseline), "safeguard_suite": str(args.safeguards),
        "limitations": ["Pilot-only observations on five cases, not a held-out final benchmark.", "Variants ran in separate batches; provider load and timing effects were not controlled.", "Only three weekly soft categories are scored; no optimum was established.", "No labelled infeasible cases; UNSAT-detection accuracy cannot be estimated.", "Gateway schema conformance is observed, but full strict enforcement is not established.", "A repaired roster is counted only when post-hoc independent evaluation marks the final output valid."],
    }
    write_json(args.out.with_suffix(".json"), summary)
    fields = ["case_id", "variant", "repetition", "status", "schema_valid", "hard_valid", "initial_hard_valid", "revision_outcome", "partial_soft_score", "latency_seconds", "total_tokens", "api_call_count", "run_dir"]
    with args.out.with_suffix(".csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["case_id"], r["variant"], r["repetition"])))
    text = ["# Repeated nurse rostering pilot", "", f"Five cases, {repetitions} independent repetitions per case and four variants: {len(rows)} trials and {summary['total_api_calls']} model calls. The earlier Responses development pilot and the two safeguard development checks are excluded.", "", "All variants use SoCLaas `x-test-2` via Chat Completions, with requested reasoning effort `none`, provider-default sampling, the same baseline prompt, and the same three-category pilot objective. Exact input/request fingerprints match across the two suites.", "", "## Results", "", "| Variant | Schema-valid / attempted | Hard-valid / attempted | Mean latency (s) | Reported tokens |", "| --- | --- | --- | --- | --- |"]
    for variant in ["baseline", "structured", "critique", "combined"]:
        s = stats[variant]
        text.append(f"| {variant} | {s['schema_valid']}/{s['trials']} | {s['hard_valid']}/{s['trials']} | {s['mean_latency_seconds']:.1f} | {s['total_tokens_reported']:,} |")
    text += ["", "Validity uses all attempted trials as the denominator. Empty responses, malformed/schema-invalid JSON, infeasibility claims and API errors are not silently removed. Hard validity also requires complete nurse-day output and no output-identity defects.", "", f"All constrained stages were also checked against the exact generation schema sent to the API: {constrained_stages - len(constrained_failures)}/{constrained_stages} conformed. This generation schema is a supported subset of the local contract: it cannot express the cross-field rule that unknown/infeasible status must have an empty roster. Conformance to the generation schema therefore does not establish full contract validity or scheduling correctness.", "", "## Hard violations", "", "| Variant | Missing coverage units | Forbidden transitions | Skill violations | Extra working assignments |", "| --- | --- | --- | --- | --- |"]
    for variant in ["baseline", "structured", "critique", "combined"]:
        h = stats[variant]["hard_violation_units_by_type"]
        text.append(f"| {variant} | {h.get('minimum_coverage', 0)} | {h.get('shift_succession', 0)} | {h.get('required_skill', 0)} | {h.get('single_assignment', 0)} |")
    text += ["", "Counts include only structurally evaluable candidates and can describe overlapping defects. They are not a total count of distinct mistakes; schema failures have null hard counts.", "", "## Audit and revision", ""]
    for variant in ["critique", "combined"]:
        outcome = stats[variant]["revision_outcomes"]
        text.append(f"- {variant}: {outcome['repaired']} invalid-to-valid repairs, {outcome['regressed']} valid-to-invalid regressions, {outcome['remained_valid']} remained valid, {outcome['remained_invalid']} remained invalid.")
    text += ["", "Original candidates and final revisions are both independently evaluated after all model calls. No evaluator counterexamples enter the model context.", "", "## Per-case validity", "", "| Case | Baseline | Structured | Critique | Combined |", "| --- | --- | --- | --- | --- |"]
    for case in sorted(left):
        values = [stats[v]["per_case"][case] for v in ["baseline", "structured", "critique", "combined"]]
        text.append("| " + case + " | " + " | ".join(f"{x['valid']}/{x['trials']}" for x in values) + " |")
    text += ["", "## Scope and interpretation", ""]
    text.extend("- " + item for item in summary["limitations"])
    text += ["", "The initial feasibility labels come from the pre-run manifest: H1/WD5 and H2/WD6 have validated supplied witnesses; the other cases started unlabelled. Any later valid generated roster provides a witness, but a failed attempt does not prove infeasibility.", "", "These are descriptive results. Both successful repairs and failures should be retained in the report. Structured output addresses representation and identifier risks; an LLM audit can still miscount staffing or introduce new violations.", "", "## Saved evidence", "", f"- Baseline suite: `{args.baseline}`", f"- Safeguard suite: `{args.safeguards}`", "- Machine-readable aggregate and all-trial CSV are beside this report.", "- Safeguard specification and API capability evidence: `docs/safeguards.md`.", ""]
    args.out.with_suffix(".md").write_text("\n".join(text))
    print(json.dumps({"report": str(args.out.with_suffix('.md')), "total_trials": len(rows), "variants": stats}, indent=2))


if __name__ == "__main__":
    main()
