"""Load the shared JSON contracts and check cross-references."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())


def schema_errors(value: object, name: str) -> list[str]:
    errors = Draft202012Validator(load_schema(name)).iter_errors(value)
    return [f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}" for e in errors]


def validate_instance(instance: dict) -> None:
    errors = schema_errors(instance, "instance")
    if errors:
        raise ValueError("Invalid instance: " + "; ".join(errors[:5]))
    nurses = {n["id"]: n for n in instance["nurses"]}
    shifts = {s["name"] for s in instance["shift_types"]}
    skills = set(instance["skills"])
    if len(nurses) != len(instance["nurses"]):
        raise ValueError("Duplicate nurse identifiers")
    if len(shifts) != len(instance["shift_types"]) or shifts & {"Off", "Any", "None"}:
        raise ValueError("Duplicate or reserved shift names")
    if instance["week_index"] >= instance["horizon_weeks"]:
        raise ValueError("Week index lies outside the planning horizon")
    for shift in instance["shift_types"]:
        if shift["min_consecutive"] > shift["max_consecutive"]:
            raise ValueError("Invalid consecutive shift range")
    for contract in instance["contracts"].values():
        for key in ["total_assignments", "consecutive_work_days", "consecutive_days_off"]:
            if contract[key]["min"] > contract[key]["max"]:
                raise ValueError("Invalid contract range")
    if set(instance["history"]) != set(nurses):
        raise ValueError("History must contain exactly the scenario nurses")
    for nurse in nurses.values():
        if nurse["contract"] not in instance["contracts"] or not set(nurse["skills"]) <= skills:
            raise ValueError("Unknown nurse contract or skill")
        history = instance["history"][nurse["id"]]
        if history["last_shift"] not in shifts | {"Off"}:
            raise ValueError("Unknown historical shift")
        if history["last_shift"] == "Off":
            if history["consecutive_same_shift"] or history["consecutive_work_days"]:
                raise ValueError("Off history cannot have a working streak")
        elif history["consecutive_days_off"] or not 0 < history["consecutive_same_shift"] <= history["consecutive_work_days"]:
            raise ValueError("Inconsistent working history")
    if set(instance["forbidden_successions"]) != shifts:
        raise ValueError("Succession table must contain every shift type")
    for following in instance["forbidden_successions"].values():
        if not set(following) <= shifts:
            raise ValueError("Unknown forbidden successor")
    coverage = set()
    for row in instance["coverage"]:
        key = (row["day"], row["shift"], row["skill"])
        if key in coverage or row["shift"] not in shifts or row["skill"] not in skills:
            raise ValueError("Duplicate or unknown coverage entry")
        if row["minimum"] > row["preferred"]:
            raise ValueError("Minimum coverage exceeds preferred coverage")
        coverage.add(key)
    expected = {(d, s, k) for d in DAYS for s in shifts for k in skills}
    if coverage != expected:
        raise ValueError("Coverage must specify every day/shift/skill combination")
    for row in instance["shift_off_requests"]:
        if row["nurse_id"] not in nurses or row["shift"] not in shifts | {"Any"}:
            raise ValueError("Unknown nurse or shift in request")
