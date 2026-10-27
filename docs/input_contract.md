# Shared contract

Both solutions consume the same instance JSON and export the same roster JSON. The full specifications are [instance.schema.json](../schemas/instance.schema.json) and [roster.schema.json](../schemas/roster.schema.json); an [example input](../converted/n005w4/h0_wd1.json) is included.

## Input

`schema_version` is `1.0`. The instance contains:

- Scenario ID, full-horizon weeks, zero-based week position and Mon–Sun days.
- Nurses, qualified skills, shift types, contracts and forbidden successions.
- Coverage for every day/shift/skill, with separate minimum and preferred counts.
- Shift-off requests and nurse history before Monday.
- Source paths and hashes for the three original INRC2 files.

Load files directly from `converted/`; the matched benchmark plan already uses them. For new cases, use `python -m rostering convert` or `rostering.inrc2.convert`. A WD suffix identifies a data variant, not a chronological week. Historical `None` is normalised to `Off`; only the previous shift affects Monday in the current hard-only scope. Streak counters are retained but not enforced. Full-horizon contract limits remain full-horizon limits.

## Output

A roster has `schema_version`, `status`, `explanation` and `roster`. Each candidate includes every nurse-day exactly once:

```json
{"nurse_id": "Patrick", "day": "Mon", "shift": "Night", "skill": "Nurse"}
```

Off records use `shift: "Off"` and `skill: null`. A working nurse covers one qualified skill per assignment.

| Status | Meaning |
| --- | --- |
| `candidate` | Complete proposed roster, subject to independent evaluation. |
| `unknown` | No roster found; return an empty roster. |
| `infeasible_claim` | Infeasibility asserted; return an empty roster. |

For A, record proof of infeasibility, runtime and search statistics in separate metadata. There is no soft objective, so soft-cost optimality is not applicable. The common evaluator checks rosters and does not certify infeasibility claims. A timeout is `unknown`.

## Shared feasibility task

Hard rules: one shift per day, minimum coverage, qualified skill and legal shift succession, including history into Monday. Completeness and real identifiers are also required. A multi-skilled nurse must not be counted twice.

Both solutions return any hard-valid roster; staffing above minimum is allowed. Neither optimizes preferred coverage, shift-off requests, complete weekends, fairness or workload. Shift-off requests are not mandatory leave. Consecutive work/shift/rest limits, weekly hours and full-horizon totals are not enforced. Each input is an independent seven-day week, not a sequential rollout.

The evaluator retains optional diagnostic soft penalties: preferred-coverage shortage (30 per missing nurse), violated shift-off request (10), and incomplete weekend where applicable (30). These do not affect hard validity and are not a shared optimization objective.

`python -m rostering evaluate` or `rostering.evaluate.evaluate` checks either solution. It reports `solution_status`, structural validity, completeness, violations by category and valid-only partial soft cost. Missing or ambiguous assignments cannot fill coverage. Schema failures/noncandidate outputs have null hard counts and soft costs. Categories can overlap, so their sum is not a count of distinct mistakes.

Constraint definitions follow the [INRC2 specification](https://arxiv.org/html/1501.04177v1). The converter validates cross-references and dimensions as well as JSON structure.
