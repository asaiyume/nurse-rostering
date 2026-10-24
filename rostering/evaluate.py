"""Post-hoc evaluation only: this module never generates or repairs assignments."""

from collections import Counter, defaultdict

from .contracts import schema_errors, validate_instance


def evaluate(instance: dict, result: object) -> dict:
    validate_instance(instance)
    errors = schema_errors(result, "roster")
    report = {
        "instance_id": instance["instance_id"],
        "schema_valid": not errors, "schema_errors": errors,
        "solution_status": result.get("status") if isinstance(result, dict) else None,
        "evaluation_status": "invalid_schema" if errors else "not_candidate",
        "roster_complete": False, "hard_valid": False,
        "hard_violation_counts": None, "hard_violations": [], "output_issues": [],
        "soft_score": None,
        "soft_scope": {
            "included": ["preferred_coverage", "shift_off_requests", "complete_weekends"],
            "excluded": ["consecutive_assignments", "consecutive_days_off", "total_assignments", "total_working_weekends"],
            "is_full_inrc2_score": False,
        },
    }
    if errors or result["status"] != "candidate":
        return report

    report["evaluation_status"] = "evaluated"
    nurses = {n["id"]: n for n in instance["nurses"]}
    shifts = {s["name"] for s in instance["shift_types"]}
    days = instance["days"]
    groups = defaultdict(list)
    counts = Counter()
    hard = {"single_assignment": 0, "minimum_coverage": 0, "shift_succession": 0, "required_skill": 0}

    def issue(kind: str, **detail) -> None:
        report["output_issues"].append({"type": kind, **detail})

    def violation(kind: str, units: int = 1, **detail) -> None:
        hard[kind] += units
        report["hard_violations"].append({"type": kind, "units": units, **detail})

    for index, row in enumerate(result["roster"]):
        nurse, day, shift, skill = (row[k] for k in ["nurse_id", "day", "shift", "skill"])
        if nurse not in nurses:
            issue("unknown_nurse", row=index, nurse_id=nurse)
            continue
        groups[nurse, day].append(row)
        if shift not in shifts | {"Off"}:
            issue("unknown_shift", row=index, shift=shift)
        elif shift == "Off":
            if skill is not None:
                issue("off_with_skill", row=index)
        elif skill not in nurses[nurse]["skills"]:
            violation("required_skill", row=index, nurse_id=nurse, day=day, shift=shift, skill=skill)

    for nurse in nurses:
        previous = instance["history"][nurse]["last_shift"]
        for day in days:
            rows = groups[nurse, day]
            if not rows:
                issue("missing_nurse_day", nurse_id=nurse, day=day)
            elif len(rows) > 1:
                issue("duplicate_nurse_day", nurse_id=nurse, day=day, records=len(rows))
            working = [r for r in rows if r["shift"] in shifts]
            if len(working) > 1:
                violation("single_assignment", len(working) - 1, nurse_id=nurse, day=day)
            # An ambiguous nurse-day cannot fill multiple coverage slots or imply a transition.
            if len(rows) != 1 or rows[0]["shift"] not in shifts | {"Off"}:
                previous = None
                continue
            row = rows[0]
            shift, skill = row["shift"], row["skill"]
            if shift in instance["forbidden_successions"].get(previous, []):
                violation("shift_succession", nurse_id=nurse, day=day, previous_shift=previous, shift=shift)
            if shift in shifts and skill in nurses[nurse]["skills"]:
                counts[day, shift, skill] += 1
            previous = shift

    preferred_cost = 0
    for row in instance["coverage"]:
        assigned = counts[row["day"], row["shift"], row["skill"]]
        missing = max(0, row["minimum"] - assigned)
        if missing:
            violation("minimum_coverage", missing, day=row["day"], shift=row["shift"], skill=row["skill"], required=row["minimum"], assigned=assigned)
        preferred_cost += 30 * max(0, row["preferred"] - assigned)

    expected = {(n, d) for n in nurses for d in days}
    report["roster_complete"] = all(len(groups[key]) == 1 for key in expected) and len(result["roster"]) == len(expected)
    report["hard_violation_counts"] = hard
    report["hard_valid"] = report["roster_complete"] and not report["output_issues"] and not any(hard.values())
    if report["hard_valid"]:
        preference_cost = 0
        for request in instance["shift_off_requests"]:
            shift = groups[request["nurse_id"], request["day"]][0]["shift"]
            if shift != "Off" and request["shift"] in {"Any", shift}:
                preference_cost += 10
        weekend_cost = 0
        for nurse, data in nurses.items():
            if instance["contracts"][data["contract"]]["complete_weekends"]:
                worked = sum(groups[nurse, day][0]["shift"] != "Off" for day in ["Sat", "Sun"])
                weekend_cost += 30 if worked == 1 else 0
        report["soft_score"] = {
            "preferred_coverage": preferred_cost, "shift_off_requests": preference_cost,
            "complete_weekends": weekend_cost,
            "partial_total": preferred_cost + preference_cost + weekend_cost,
        }
    return report
