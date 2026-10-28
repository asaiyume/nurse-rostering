"""Export one preselected case's complete returned outputs, prompts and thinking text."""

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rostering.evaluate import evaluate
from rostering.llm.api import completed, output_text
from scripts.run_comparison import protocol_text


def export(directory, case_id="n050w4_h2_wd6", repetition=1):
    summary = json.loads((directory / "summary.json").read_text())
    plan = summary["execution"]["plan"]
    case = next(c for c in plan["cases"] if c["id"] == case_id)
    instance = json.loads((ROOT / case["instance"]).read_text())
    files = {"instance.json": (ROOT / case["instance"]).read_bytes()}
    rows, reasoning_totals = [], {}
    for variant in ["classical", *plan["variants"]]:
        r = next(r for r in summary["rows"] if r["case_id"] == case_id and r["variant"] == variant
                 and r["repetition"] == (1 if variant == "classical" else repetition))
        source = directory / r["artifact_dir"]
        for name in ["metadata.json", "evaluation.json", "roster.json"]:
            if (source / name).exists():
                files[f"{variant}/{name}"] = (source / name).read_bytes()
        stages = sorted((source / "stages").iterdir()) if (source / "stages").exists() else []
        thinking_tokens = 0
        reasoning_usage_reports = 0
        for stage in stages:
            for name in ["request.json", "response.json", "output.txt", "evaluation.json"]:
                if (stage / name).exists():
                    files[f"{variant}/{stage.name}/{name}"] = (stage / name).read_bytes()
            request = json.loads((stage / "request.json").read_text())
            prompt = request["input"] if summary["execution"]["config"]["api_style"] == "responses" else request["messages"][0]["content"]
            files[f"{variant}/{stage.name}/full-prompt.txt"] = prompt.encode()
            if (stage / "response.json").exists():
                response = json.loads((stage / "response.json").read_text())
                message = response.get("choices", [{}])[0].get("message", {})
                thinking = message.get("reasoning") or message.get("reasoning_content")
                if thinking:
                    files[f"{variant}/{stage.name}/thinking.txt"] = thinking.encode()
                reported = response.get("usage", {}).get("completion_tokens_details", {}).get("reasoning_tokens")
                if reported is not None:
                    reasoning_usage_reports += 1
                    thinking_tokens += reported
                if stage.name == "generation":
                    try:
                        initial_roster = json.loads(output_text(response))
                    except ValueError:
                        initial_roster = None
                    initial = evaluate(instance, initial_roster)
                    if not completed(response):
                        initial.update(hard_valid=False, soft_score=None)
                    files[f"{variant}/generation-evaluation-replayed.json"] = (json.dumps(initial, indent=2) + "\n").encode()
        reasoning_totals[variant] = thinking_tokens if reasoning_usage_reports else None
        initial = json.loads(files[f"{variant}/generation-evaluation-replayed.json"]) if variant != "classical" and f"{variant}/generation-evaluation-replayed.json" in files else None
        rows.append((variant, r, initial))
        if (source / "roster.json").exists():
            roster = json.loads((source / "roster.json").read_text())
            groups = defaultdict(list)
            for row in roster.get("roster", []):
                groups[row["nurse_id"], row["day"]].append(row)
            text = [f"# Full {variant} final roster", "",
                    "Each working cell is shift/skill. Missing and ambiguous records are shown explicitly; "
                    "the JSON remains the complete canonical output.", "",
                    "| Nurse | Mon | Tue | Wed | Thu | Fri | Sat | Sun |",
                    "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for nurse in instance["nurses"]:
                values = []
                for day in instance["days"]:
                    group = groups[nurse["id"], day]
                    if len(group) != 1:
                        values.append("Missing" if not group else "Ambiguous")
                    else:
                        row = group[0]
                        values.append("Off" if row["shift"] == "Off" else f"{row['shift']}/{row['skill']}")
                text.append("| " + nurse["id"] + " | " + " | ".join(values) + " |")
            files[f"{variant}/full-roster.md"] = ("\n".join(text) + "\n").encode()
    lines = [f"# Full high effort {case['nurses']} nurse example", "",
             f"Case `{case_id}`, repetition {repetition}: {case['nurses']} nurses, {len(instance['days'])} days, "
             f"{len(instance['shift_types'])} working shifts and {len(instance['skills'])} skill types, "
             f"requiring {case['minimum_staff_days']} minimum nurse-days. "
             "This larger history-contrast case and repetition were selected before the final results, "
             "not because a variant succeeded or failed. It is not claimed to be the hardest case.", "",
             protocol_text(plan, summary["execution"]["config"]) +
             "There is no soft objective. The classical witness uses the same input and hard constraints.", "",
             "| Method | Initial shortage / illegal transitions | Final shortage / illegal transitions | Final hard-valid | Status | Reported thinking tokens |",
             "| --- | --- | --- | --- | --- | --- |"]
    for variant, row, initial in rows:
        first = (initial or {}).get("hard_violation_counts")
        final = row["hard_violation_counts"]
        counts = lambda x: "unavailable" if x is None else f"{x.get('minimum_coverage', 0)} / {x.get('shift_succession', 0)}"
        thinking = "not applicable" if variant == "classical" else "unavailable" if reasoning_totals[variant] is None else format(reasoning_totals[variant], ",")
        lines.append(f"| {variant} | {counts(first)} | {counts(final)} | {row['hard_valid']} | {row['status']} | {thinking} |")
    lines += ["", "## Full files", "",
              "- `instance.json`: complete shared input, including initial history and demand.",
              "- Each method directory: final roster, complete independent evaluator report, metadata and readable full roster grid when available.",
              "- Each model stage: exact request, full assembled prompt, complete provider response, unabridged answer/audit, and `thinking.txt` when the provider exposed reasoning text.",
              "- `generation-evaluation-replayed.json`: original candidate independently evaluated after generation/audit/revision had finished; this was not supplied to the model.", "",
              "Thinking text is the external model's returned reasoning field, not a reconstructed explanation. "
              "A separate audit is an explicit additional model output. The stage response preserves usage counters "
              "and termination status. If a provider/network failure prevented a response, no missing reasoning "
              "or answer is invented. Baseline and critique are separate generations; assess revision effects "
              "by comparing original and final outputs within each critique/combined trial.", "",
              "This export adds no API calls. The full benchmark includes all cases and repetitions; "
              "this one example does not estimate success rates.", ""]
    lines += ["## Direct links", "", "- **classical:** [roster](classical/roster.json) · [evaluation](classical/evaluation.json)"]
    for variant in plan["variants"]:
        links = [f"[metadata]({variant}/metadata.json)"]
        for stage in ["generation", "critique", "revision"]:
            for name, label in [("full-prompt.txt", "prompt"), ("thinking.txt", "thinking"), ("output.txt", "answer")]:
                path = f"{variant}/{stage}/{name}"
                if path in files:
                    links.append(f"[{stage} {label}]({path})")
        path = f"{variant}/evaluation.json"
        if path in files:
            links.append(f"[evaluation]({path})")
        lines.append("- **" + variant + ":** " + " · ".join(links))
    lines.append("")
    files["README.md"] = ("\n".join(lines)).encode()
    known = [os.environ[k].encode() for k in ["SOCLAAS_API_KEY", "OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"]
             if len(os.environ.get(k, "")) >= 12]
    patterns = [rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b",
                rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}", rb"/Users/[^\s\"\x27]+"]
    for name, data in files.items():
        if any(key in data for key in known) or any(re.search(p, data) for p in patterns):
            raise ValueError("Sensitive-content match in " + name)
    target = ROOT / "reports/examples" / case_id
    for name, data in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    archive = ROOT / f"outputs/exports/{case_id}-r{repetition}-example.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            z.writestr(case_id + "/" + name, data)
    return {"example": str(target), "archive": str(archive), "files": len(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--case", default="n050w4_h2_wd6")
    parser.add_argument("--repetition", type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(export(args.run_dir, args.case, args.repetition), indent=2))


if __name__ == "__main__":
    main()
