"""Shared conversion/evaluation commands and the Solution B runner."""

import argparse
import json
from pathlib import Path
import sys

from .contracts import ROOT, validate_instance
from .evaluate import evaluate
from .inrc2 import convert, read_reference
from .io import write_json


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(prog="rostering", description="Shared nurse rostering tools for Solutions A and B")
    commands = parser.add_subparsers(dest="command", required=True)
    conversion = commands.add_parser("convert", help="Shared: INRC2 inputs to standard JSON")
    conversion.add_argument("--scenario-dir", type=Path, default=Path("inrc2/n005w4"))
    conversion.add_argument("--history", type=int, choices=[0, 1, 2], default=0)
    conversion.add_argument("--week-data", type=int, choices=range(10), default=1)
    conversion.add_argument("--out", type=Path, required=True)
    llm = commands.add_parser("llm", help="Solution B: generate and evaluate a roster")
    llm.add_argument("--instance", type=Path, required=True)
    llm.add_argument("--config", type=Path, default=ROOT / "config/llm.json")
    llm.add_argument("--output-dir", type=Path, default=Path("outputs"))
    llm.add_argument("--max-output-tokens", type=positive, default=16000)
    llm.add_argument("--timeout", type=positive, default=240)
    llm.add_argument("--dry-run", action="store_true", help="Save request without calling the API")
    llm.add_argument("--variant", choices=["baseline", "structured", "critique", "combined"], default="baseline")
    check = commands.add_parser("evaluate", help="Shared: evaluate either solution's roster")
    check.add_argument("--instance", type=Path, required=True)
    source = check.add_mutually_exclusive_group(required=True)
    source.add_argument("--roster", type=Path)
    source.add_argument("--reference", type=Path)
    check.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "convert":
            name = args.scenario_dir.name
            instance = convert(args.scenario_dir / f"Sc-{name}.txt", args.scenario_dir / f"H0-{name}-{args.history}.txt", args.scenario_dir / f"WD-{name}-{args.week_data}.txt")
            if args.out.exists():
                raise ValueError("Output exists; choose a new path")
            write_json(args.out, instance)
            print(json.dumps({"instance": str(args.out), "nurses": len(instance["nurses"]), "days": len(instance["days"])}))
            return 0
        instance = json.loads(args.instance.read_text())
        validate_instance(instance)
        if args.command == "llm":
            from .llm.api import APIError
            from .llm.pipeline import run_roster
            try:
                path, metadata = run_roster(instance, json.loads(args.config.read_text()), args.output_dir, max_output_tokens=args.max_output_tokens, timeout=args.timeout, dry_run=args.dry_run, variant=args.variant)
            except APIError as error:
                print(f"Error: {error}", file=sys.stderr)
                return 1
            print(json.dumps({"run_dir": str(path), "status": metadata["status"], "latency_seconds": metadata["latency_seconds"], "usage": metadata["usage"]}, indent=2))
            return 0 if metadata["status"] in {"dry_run", "valid_roster"} else 2
        result = read_reference(instance, args.reference) if args.reference else json.loads(args.roster.read_text())
        report = evaluate(instance, result)
        if args.out:
            write_json(args.out, report)
        print(json.dumps(report, indent=2))
        return 0 if report["hard_valid"] else 2
    except (OSError, ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
