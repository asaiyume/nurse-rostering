"""Read INRC2 text inputs without searching for or generating assignments."""

import hashlib
import re
from pathlib import Path

from .contracts import DAYS, ROOT, validate_instance


def lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


class Reader:
    def __init__(self, path: Path):
        self.path = path
        self.rows = iter(lines(path))

    def next(self) -> str:
        try:
            return next(self.rows)
        except StopIteration:
            raise ValueError(f"Unexpected end of {self.path.name}") from None

    def expect(self, text: str) -> None:
        if self.next() != text:
            raise ValueError(f"Expected {text} in {self.path.name}")

    def value(self, key: str) -> str:
        match = re.fullmatch(rf"{key}\s*=\s*(\S+)", self.next())
        if not match:
            raise ValueError(f"Expected {key} in {self.path.name}")
        return match[1]

    def end(self) -> None:
        if next(self.rows, None) is not None:
            raise ValueError(f"Unexpected trailing data in {self.path.name}")


def pair(text: str) -> dict:
    match = re.fullmatch(r"\((\d+),(\d+)\)", text)
    if not match:
        raise ValueError(f"Invalid INRC2 range: {text}")
    return {"min": int(match[1]), "max": int(match[2])}


def provenance(path: Path) -> dict:
    resolved = path.resolve()
    try:
        label = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        label = path.as_posix()
    return {"path": label, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def convert(scenario_path: Path, history_path: Path, week_path: Path) -> dict:
    sc = Reader(scenario_path)
    scenario = sc.value("SCENARIO")
    horizon = int(sc.value("WEEKS"))
    skills = [sc.next() for _ in range(int(sc.value("SKILLS")))]
    shift_types = []
    for _ in range(int(sc.value("SHIFT_TYPES"))):
        name, bounds = sc.next().split()
        limits = pair(bounds)
        shift_types.append({"name": name, "min_consecutive": limits["min"], "max_consecutive": limits["max"]})
    sc.expect("FORBIDDEN_SHIFT_TYPES_SUCCESSIONS")
    forbidden = {}
    for _ in shift_types:
        name, count, *following = sc.next().split()
        if len(following) != int(count) or name in forbidden:
            raise ValueError("Invalid succession table")
        forbidden[name] = following
    contracts = {}
    for _ in range(int(sc.value("CONTRACTS"))):
        name, total, work, off, weekends, complete = sc.next().split()
        if name in contracts or complete not in {"0", "1"}:
            raise ValueError("Duplicate contract or invalid complete-weekend flag")
        contracts[name] = {
            "total_assignments": pair(total), "consecutive_work_days": pair(work),
            "consecutive_days_off": pair(off), "max_working_weekends": int(weekends),
            "complete_weekends": complete == "1",
        }
    nurses = []
    for _ in range(int(sc.value("NURSES"))):
        name, contract, count, *qualifications = sc.next().split()
        if len(qualifications) != int(count):
            raise ValueError("Nurse skill count mismatch")
        nurses.append({"id": name, "contract": contract, "skills": qualifications})
    sc.end()

    hr = Reader(history_path)
    hr.expect("HISTORY")
    week_index, history_scenario = hr.next().split()
    hr.expect("NURSE_HISTORY")
    history = {}
    for _ in nurses:
        name, total, weekends, last, same, work, off = hr.next().split()
        if name in history:
            raise ValueError("Duplicate nurse history")
        history[name] = {
            "total_assignments": int(total), "working_weekends": int(weekends),
            "last_shift": "Off" if last == "None" else last,
            "consecutive_same_shift": int(same), "consecutive_work_days": int(work),
            "consecutive_days_off": int(off),
        }
    hr.end()

    wd = Reader(week_path)
    wd.expect("WEEK_DATA")
    week_scenario = wd.next()
    if history_scenario != scenario or week_scenario != scenario:
        raise ValueError("Scenario, history, and week data identifiers do not match")
    wd.expect("REQUIREMENTS")
    coverage = []
    for _ in range(len(skills) * len(shift_types)):
        shift, skill, *bounds = wd.next().split()
        if len(bounds) != 7:
            raise ValueError("Coverage must contain seven days")
        for day, text in zip(DAYS, bounds):
            limits = pair(text)
            coverage.append({"day": day, "shift": shift, "skill": skill, "minimum": limits["min"], "preferred": limits["max"]})
    requests = []
    for _ in range(int(wd.value("SHIFT_OFF_REQUESTS"))):
        nurse, shift, day = wd.next().split()
        requests.append({"nurse_id": nurse, "day": day, "shift": shift})
    wd.end()
    result = {
        "schema_version": "1.0", "instance_id": f"{scenario}_{history_path.stem}_{week_path.stem}_week{week_index}",
        "scenario_id": scenario, "horizon_weeks": horizon, "week_index": int(week_index),
        "days": DAYS.copy(), "skills": skills, "shift_types": shift_types,
        "forbidden_successions": forbidden, "contracts": contracts, "nurses": nurses,
        "history": history, "coverage": coverage, "shift_off_requests": requests,
        "sources": {"scenario": provenance(scenario_path), "history": provenance(history_path), "week_data": provenance(week_path)},
    }
    validate_instance(result)
    return result


def read_reference(instance: dict, path: Path) -> dict:
    """Convert a supplied sparse solution to a dense roster for evaluator checks only."""
    reader = Reader(path)
    reader.expect("SOLUTION")
    index, scenario = reader.next().split()
    if int(index) != instance["week_index"] or scenario != instance["scenario_id"]:
        raise ValueError("Reference solution belongs to a different scenario or week")
    assignments = []
    for _ in range(int(reader.value("ASSIGNMENTS"))):
        nurse, day, shift, skill = reader.next().split()
        assignments.append({"nurse_id": nurse, "day": day, "shift": shift, "skill": skill})
    reader.end()
    present = {(r["nurse_id"], r["day"]) for r in assignments}
    assignments.extend(
        {"nurse_id": nurse["id"], "day": day, "shift": "Off", "skill": None}
        for nurse in instance["nurses"] for day in instance["days"]
        if (nurse["id"], day) not in present
    )
    return {"schema_version": "1.0", "status": "candidate", "explanation": "Imported evaluation reference; never included in generation prompts.", "roster": assignments}
