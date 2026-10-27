"""Replay a completed comparison from local traces without making API calls."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import runpy
import sys

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rostering.evaluate import evaluate
from rostering.llm.api import completed, output_text
from rostering.llm.pipeline import build_request


def verify(directory, allow_partial=False):
    manifest = json.loads((directory / "manifest.json").read_text())
    summary = json.loads((directory / "summary.json").read_text())
    if not summary["complete"] and not allow_partial:
        raise ValueError("Comparison is not complete")
    plan = manifest["plan"]
    for name, expected_hash in manifest["source_hashes"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected_hash:
            raise ValueError("Changed benchmark source: " + name)
    cases = {c["id"]: c for c in plan["cases"]}
    inputs = {}
    for name, case in cases.items():
        raw = (ROOT / case["instance"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != case["sha256"]:
            raise ValueError("Changed source input: " + name)
        inputs[name] = json.loads(raw)
    seen, counts = set(), {}
    constrained, conforming, returned_calls = 0, 0, 0
    reasoning_tokens, reasoning_stages = Counter(), Counter()
    returned_models = Counter()
    valid_initials, valid_initials_in_failed_trials = Counter(), Counter()
    incomplete_audits, completed_revisions = Counter(), Counter()
    api_failure_stages = Counter()
    failure_examples = []
    for row in summary["rows"]:
        key = row["case_id"], row["variant"], row["repetition"]
        if key in seen:
            raise ValueError("Duplicate attempt")
        seen.add(key)
        case = cases[row["case_id"]]
        instance = inputs[row["case_id"]]
        run = directory / row["artifact_dir"]
        if not run.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Artifact path escapes the comparison")
        metadata = json.loads((run / "metadata.json").read_text())
        if metadata["mode"] != "hard_constraints_only":
            raise ValueError("Mismatched task scope")
        if row["variant"] == "classical" and (metadata["time_limit_seconds"] is not None or metadata["soft_method"] is not None):
            raise ValueError("Classical timeout or objective differs from the plan")
        if row["variant"] != "classical":
            if row["status"] == "api_error" and metadata["stages"]:
                api_failure_stages[row["variant"] + ":" + metadata["stages"][-1]["name"]] += 1
            if metadata.get("critique_incomplete"):
                incomplete_audits[row["variant"]] += 1
            completed_revisions[row["variant"]] += sum(s["name"] == "revision" and s["response_status"] == "stop" for s in metadata["stages"])
            if metadata["timeout_seconds"] != plan["time_limit_seconds"] or metadata["total_timeout_seconds"] != plan["time_limit_seconds"]:
                raise ValueError("Trial deadline settings differ from the frozen plan")
            if json.loads((run / "instance.json").read_text()) != instance:
                raise ValueError("A and B used different inputs")
            for stage in metadata["stages"]:
                request = json.loads((run / "stages" / stage["name"] / "request.json").read_text())
                if stage["name"] == "generation":
                    _, expected_request = build_request(instance, manifest["config"], plan["max_output_tokens"], row["variant"])
                    if request != expected_request:
                        raise ValueError("Generation request differs from the frozen setup")
                if "tools" in request or request.get("reasoning_effort") != manifest["config"]["reasoning_effort"]:
                    raise ValueError("Model settings or tool access changed")
                response_path = run / "stages" / stage["name"] / "response.json"
                if response_path.exists():
                    returned_calls += 1
                    response = json.loads(response_path.read_text())
                    returned_models[response.get("model", "unknown")] += 1
                    message = response.get("choices", [{}])[0].get("message", {})
                    reasoning = message.get("reasoning") or message.get("reasoning_content")
                    if reasoning:
                        reasoning_stages[row["variant"]] += 1
                    reasoning_tokens[row["variant"]] += (response.get("usage", {})
                        .get("completion_tokens_details", {}).get("reasoning_tokens") or 0)
                    schema = request.get("response_format", {}).get("json_schema", {}).get("schema")
                    if schema:
                        constrained += 1
                        try:
                            value = json.loads(output_text(response))
                        except ValueError:
                            continue
                        if completed(response) and not list(Draft202012Validator(schema).iter_errors(value)):
                            conforming += 1
            actual_calls = len(list((run / "stages").glob("*/request.json")))
            if actual_calls != row["api_call_count"] or metadata["api_call_count"] != row["api_call_count"]:
                raise ValueError("Model call accounting differs")
        evaluation_path = run / "evaluation.json"
        if evaluation_path.exists():
            saved = json.loads(evaluation_path.read_text())
            roster_path = run / "roster.json"
            roster = json.loads(roster_path.read_text()) if roster_path.exists() else None
            checked = evaluate(instance, roster)
            if row["status"] == "incomplete_response":
                checked.update(hard_valid=False, soft_score=None)
            for field in ["schema_valid", "hard_valid", "hard_violation_counts", "soft_score"]:
                if saved[field] != checked[field]:
                    raise ValueError(f"Evaluation differs for {key}: {field}")
            if row["hard_valid"] != saved["hard_valid"] or row["schema_valid"] != saved["schema_valid"]:
                raise ValueError("Summary validity differs from evaluator")
            if row["status"] == "invalid_roster" and checked["schema_valid"] and checked["hard_violations"] and len(failure_examples) < 3:
                failure_examples.append({"case_id": row["case_id"], "variant": row["variant"],
                                         "repetition": row["repetition"],
                                         "schema_valid": True, "roster_complete": checked["roster_complete"],
                                         "violations": checked["hard_violations"][:5]})
        elif row["hard_valid"]:
            raise ValueError("Valid claim has no independent evaluation")
        if row["variant"] != "classical":
            initial_path = run / "stages/generation/evaluation.json"
            if (run / "stages/generation/response.json").exists():
                response = json.loads((run / "stages/generation/response.json").read_text())
                try:
                    original = json.loads(output_text(response))
                except ValueError:
                    original = None
                original_checked = evaluate(instance, original)
                if not completed(response):
                    original_checked.update(hard_valid=False, soft_score=None)
                valid_initials[row["variant"]] += original_checked["hard_valid"]
                if original_checked["hard_valid"] and row["status"] == "api_error":
                    valid_initials_in_failed_trials[row["variant"]] += 1
                if initial_path.exists():
                    initial_saved = json.loads(initial_path.read_text())
                    for field in ["schema_valid", "hard_valid", "hard_violation_counts", "soft_score"]:
                        if original_checked[field] != initial_saved[field]:
                            raise ValueError("Initial candidate evaluation differs")
            if (metadata.get("usage") or {}).get("total_tokens") != row["total_tokens"]:
                raise ValueError("Token totals differ")
        counts[row["variant"]] = counts.get(row["variant"], 0) + 1
    expected = {(c, v, r) for c in cases for v in plan["variants"] for r in range(1, plan["repetitions"] + 1)}
    expected |= {(c, "classical", 1) for c in cases}
    if (summary["complete"] and seen != expected) or not seen <= expected:
        raise ValueError("Missing or unexpected attempts")
    total_calls = sum(r["api_call_count"] for r in summary["rows"])
    if total_calls != summary["api_calls"] or total_calls > summary["max_planned_api_calls"]:
        raise ValueError("Total call budget differs")
    aggregate = runpy.run_path(str(ROOT / "scripts/run_comparison.py"))["aggregate"]
    if aggregate(summary["rows"]) != summary["variants"]:
        raise ValueError("Aggregate metrics differ")
    result = {"complete": summary["complete"], "verified_trials": len(seen), "trials_by_method": counts,
              "api_calls": total_calls, "returned_api_calls": returned_calls,
              "constrained_stages": constrained, "complete_schema_conforming_stages": conforming,
              "requested_reasoning_effort": manifest["config"]["reasoning_effort"],
              "reported_reasoning_tokens_by_variant": dict(reasoning_tokens),
              "stages_with_exposed_reasoning_by_variant": dict(reasoning_stages),
              "returned_models": dict(returned_models),
              "valid_initial_candidates_by_variant": dict(valid_initials),
              "valid_initial_candidates_in_api_failed_trials": dict(valid_initials_in_failed_trials),
              "incomplete_audit_trials_by_variant": dict(incomplete_audits),
              "completed_revision_stages_by_variant": dict(completed_revisions),
              "api_failure_stages": dict(api_failure_stages),
              "schema_valid_scheduling_failure_examples": failure_examples,
              "a_b_inputs_match": True, "independent_evaluations_match": True}
    if not summary["complete"]:
        return result
    report = ROOT / "reports" / (plan["name"] + "_verification.json")
    report.write_text(json.dumps(result, indent=2) + "\n")
    report_md = ROOT / "reports" / (plan["name"] + ".md")
    marker = "<!-- verified-analysis:start -->"
    text = report_md.read_text().split(marker, 1)[0].rstrip()
    lines = ["", "", marker, "## Replay and reasoning evidence", "",
             f"All {len(seen)} saved trials were replayed offline with matching inputs and independent evaluations. "
             f"The gateway returned {returned_calls} responses from {total_calls} recorded calls. "
             f"{conforming}/{constrained} constrained stages returned complete JSON matching their generation schema. "
             "This does not establish full output-schema or scheduling correctness.", "",
             "| Variant | Valid initial candidates | Final hard-valid | API failures | Reported reasoning tokens |",
             "| --- | --- | --- | --- | --- |"]
    for variant in plan["variants"]:
        group = summary["variants"][variant]
        lines.append(f"| {variant} | {valid_initials[variant]} | {group['hard_valid']} | "
                     f"{group['status_counts'].get('api_error', 0)} | {reasoning_tokens[variant]:,} |")
    lines += ["", "API failures are unresolved "
              "attempts, not demonstrated scheduling violations. Initial valid rosters in API-failed review trials are "
              "reported separately: the pipeline does not silently accept an initial roster after a failed API stage. "
              "The final protocol has no imposed deadline; server/network failures remain possible.",
              "", "Gateway load, caching and network time were not controlled. Reported reasoning tokens are taken from "
              "the API usage records; exposed thinking text remains in the raw response traces. Token totals "
              "sum available usage only: API-failed stages can have unreported usage, so these totals are not "
              "complete monetary-cost estimates.", ""]
    lines += ["### Audit and revision outcomes", "",
              "| Variant | Completed revisions | Invalid-to-valid repairs | Valid-to-invalid final outputs | Incomplete audits retaining the original |",
              "| --- | --- | --- | --- | --- |"]
    for variant in ["critique", "combined"]:
        outcomes = summary["variants"][variant]["revision_outcomes"]
        lines.append(f"| {variant} | {completed_revisions[variant]} | {outcomes.get('repaired', 0)} | "
                     f"{outcomes.get('regressed', 0)} | {incomplete_audits[variant]} |")
    lines += ["", "A valid-to-invalid final output includes incomplete or malformed revision output, "
              "not only newly introduced scheduling violations. An incomplete audit can retain a valid original "
              "without completing a revision; that is not counted as a successful repair.", ""]
    if failure_examples:
        lines += ["### Schema validity does not establish feasibility", ""]
        for example in failure_examples:
            lines.append(f"- `{example['case_id']}`, {example['variant']} repetition {example['repetition']}: "
                         "the output passed its JSON schema but failed independent scheduling checks. "
                         + "; ".join(f"{v.get('day', '')} {v.get('shift', '')} {v.get('skill', '')}: "
                                     f"{v['type']}, required {v.get('required', '—')}, assigned {v.get('assigned', '—')}"
                                     for v in example["violations"]) + ".")
        lines.append("")
    report_md.write_text(text + "\n".join(lines))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--allow-partial", action="store_true", help="Read-only check of currently completed trials")
    args = parser.parse_args()
    print(json.dumps(verify(args.run_dir, args.allow_partial), indent=2))


if __name__ == "__main__":
    main()
