# LLM safeguards

Solution B uses SoCLaas `x-test-2` through its OpenAI-compatible Chat Completions API. The `hard_only_v1` prompt asks for any roster satisfying the same four hard constraints as Solution A. The model produces every assignment directly; Python performs parsing and independent evaluation afterwards. The LLM has no tools, code execution or classical-solver access.

## Variants

| Variant | Generation | Audit and revision | Maximum calls |
| --- | --- | --- | --- |
| `baseline` | Natural-language rules and shared input JSON; prompt requests JSON. | None. | 1 |
| `structured` | Same prompt plus case-specific `response_format.type=json_schema`, `strict=true`. | None. | 1 |
| `critique` | Same baseline prompt. | One fresh LLM audit, then one revision. | 3 |
| `combined` | Structured generation. | One audit, then structured revision. | 3 |

The exact generation template is `prompts/baseline.txt`; audit/revision templates are in `rostering/llm/safeguards.py`. Every run saves the full assembled requests, original output, audit, revision and final evaluation under ignored `outputs/`.

The audit checks specific nurse/day or day/shift/skill counterexamples for complete output, minimum coverage, qualifications and legal transitions, including history into Monday. It ignores preferred staffing, shift-off requests, complete weekends, fairness, streak limits and full-horizon workload. Revision must verify audit claims because the audit can itself be wrong. This bounded self-critique is an adaptation of [Self-Refine](https://arxiv.org/abs/2303.17651); it is not an independently trained verifier. The deterministic evaluator runs only after model calls finish and never feeds findings back into the LLM.

## Output schema and its limits

The generation schema restricts fields, identifier enums and maximum roster length. It cannot establish nurse-day uniqueness, staffing coverage, nurse-to-skill compatibility or legal transitions. It also omits the full local output schema's conditional status/empty-roster rule. Generation-schema conformance, full output-schema validity and hard scheduling validity are distinct measures.

The gateway is OpenAI-compatible, but API compatibility alone does not establish full strict-schema enforcement. Structured output is requested and the returned data is independently validated; schema conformance does not prove scheduling correctness.

## Settings and failures

- Requested reasoning effort: `high`; provider-default temperature; no model seed.
- Generation/revision: at most 32,000 output tokens each; audit: at most 16,000. These caps include reasoning and answer tokens.
- Matched benchmark: no imposed classical-search, client-request or whole-trial deadline. Generation stops at the configured token limit or the provider's termination. Server/network failures remain possible.
- Single-case LLM CLI: timeouts are disabled by default. Explicit `--timeout` / `--total-timeout` options are available for separate deadline experiments.
- No automatic retries, JSON repairs or evaluator-directed corrections.
- Empty/incomplete generation does not trigger an audit. Empty/incomplete audit retains the initial candidate and records the failure.
- API failures, incomplete outputs and abstentions stay in the trial denominator. Missing usage is not reported as known zero usage.
- Original and revised candidates are evaluated after the calls to count valid repairs and regressions.

## Matched comparison

The frozen [plan](../config/experiments/parity_v1.json) covers 15 independent seven-day inputs with five nurse counts and controlled history/demand contrasts. See [selection details](benchmark.md). A runs once per input; each B variant runs three times: 15 classical runs and 180 LLM trials, with at most 360 model calls. Job order is shuffled with scheduling seed 4263; this is not a model sampling seed.

`uv run python scripts/run_comparison.py` saves each attempt, freezes input and source hashes, and generates the [comparison](../reports/hard_only_parity_v1.md) and README table when complete. Resume with `--resume outputs/comparison/RUN_DIRECTORY`; completed and uncertain interrupted requests are not replayed. Raw traces remain local and ignored; portable results include every attempted trial and identify incomplete runs explicitly.

New runs also save a `source_snapshot/`. Replay can check the original runner against its frozen hash after reporting fixes; current model, prompt, schema and evaluator sources must still match. Exported example ZIPs are saved inside ignored `outputs/exports/`.

There is no soft objective or optimality claim. The evaluator's retained soft scores are optional diagnostics. H0/H1/H2 and WD numbers identify alternative initial histories and weekly demand files, not sequential weeks.
