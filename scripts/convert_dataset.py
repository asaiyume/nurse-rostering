"""Convert every INRC2 scenario/initial-history/week-data combination to JSON."""

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rostering.inrc2 import convert
from rostering.io import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "inrc2")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "converted")
    args = parser.parse_args()
    rows = []
    created = 0
    scenarios = sorted(p for p in args.data_dir.iterdir() if p.is_dir())
    if not scenarios:
        raise ValueError("No scenario directories found")
    for folder in scenarios:
        name = folder.name
        histories = sorted(folder.glob(f"H0-{name}-*.txt"))
        weeks = sorted(folder.glob(f"WD-{name}-*.txt"))
        if not histories or not weeks:
            raise ValueError(f"Missing history or weekly inputs for {name}")
        for history in histories:
            h = int(history.stem.rsplit("-", 1)[1])
            for week in weeks:
                w = int(week.stem.rsplit("-", 1)[1])
                instance = convert(folder / f"Sc-{name}.txt", history, week)
                relative = Path(name) / f"h{h}_wd{w}.json"
                target = args.out_dir / relative
                if target.exists():
                    if json.loads(target.read_text()) != instance:
                        raise ValueError(f"Existing conversion differs: {target}")
                else:
                    write_json(target, instance)
                    created += 1
                rows.append({
                    "file": relative.as_posix(), "scenario": instance["scenario_id"],
                    "nurses": len(instance["nurses"]), "horizon_weeks": instance["horizon_weeks"],
                    "history": h, "week_data": w, "week_index": instance["week_index"],
                })
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "index.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"scenarios": len(scenarios), "instances": len(rows), "created": created, "output": str(args.out_dir)}, indent=2))


if __name__ == "__main__":
    main()
