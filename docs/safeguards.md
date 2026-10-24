# Safeguard methodology

Solution B uses SoCLaas model `x-test-2` through its OpenAI-compatible Chat Completions API. The model produces every roster assignment directly. Parsing and independent post-hoc evaluation run in Python; the LLM has no tools, code execution or classical solver access.

## Variants

| Variant | Generation | Audit and revision | Maximum calls |
| --- | --- | --- | --- |
| `baseline` | The shared prompt requests JSON. | None. | 1 |
| `structured` | Same prompt plus `response_format.type=json_schema`, `strict=true`, case-specific enums and a supported generation schema. | None. | 1 |
| `critique` | Same baseline prompt. | One fresh LLM audit, then one final revision. | 3 |
| `combined` | Structured generation. | One audit, then structured final revision. | 3 |

`rostering/llm/safeguards.py` defines the generation schema and audit/revision instructions. `prompts/baseline.txt` defines the shared task and objective. The audit checks concrete nurse/day or day/shift/skill counterexamples for completeness, coverage, skills, transitions, requests and weekends. Revision is told to verify the audit because it may contain mistakes.

The audit uses the same LLM in a fresh request. It is a bounded adaptation of [Self-Refine](https://arxiv.org/abs/2303.17651), rather than an independently trained verifier or a complete Chain-of-Verification implementation. The deterministic evaluator runs after all model calls; its counterexamples never enter the revision prompt.

The schema restricts output fields, identifier enums and record count. It cannot establish coverage, uniqueness, nurse-to-skill compatibility or legal transitions. The supported generation subset also omits the local contract's conditional status/roster rule. Generation-schema conformance, full output-contract validity and scheduling correctness are therefore reported separately.

## Fixed settings and failure handling

- Requested reasoning effort: `none`; temperature remains at provider default; no model seed is requested.
- Generation/revision output limit: 16,000 tokens each. Audit limit: 8,000.
- Timeout: 240 seconds per call, with no automatic retries.
- An empty or incomplete generation is retained without triggering critique.
- An empty or incomplete audit retains the original candidate and records `critique_incomplete`.
- API failures and incomplete outputs remain failed trials; missing usage is not treated as known zero cost.
- Original and final candidates are evaluated afterwards so repairs and regressions can be counted.

## Cases and comparison

The two plans in `config/experiments/` use these same five initial-history/weekly-data combinations, with three repetitions each:

| Case | Minimum nurse-days | Preferred nurse-days | Requests | Initial feasibility label |
| --- | --- | --- | --- | --- |
| H0 / WD0 | 22 | 30 | 3 | Unlabelled |
| H0 / WD4 | 26 | 29 | 1 | Unlabelled |
| H1 / WD5 | 23 | 28 | 3 | Feasible, validated supplied witness |
| H2 / WD6 | 23 | 31 | 2 | Feasible, validated supplied witness |
| H2 / WD9 | 19 | 26 | 5 | Unlabelled |

Reference witnesses are evaluated outside the generation pipeline and never included in prompts. The cases were selected before their batch results were inspected. The earlier H0/WD1 development case is excluded. A failed attempt does not establish infeasibility on an unlabelled case.

The comparison measures schema validity, complete hard-valid rosters, violations by type, valid-only partial soft cost, and total latency/tokens/calls across stages. Every attempted trial remains in the validity denominator. The objective covers three weekly soft categories only; see [the input contract](input_contract.md). No optimality or UNSAT-detection claim is made.

## Measured gateway behaviour

The retained `python -m rostering.llm.probe` command tests both APIs with a valid schema containing a random enum absent from the conflicting plain-text prompt, then an invalid strict schema. It writes fresh evidence under ignored `outputs/`.

On 24 October 2026, Responses ignored the schema request; Chat Completions produced the schema's exact enum value. Both APIs accepted the invalid schema. The new experiments therefore use Chat Completions consistently, while avoiding a claim that OpenAI's strict guarantees automatically apply to this gateway. Request conventions follow the [Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

In the completed matched experiment, all 45 constrained stages matched their generation schemas. Some outputs still violated the fuller contract through inconsistent status/roster combinations, and none satisfied every hard scheduling check. See [the recorded results](../reports/pilot_chat_v1.md), [aggregate JSON](../reports/pilot_chat_v1.json), and [all-trial CSV](../reports/pilot_chat_v1.csv).

Raw evidence for that historical run remains in the previous workspace archive. The clean repository includes its metrics and portable suite/run identifiers, plus the scripts to collect and verify new experiments. Variants ran in separate batches, so latency and accuracy differences are descriptive pilot observations; provider load and timing effects were not controlled.
