# Repeated nurse rostering pilot

Five cases, 3 independent repetitions per case and four variants: 60 trials and 120 model calls. The earlier Responses development pilot and the two safeguard development checks are excluded.

All variants use SoCLaas `x-test-2` via Chat Completions, with requested reasoning effort `none`, provider-default sampling, the same baseline prompt, and the same three-category pilot objective. Exact input/request fingerprints match across the two suites.

## Results

| Variant | Schema-valid / attempted | Hard-valid / attempted | Mean latency (s) | Reported tokens |
| --- | --- | --- | --- | --- |
| baseline | 14/15 | 0/15 | 5.0 | 55,336 |
| structured | 14/15 | 0/15 | 6.5 | 54,438 |
| critique | 15/15 | 0/15 | 39.0 | 258,941 |
| combined | 14/15 | 0/15 | 38.5 | 258,954 |

Validity uses all attempted trials as the denominator. Empty responses, malformed/schema-invalid JSON, infeasibility claims and API errors are not silently removed. Hard validity also requires complete nurse-day output and no output-identity defects.

All constrained stages were also checked against the exact generation schema sent to the API: 45/45 conformed. This generation schema is a supported subset of the local contract: it cannot express the cross-field rule that unknown/infeasible status must have an empty roster. Conformance to the generation schema therefore does not establish full contract validity or scheduling correctness.

## Hard violations

| Variant | Missing coverage units | Forbidden transitions | Skill violations | Extra working assignments |
| --- | --- | --- | --- | --- |
| baseline | 89 | 9 | 2 | 0 |
| structured | 95 | 19 | 6 | 1 |
| critique | 88 | 16 | 3 | 0 |
| combined | 77 | 22 | 6 | 0 |

Counts include only structurally evaluable candidates and can describe overlapping defects. They are not a total count of distinct mistakes; schema failures have null hard counts.

## Audit and revision

- critique: 0 invalid-to-valid repairs, 0 valid-to-invalid regressions, 0 remained valid, 15 remained invalid.
- combined: 0 invalid-to-valid repairs, 0 valid-to-invalid regressions, 0 remained valid, 15 remained invalid.

Original candidates and final revisions are both independently evaluated after all model calls. No evaluator counterexamples enter the model context.

## Per-case validity

| Case | Baseline | Structured | Critique | Combined |
| --- | --- | --- | --- | --- |
| h0_wd0 | 0/3 | 0/3 | 0/3 | 0/3 |
| h0_wd4 | 0/3 | 0/3 | 0/3 | 0/3 |
| h1_wd5 | 0/3 | 0/3 | 0/3 | 0/3 |
| h2_wd6 | 0/3 | 0/3 | 0/3 | 0/3 |
| h2_wd9 | 0/3 | 0/3 | 0/3 | 0/3 |

## Scope and interpretation

- Pilot-only observations on five cases, not a held-out final benchmark.
- Variants ran in separate batches; provider load and timing effects were not controlled.
- Only three weekly soft categories are scored; no optimum was established.
- No labelled infeasible cases; UNSAT-detection accuracy cannot be estimated.
- Gateway schema conformance is observed, but full strict enforcement is not established.
- A repaired roster is counted only when post-hoc independent evaluation marks the final output valid.

The initial feasibility labels come from the pre-run manifest: H1/WD5 and H2/WD6 have validated supplied witnesses; the other cases started unlabelled. Any later valid generated roster provides a witness, but a failed attempt does not prove infeasibility.

These are descriptive results. Both successful repairs and failures should be retained in the report. Structured output addresses representation and identifier risks; an LLM audit can still miscount staffing or introduce new violations.

## Included evidence

- `pilot_chat_v1.json`: aggregate metrics, case definitions, observed schema conformance, limitations, and archived suite/run identifiers.
- `pilot_chat_v1.csv`: all 60 trials with portable archive run identifiers.
- `../docs/safeguards.md`: exact safeguard definitions and reproduction commands.

Raw requests/responses and temporary development runs remain in the original workspace archive and are excluded from this clean repository. The included metrics preserve the completed experiment; replaying original traces requires that archive. New suites can be generated and independently replayed using the included batch runner and summarizer.
