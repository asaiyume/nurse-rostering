# Matched hard-only comparison

Status: **complete**. 195/195 saved trials; 312 model calls recorded.

Fifteen identical input files are used by both solutions: five nurse-count strata, with an anchor, a controlled history contrast and a controlled demand contrast in each. Solution A runs once per input; each LLM variant runs three times per input. All inputs represent one independent seven-day week at week zero.

Both solve hard-constraint feasibility only: minimum coverage, qualified skills, at most one working shift per nurse-day, and legal successions including history into Monday. Complete nurse-day output and valid identifiers are also required. Surplus staffing is allowed. Neither optimizes preferences, weekends, fairness or workload. Evaluator soft scores are diagnostic only.

No client or whole-trial time limit is imposed; classical search also runs without a time limit. Token caps are 32,000 per roster stage and 16,000 for the audit. All four variants request reasoning effort high; these caps include reasoning and answer tokens. LLM latency includes all model calls; runtime also includes local pipeline work. Classical runs finish before the LLM batch to avoid local CPU contention. LLM jobs are shuffled with scheduling seed 4263; this does not seed model sampling.

| Method | Cases covered | Hard-valid trials / attempted | Output-schema valid | Mean runtime (s) | Mean model latency (s) | API calls | Reported tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| classical | 15/15 | 15/15 | 15/15 | 0.012 | — | 0 | — |
| baseline | 15/15 | 40/45 | 40/45 | 162.098 | 162.032 | 45 | 823,316 |
| structured | 15/15 | 38/45 | 39/45 | 165.944 | 165.876 | 45 | 917,451 |
| critique | 15/15 | 40/45 | 40/45 | 329.464 | 329.390 | 111 | 2,154,631 |
| combined | 15/15 | 43/45 | 43/45 | 344.471 | 344.394 | 111 | 2,354,185 |

Counts include every saved attempt, including errors, incomplete outputs and abstentions. A classical infeasibility proof is a resolved decision, not a hard-valid roster. The classical denominator is 15; each LLM denominator is 45 at completion. Three model repetitions on one input do not create three different benchmark instances.

## Validity by nurse count

| Nurses | Classical | Baseline | Structured | Critique | Combined |
| --- | --- | --- | --- | --- | --- |
| 5 | 3/3 | 9/9 | 9/9 | 9/9 | 9/9 |
| 12 | 3/3 | 9/9 | 9/9 | 9/9 | 9/9 |
| 21 | 3/3 | 9/9 | 8/9 | 9/9 | 9/9 |
| 35 | 3/3 | 9/9 | 9/9 | 9/9 | 9/9 |
| 50 | 3/3 | 4/9 | 3/9 | 4/9 | 7/9 |

## Cases and decision outcomes

| Case | Role | Minimum staff-days | Classical status | B valid baseline / structured / critique / combined |
| --- | --- | --- | --- | --- |
| n005w4_h0_wd6 | anchor | 23 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n005w4_h1_wd6 | history_contrast | 23 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n005w4_h0_wd4 | demand_contrast | 26 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n012w8_h1_wd1 | anchor | 48 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n012w8_h2_wd1 | history_contrast | 48 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n012w8_h1_wd4 | demand_contrast | 43 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n021w4_h2_wd8 | anchor | 63 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n021w4_h0_wd8 | history_contrast | 63 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n021w4_h2_wd2 | demand_contrast | 67 | candidate | 3/3 / 2/3 / 3/3 / 3/3 |
| n035w4_h0_wd7 | anchor | 89 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n035w4_h2_wd7 | history_contrast | 89 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n035w4_h0_wd2 | demand_contrast | 86 | candidate | 3/3 / 3/3 / 3/3 / 3/3 |
| n050w4_h1_wd6 | anchor | 139 | candidate | 1/3 / 1/3 / 2/3 / 2/3 |
| n050w4_h2_wd6 | history_contrast | 139 | candidate | 0/3 / 1/3 / 0/3 / 2/3 |
| n050w4_h1_wd5 | demand_contrast | 149 | candidate | 3/3 / 1/3 / 2/3 / 3/3 |

## Violations and uncertainty

| Method | Evaluable candidates | Coverage shortage | Forbidden transitions | Skill violations | Extra working assignments |
| --- | --- | --- | --- | --- | --- |
| classical | 15 | 0 | 0 | 0 | 0 |
| baseline | 40 | 0 | 0 | 0 | 0 |
| structured | 39 | 1 | 0 | 0 | 0 |
| critique | 40 | 0 | 0 | 0 | 0 |
| combined | 43 | 0 | 0 | 0 | 0 |

Violation totals cover evaluable candidates only; unavailable counts are not zero. Categories can overlap. These totals should not replace all-attempt validity rates.

### Infeasibility claims

- baseline: 0 false on A-validated feasible inputs; 0 agree with an A infeasibility proof; 0 unverified because A did not resolve feasibility.
- structured: 0 false on A-validated feasible inputs; 0 agree with an A infeasibility proof; 0 unverified because A did not resolve feasibility.
- critique: 0 false on A-validated feasible inputs; 0 agree with an A infeasibility proof; 0 unverified because A did not resolve feasibility.
- combined: 0 false on A-validated feasible inputs; 0 agree with an A infeasibility proof; 0 unverified because A did not resolve feasibility.

This purposive 15-case subset is not representative of every INRC2 instance. Nurse count varies alongside skill/shift mix, so differences across sizes are descriptive. History contrasts hold weekly demand fixed; demand contrasts hold history fixed, but weekly demand distributions change as well as their totals. Four/eight-week labels are source metadata: no multiweek progression is tested. No optimality, monetary-cost or demographic-fairness claim is made. Raw traces remain under ignored outputs; portable aggregate metrics and all-trial records accompany this report.

<!-- verified-analysis:start -->
## Replay and reasoning evidence

All 195 saved trials were replayed offline with matching inputs and independent evaluations. The gateway returned 298 responses from 312 recorded calls. 105/108 constrained stages returned complete JSON matching their generation schema. This does not establish full output-schema or scheduling correctness.

| Variant | Valid initial candidates | Final hard-valid | API failures | Reported reasoning tokens |
| --- | --- | --- | --- | --- |
| baseline | 40 | 40 | 5 | 449,523 |
| structured | 38 | 38 | 3 | 521,885 |
| critique | 39 | 40 | 4 | 1,080,159 |
| combined | 43 | 43 | 2 | 1,205,505 |

API failures are unresolved attempts, not demonstrated scheduling violations. Initial valid rosters in API-failed review trials are reported separately: the pipeline does not silently accept an initial roster after a failed API stage. The final protocol has no imposed deadline; server/network failures remain possible.

Gateway load, caching and network time were not controlled. Reported reasoning tokens are taken from the API usage records; exposed thinking text remains in the raw response traces. Token totals sum available usage only: API-failed stages can have unreported usage, so these totals are not complete monetary-cost estimates.

### Audit and revision outcomes

| Variant | Completed revisions | Invalid-to-valid repairs | Valid-to-invalid final outputs | Incomplete audits retaining the original |
| --- | --- | --- | --- | --- |
| critique | 26 | 1 | 0 | 14 |
| combined | 23 | 0 | 0 | 20 |

A valid-to-invalid final output includes incomplete or malformed revision output, not only newly introduced scheduling violations. An incomplete audit can retain a valid original without completing a revision; that is not counted as a successful repair.

### Schema validity does not establish feasibility

- `n021w4_h2_wd2`, structured repetition 1: the output passed its JSON schema but failed independent scheduling checks. Sat Night Nurse: minimum_coverage, required 1, assigned 0.
