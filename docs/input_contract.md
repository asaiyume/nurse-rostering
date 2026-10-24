# Shared nurse rostering input contract

This is the proposed v1.0 interface for review with Jevan. Solutions A and B should consume the same instance and use the same experimental constraint scope. Agreement has not been recorded yet.

The machine-readable contract is `schemas/instance.schema.json`; a converted example is `data/instances/n005w4_h0_wd1.json`. The parser also checks references, identifiers, ranges, complete coverage dimensions, and basic history consistency that JSON Schema alone does not enforce.

## Input fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Exactly `1.0`; change when the shared format changes incompatibly. |
| `instance_id` | Identifies the scenario, input history, weekly data variant, and week position. |
| `scenario_id` | Original scenario identifier, such as `n005w4`. |
| `horizon_weeks` | Original planning horizon; four/eight-week limits remain horizon limits. |
| `week_index` | Zero-based position from the history header, not the WD filename suffix. |
| `days` | Exactly Monday through Sunday in chronological order. |
| `skills` | All scenario skill names. Skills do not imply a qualification hierarchy. |
| `shift_types` | Names and minimum/maximum consecutive assignments for each shift. Off is a separate output value. |
| `forbidden_successions` | Maps each shift to prohibited next-day working shifts. Off interrupts a succession. |
| `contracts` | Contract ID mapped to total assignments, work/off streak ranges, maximum working weekends, and the complete-weekend flag. |
| `nurses` | Original identifiers, contract IDs, and explicit qualified skills. |
| `history` | Per-nurse counters and border data before Monday. Raw `None` is normalised to `Off`. |
| `coverage` | Every day/shift/skill combination, including zero demand, with `minimum` and `preferred` counts. |
| `shift_off_requests` | Nurse, day, and undesired shift. `Any` requests the whole day off. |
| `sources` | Original three input paths and SHA-256 hashes. Reference solutions are excluded. |

Each history record has `total_assignments`, `working_weekends`, `last_shift`, `consecutive_same_shift`, `consecutive_work_days`, and `consecutive_days_off`. Initial counters may be zero while border streaks are nonzero. This is expected: history still affects Monday.

The CLI conversion currently selects an initial H0 file and one WD variant. The runner handles one week per invocation. It does not yet advance history automatically or implement the full multi-stage competition protocol.

## Output contract

`schemas/roster.schema.json` defines the common JSON output. A candidate contains exactly one record per nurse-day, with fields `nurse_id`, `day`, `shift`, and `skill`. Working shifts must specify one qualified skill; Off records use `skill: null`. The evaluator checks uniqueness and cross-references separately from syntax.

| Status | Meaning |
| --- | --- |
| `candidate` | A complete proposed roster for independent evaluation. This is not a correctness certificate. |
| `unknown` | The model did not construct a roster; `roster` must be empty. |
| `infeasible_claim` | The model asserts infeasibility; `roster` must be empty. The evaluator does not certify the claim. |

## Pilot evaluation scope

The hard rules are INRC2's single assignment per day, minimum coverage, legal shift succession, and required skill. Completeness and valid identifiers are additional output requirements. An ambiguous or unqualified nurse-day cannot be credited toward coverage.

The pilot scores three soft categories on hard-valid candidates: preferred coverage shortage at 30 per nurse, violated shift-off requests at 10 each, and incomplete weekends at 30 per applicable nurse. It does not score consecutive assignments, consecutive days off, total assignments, or total working weekends. These fields remain in the input for later extensions. The resulting `partial_total` is not a full INRC2 score, and is not comparable with the full score in supplied validator reports.

To compare with Solution A, use exactly this pilot objective or agree on an expanded scope before running both. The objective is absent for invalid rosters and abstentions. Only claim an optimality gap if A proves the optimum for this same objective and input.

## Violation counts

- `single_assignment`: extra working assignments beyond one per nurse-day.
- `minimum_coverage`: missing nurse units, summed across day/shift/skill requirements.
- `shift_succession`: prohibited consecutive-day transitions, including the history-to-Monday boundary.
- `required_skill`: working records whose assigned skill the nurse lacks, including a null working skill.

Missing/duplicate nurse-day records, unknown nurses/shifts, and Off records with a skill are reported under `output_issues`. JSON/schema failures and noncandidate responses leave hard counts and soft costs null because no complete candidate was evaluated. Hard validity requires valid structure, complete output, no output issues, and zero hard violations. Separate categories can describe the same defective assignment; do not interpret their sum as a count of distinct mistakes.

## Sources

The format and constraint distinction follow the [INRC2 problem description](https://arxiv.org/html/1501.04177v1). The current API layer supports Chat Completions and Responses. New experiments use Chat Completions after gateway capability checks; see `docs/safeguards.md` for the measured behaviour and [Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs) for the request conventions.
