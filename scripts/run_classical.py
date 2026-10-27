"""Run classical cases from the smallest nurse-count scenario folders.

Default: 10 folders, 30 cases per folder, 4 workers, 420 seconds per case.
Selects inputs, runs the solver, independently evaluates rosters and saves
per-case results plus overall CSV/JSON summaries. Folders run in sequence;
cases within a folder can run concurrently. Previous outputs are preserved.
--list-only never creates outputs or runs cases.
"""

import argparse
import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import math
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rostering.classical.__main__ import solve
from rostering.evaluate import evaluate
from rostering.io import write_json


def run_case(path, run_dir, time_limit):
    """Worker entry point; no dependency on another runner script."""
    case = f"{path.parent.name}_{path.stem}"
    folder = run_dir / path.parent.name / case
    row = dict(case=case, status="error", hard_valid=False, soft_cost=None,
               runtime_seconds=None, timed_out=None, optimality_proven=False,
               infeasibility_proven=False, nodes=None, error="")
    try:
        instance = json.loads(path.read_text(encoding="utf-8"))
        roster, metadata = solve(instance, time_limit=time_limit)
        report = evaluate(instance, roster)
        write_json(folder / "roster.json", roster)
        write_json(folder / "metadata.json", metadata)
        write_json(folder / "evaluation.json", report)
        row.update(status=roster["status"], hard_valid=report["hard_valid"],
                   soft_cost=(report["soft_score"]["partial_total"]
                              if report["soft_score"] is not None else None),
                   runtime_seconds=round(metadata["runtime_seconds"], 6),
                   timed_out=metadata["timed_out"],
                   optimality_proven=metadata["optimality_proven"],
                   infeasibility_proven=metadata["infeasibility_proven"],
                   nodes=metadata["statistics"]["nodes"])
    except Exception as error:
        # A malformed instance or failed case must not discard other results.
        row["error"] = f"{type(error).__name__}: {error}"
    return row


def save_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["case"]))


def print_summary(run_dir, rows, expected_cases=()):
    timed = []
    for row in rows:
        try:
            seconds = float(row.get("runtime_seconds", ""))
        except (TypeError, ValueError):
            continue
        if math.isfinite(seconds) and seconds >= 0:
            timed.append((seconds, row["case"]))
    print(f"\nTotal test cases tested: {len(rows)}", flush=True)
    correct = [row for row in rows if row.get("status") == "candidate"
               and row.get("hard_valid") is True]
    failed = [row for row in rows if row not in correct]
    percentage = f" ({100 * len(correct) / len(rows):.2f}%)" if rows else ""
    print(f"Correctness (hard constraints): {len(correct)}/{len(rows)}{percentage}", flush=True)
    print("Failed / unresolved test cases:", flush=True)
    if not failed:
        print("  None" if rows else "  No completed results", flush=True)
    for row in failed:
        reason = row.get("error") or row.get("status") or "invalid output"
        print(f"  {row['case']}: {reason}", flush=True)
    completed = {row["case"] for row in rows}
    missing = sorted(set(expected_cases) - completed)
    if missing:
        print(f"Not completed / no result: {len(missing)}", flush=True)
        for case in missing:
            print(f"  {case}", flush=True)
    if timed:
        shortest, longest = min(timed), max(timed)
        print(f"Shortest time taken: {shortest[0]:.6f} seconds ({shortest[1]})", flush=True)
        print(f"Longest time taken: {longest[0]:.6f} seconds ({longest[1]})", flush=True)
    else:
        print("Shortest time taken: N/A", flush=True)
        print("Longest time taken: N/A", flush=True)
    if len(timed) != len(rows):
        print(f"Cases without a recorded runtime: {len(rows) - len(timed)}", flush=True)
    print("Times include completed and timed-out cases with recorded runtimes.", flush=True)
    print(f"Results: {run_dir}", flush=True)
    summary = dict(total_tested=len(rows), correct=len(correct),
                   failed_or_unresolved=failed, not_completed=missing,
                   shortest_seconds=min(timed)[0] if timed else None,
                   longest_seconds=max(timed)[0] if timed else None)
    write_json(run_dir / "summary.json", summary)
    return summary


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folders", type=positive_int, default=10)
    parser.add_argument("--cases-per-folder", type=positive_int, default=30)
    parser.add_argument("--workers", type=positive_int, default=4)
    parser.add_argument("--time-limit", type=float, default=420)
    parser.add_argument("--list-only", action="store_true",
                        help="Show selected folders without running any cases")
    args = parser.parse_args()
    if not 0 < args.time_limit < float("inf"):
        parser.error("--time-limit must be finite and positive")

    scenarios = []
    for path in (ROOT / "converted").iterdir():
        match = re.fullmatch(r"n(\d+)w(\d+)", path.name)
        if path.is_dir() and match and any(path.glob("*.json")):
            scenarios.append((int(match[1]), int(match[2]), path))
    scenarios.sort(key=lambda item: (item[0], item[1], item[2].name))
    selected = scenarios[:args.folders]
    if not selected:
        parser.error("No scenario folders found in converted/")

    total = 0
    for nurses, horizon, path in selected:
        count = min(args.cases_per_folder, len(list(path.glob("*.json"))))
        total += count
        print(f"{path.name}: {nurses} nurses, {horizon}-week horizon, {count} cases",
              flush=True)
    print(f"Total: {len(selected)} folders, {total} cases.", flush=True)
    if args.list_only:
        return 0

    cases_by_folder = [(path, sorted(path.glob("*.json"))[:args.cases_per_folder])
                       for _, _, path in selected]
    expected_cases = [f"{path.name}_{case.stem}" for path, cases in cases_by_folder
                      for case in cases]
    # Isolate this invocation so totals never include previous runs.
    run_dir = ROOT / "outputs/classical/runs" / (
        datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "plan.json", dict(
        instances=[str(case.resolve()) for _, cases in cases_by_folder for case in cases],
        workers=args.workers, time_limit_seconds=args.time_limit))
    print(f"Results: {run_dir}", flush=True)
    rows = []

    def record(row, folder_rows, path):
        rows.append(row)
        folder_rows.append(row)
        print(f"[{len(rows)}/{total}] {row['case']}: {row['status']}, "
              f"valid={row['hard_valid']}, soft={row['soft_cost']}, "
              f"seconds={row['runtime_seconds']}"
              + (f", error={row['error']}" if row['error'] else ""), flush=True)
        # Save completed results immediately, including before interruption.
        save_csv(run_dir / "summary.csv", rows)
        save_csv(run_dir / path.name / "summary.csv", folder_rows)

    try:
        for position, (path, cases) in enumerate(cases_by_folder, start=1):
            print(f"\nFolder {position}/{len(selected)}: {path.name}", flush=True)
            folder_rows = []
            if args.workers == 1:
                for case in cases:
                    record(run_case(case, run_dir, args.time_limit), folder_rows, path)
            else:
                with ProcessPoolExecutor(max_workers=args.workers) as pool:
                    futures = {pool.submit(run_case, case, run_dir, args.time_limit): case
                               for case in cases}
                    for future in as_completed(futures):
                        try:
                            row = future.result()
                        except Exception as error:
                            case = futures[future]
                            row = dict(case=f"{case.parent.name}_{case.stem}", status="error",
                                       hard_valid=False, soft_cost=None, runtime_seconds=None,
                                       timed_out=None, optimality_proven=False,
                                       infeasibility_proven=False, nodes=None,
                                       error=f"{type(error).__name__}: {error}")
                        record(row, folder_rows, path)
            print(f"Finished {path.name}: "
                  f"{sum(row['hard_valid'] for row in folder_rows)}/{len(folder_rows)} valid",
                  flush=True)
    except KeyboardInterrupt:
        print("\nInterrupted. Completed batch results remain saved.", file=sys.stderr)
        return 130
    finally:
        print_summary(run_dir, rows, expected_cases)

    if any(row["status"] == "error" for row in rows):
        return 1
    return 0 if len(rows) == total and all(row["hard_valid"] for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
