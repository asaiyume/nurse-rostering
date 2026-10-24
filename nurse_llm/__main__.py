"""Commands for conversion, generation, and independent evaluation."""

import argparse
import json
from pathlib import Path
import sys

from .api import APIError
from .contracts import ROOT, validate_instance
from .evaluate import evaluate
from .inrc2 import convert, read_reference
from .pipeline import run_baseline, write_json
from .safeguards import VARIANTS


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description="INRC2 direct LLM roster pilot")
    commands = parser.add_subparsers(dest="command", required=True)
    conversion = commands.add_parser("convert", help="Convert scenario + initial history + weekly variant to shared JSON")
    conversion.add_argument("--scenario-dir", type=Path, default=Path("inrc2/n005w4"))
    conversion.add_argument("--history", type=int, choices=[0, 1, 2], default=0)
    conversion.add_argument("--week-data", type=int, choices=range(10), default=1)
    conversion.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("run", help="Generate and evaluate one baseline roster")
    run.add_argument("--instance", type=Path, required=True)
    run.add_argument("--config", type=Path, default=ROOT / "config" / "llm.json")
    run.add_argument("--output-dir", type=Path, default=Path("outputs"))
    run.add_argument("--max-output-tokens", type=positive, default=16000)
    run.add_argument("--timeout", type=positive, default=240)
    run.add_argument("--dry-run", action="store_true", help="Save instance, prompt, request, metadata; do not call the API")
    run.add_argument("--variant", choices=VARIANTS, default="baseline")
    check = commands.add_parser("evaluate", help="Evaluate a saved JSON roster or INRC2 reference without an API call")
    check.add_argument("--instance", type=Path, required=True)
    source = check.add_mutually_exclusive_group(required=True)
    source.add_argument("--roster", type=Path)
    source.add_argument("--reference", type=Path)
    check.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "convert":
            name = args.scenario_dir.name
            instance = convert(
                args.scenario_dir / f"Sc-{name}.txt",
                args.scenario_dir / f"H0-{name}-{args.history}.txt",
                args.scenario_dir / f"WD-{name}-{args.week_data}.txt",
            )
            if args.out.exists():
                raise ValueError("Output already exists; choose a new path to preserve the agreed input")
            write_json(args.out, instance)
            print(json.dumps({"instance": str(args.out), "nurses": len(instance["nurses"]), "days": len(instance["days"]), "coverage_entries": len(instance["coverage"])}))
            return 0
        instance = json.loads(args.instance.read_text())
        validate_instance(instance)
        if args.command == "run":
            config = json.loads(args.config.read_text())
            path, metadata = run_baseline(instance, config, args.output_dir, max_output_tokens=args.max_output_tokens, timeout=args.timeout, dry_run=args.dry_run, variant=args.variant)
            print(json.dumps({"run_dir": str(path), "status": metadata["status"], "latency_seconds": metadata["latency_seconds"], "usage": metadata["usage"]}, indent=2))
            return 0 if metadata["status"] in {"dry_run", "valid_roster"} else 2
        result = read_reference(instance, args.reference) if args.reference else json.loads(args.roster.read_text())
        report = evaluate(instance, result)
        if args.out:
            write_json(args.out, report)
        print(json.dumps(report, indent=2))
        return 0 if report["hard_valid"] else 2
    except (OSError, ValueError, KeyError, APIError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
