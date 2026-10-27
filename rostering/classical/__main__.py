"""Feasibility-only nurse rostering with a required-slot CSP.

Each required day/shift/skill position is a variable whose values are qualified
nurses. Same-day variables are all different. Adjacent-day slots with illegal
successions cannot choose the same nurse. Monday eligibility includes history.
Unused nurse-days become Off; all nurse-day output records are emitted.

Search uses MRV, degree tie-break, LCV and depth-first backtracking. Specialized
AC-3 propagates binary != and ordered-slot constraints; bounded global capacity
checks enforce distinct-nurse availability. Domains use integer bitsets.

Soundness: every required slot is filled by a qualified nurse, same-day
conflicts prevent double assignment, and adjacent-day conflicts forbid illegal
transitions. The complete output is independently checked by the evaluator.

Completeness: any feasible hard-only roster can have surplus assignments
replaced with Off, preserving feasibility because Off has no forbidden
predecessor/successor. The remaining workers fill exactly these required slots.
Identical slots can be ordered by nurse index without losing a feasible roster.
AC-3 and capacity deductions remove only unsupported choices. Branching visits
all surviving choices, so unlimited finite search finds a solution or proves
infeasibility. A time limit may instead return unknown.

There is no soft objective, so optimality is not applicable. Preferences,
complete-weekend penalties and contract totals are not used in search.
"""

import argparse
from collections import deque
from itertools import combinations
import json
from pathlib import Path
import sys
from time import monotonic

from ..contracts import validate_instance
from ..evaluate import evaluate
from ..io import write_json


def solve(instance, *, optimize=False, time_limit=240, exhaustive=False):
    """Feasibility CSP: required staffing slots choose qualified nurses.

    The legacy optimize argument is accepted but ignored. None uses 240s;
    exhaustive=True disables the limit. No external solver is used.
    """
    time_limit = None if exhaustive else (240 if time_limit is None else time_limit)
    validate_instance(instance)
    if time_limit is not None and not 0 < time_limit < float("inf"):
        raise ValueError("Time limit must be finite and positive")
    started = monotonic()
    nurses, days = instance["nurses"], instance["days"]
    forbidden = instance["forbidden_successions"]
    full_mask = (1 << len(nurses)) - 1
    stats = dict(nodes=0, backtracks=0, arc_revisions=0,
                 values_pruned=0, coverage_checks=0)

    def check_time():
        if time_limit is not None and monotonic() - started >= time_limit:
            raise TimeoutError

    # One variable per required day/shift/skill position. Domain bits identify
    # nurses, so several qualifications never count one person twice.
    slots, domains = [], []
    by_day = [[] for _ in days]
    buckets = [[] for _ in days]
    ordered_edges = []
    for day_index, day in enumerate(days):
        for row in instance["coverage"]:
            if row["day"] != day or not row["minimum"]:
                continue
            eligible = 0
            for n, nurse in enumerate(nurses):
                if row["skill"] not in nurse["skills"]:
                    continue
                previous = instance["history"][nurse["id"]]["last_shift"]
                if day_index == 0 and row["shift"] in forbidden.get(previous, []):
                    continue
                eligible |= 1 << n
            group = []
            for _ in range(row["minimum"]):
                x = len(slots)
                slots.append((day_index, row["shift"], row["skill"]))
                domains.append(eligible)
                by_day[day_index].append(x)
                group.append(x)
            buckets[day_index].append(group)
            # Identical slots are interchangeable. Increasing nurse indices
            # keep one representative of each permutation, safely.
            ordered_edges.extend(zip(group, group[1:]))

    # Conflict arcs: same nurse cannot occupy two slots on one day, or an
    # illegal pair of shifts on adjacent days. Other day pairs are independent.
    conflicts = [set() for _ in slots]
    for day_index, xs in enumerate(by_day):
        for x, y in combinations(xs, 2):
            conflicts[x].add(y)
            conflicts[y].add(x)
        if day_index + 1 < len(days):
            for x in xs:
                for y in by_day[day_index + 1]:
                    if slots[y][1] in forbidden.get(slots[x][1], []):
                        conflicts[x].add(y)
                        conflicts[y].add(x)
    conflicts = [tuple(sorted(xs)) for xs in conflicts]
    less = [[] for _ in slots]
    greater = [[] for _ in slots]
    for x, y in ordered_edges:
        less[x].append(y)
        greater[y].append(x)

    # Small, bounded family of global Hall/capacity checks. Each group of
    # slots needs at least that many distinct nurses. When capacity equals
    # demand, other slots that day cannot use those nurses.
    groups = [[] for _ in days]
    for d, bs in enumerate(buckets):
        sizes = range(1, len(bs) + 1) if len(bs) <= 6 else sorted({1, 2, len(bs)})
        seen = set()
        for size in sizes:
            for chosen in combinations(bs, size):
                indices = tuple(x for bucket in chosen for x in bucket)
                if indices not in seen:
                    seen.add(indices)
                    groups[d].append((indices, tuple(x for x in by_day[d] if x not in indices)))

    def propagate(ds, changed=None):
        if any(mask == 0 for mask in ds):
            return False
        queue = deque(range(len(ds)) if changed is None else changed)
        pending = set(queue)
        dirty = set(range(len(days)) if changed is None else (slots[x][0] for x in changed))

        def restrict(x, mask):
            mask &= ds[x]
            if mask == ds[x]:
                return True
            stats["values_pruned"] += ds[x].bit_count() - mask.bit_count()
            ds[x] = mask
            if not mask:
                return False
            if x not in pending:
                pending.add(x)
                queue.append(x)
            dirty.add(slots[x][0])
            return True

        while queue or dirty:
            check_time()
            if queue:
                x = queue.popleft()
                pending.remove(x)
                mask = ds[x]
                # For !=, every value has support unless the other domain
                # is singleton. This is AC-3 revision specialized to !=.
                if mask.bit_count() == 1:
                    for y in conflicts[x]:
                        stats["arc_revisions"] += 1
                        if not restrict(y, ds[y] & ~mask):
                            return False
                # AC-3 support bounds for ordered identical slots x < y.
                for y in less[x]:
                    stats["arc_revisions"] += 1
                    smallest = (mask & -mask).bit_length() - 1
                    if not restrict(y, full_mask ^ ((1 << (smallest + 1)) - 1)):
                        return False
                for y in greater[x]:
                    stats["arc_revisions"] += 1
                    largest = mask.bit_length() - 1
                    if not restrict(y, (1 << largest) - 1):
                        return False
                continue
            d = min(dirty)
            dirty.remove(d)
            for xs, others in groups[d]:
                check_time()
                stats["coverage_checks"] += 1
                union = 0
                for x in xs:
                    union |= ds[x]
                count = union.bit_count()
                if count < len(xs):
                    return False
                if count == len(xs):
                    for y in others:
                        if not restrict(y, ds[y] & ~union):
                            return False
        return True

    def degree(x, ds):
        return sum(ds[y].bit_count() > 1 for y in conflicts[x])

    def children(x, ds):
        # LCV: count immediate domain deletions, including ordered slots.
        ranked = []
        values = ds[x]
        while values:
            check_time()
            bit = values & -values
            values ^= bit
            nurse = bit.bit_length() - 1
            loss = sum(bool(ds[y] & bit) for y in conflicts[x])
            loss += sum((ds[y] & ((1 << (nurse + 1)) - 1)).bit_count() for y in less[x])
            loss += sum((ds[y] & (full_mask ^ ((1 << nurse) - 1))).bit_count() for y in greater[x])
            ranked.append((loss, nurse, bit))
        for _, _, bit in sorted(ranked):
            check_time()
            child = ds.copy()
            child[x] = bit
            if propagate(child, [x]):
                yield child

    initial_choices = sum(mask.bit_count() for mask in domains)
    best, exhausted, timed_out = None, False, False
    stack = []
    try:
        if propagate(domains):
            stack.append(iter([domains]))
        while stack:
            check_time()
            ds = next(stack[-1], None)
            if ds is None:
                stack.pop()
                stats["backtracks"] += 1
                continue
            stats["nodes"] += 1
            unassigned = [x for x in range(len(ds)) if ds[x].bit_count() > 1]
            if not unassigned:
                best = ds
                break
            size = min(ds[x].bit_count() for x in unassigned)
            x = min((x for x in unassigned if ds[x].bit_count() == size),
                    key=lambda x: (-degree(x, ds), x))
            stack.append(iter(children(x, ds)))
        else:
            exhausted = True
    except TimeoutError:
        timed_out = True

    status = "candidate" if best is not None else "infeasible_claim" if exhausted else "unknown"
    result = dict(schema_version="1.0", status=status, roster=[], explanation=(
        "Valid roster for the four hard constraint categories." if best is not None else
        "Exhaustive search proved infeasibility." if exhausted else
        "Time limit reached before finding a roster."))
    if best is not None:
        assignments = {}
        for x, mask in enumerate(best):
            nurse = mask.bit_length() - 1
            d, shift, skill = slots[x]
            if (nurse, d) in assignments:
                raise AssertionError("Nurse assigned twice on one day")
            assignments[nurse, d] = (shift, skill)
        for nurse, data in enumerate(nurses):
            for d, day in enumerate(days):
                shift, skill = assignments.get((nurse, d), ("Off", None))
                result["roster"].append(dict(nurse_id=data["id"], day=day, shift=shift, skill=skill))
        if not evaluate(instance, result)["hard_valid"]:
            raise AssertionError("Shared evaluator rejected the roster")
    metadata = dict(
        algorithm="Slot CSP: MRV/degree/LCV backtracking with specialized AC-3",
        mode="hard_constraints_only", soft_method=None,
        time_limit_seconds=time_limit, variable_count=len(slots),
        variable_type="required_staffing_slot", nurse_day_records=len(nurses)*len(days),
        initial_domain_values=initial_choices, exact_minimum_reduction=True,
        ordered_slot_pairs=len(ordered_edges), legacy_optimize_ignored=bool(optimize),
        runtime_seconds=monotonic()-started, timed_out=timed_out,
        search_exhausted=exhausted, infeasibility_proven=best is None and exhausted,
        optimality_proven=False, optimality_applicable=False, soft_cost=None,
        objective_scope="Feasibility only; no soft objective", statistics=stats)
    return result, metadata


def main():
    parser = argparse.ArgumentParser(
        description="Classical CSP nurse rostering solver"
    )
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument(
        "--time-limit",
        type=float,
        default=240,
        help="Seconds; default 240",
    )
    parser.add_argument(
        "--first-feasible",
        action="store_true",
        help="Compatibility flag; solver always stops at first valid roster",
    )
    parser.add_argument("--exhaustive", action="store_true",
                        help="Disable the time limit; may take a long time")
    args = parser.parse_args()

    try:
        metadata_path = (
            args.metadata
            or args.out.with_suffix(".metadata.json")
        )
        paths = [
            args.instance.resolve(),
            args.out.resolve(),
            metadata_path.resolve(),
        ]
        if len(set(paths)) != 3:
            raise ValueError(
                "Instance, roster and metadata paths must differ"
            )

        instance = json.loads(
            args.instance.read_text(encoding="utf-8")
        )
        result, metadata = solve(
            instance,
            optimize=False,
            time_limit=args.time_limit,
            exhaustive=args.exhaustive,
        )

        write_json(args.out, result)
        write_json(metadata_path, metadata)
        print(json.dumps(
            {"status": result["status"], **metadata},
            indent=2,
        ))
        return 0 if result["status"] == "candidate" else 2

    except (OSError, ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
