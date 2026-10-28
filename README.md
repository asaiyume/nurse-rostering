# Nurse Rostering

CS4263: compare **Solution A (classical CSP)** and **Solution B (LLM)** on the same INRC2 inputs, roster format and evaluator. Both solutions are implemented independently.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from this directory:

```sh
uv sync --locked
```

Python 3.13 and dependencies are managed by uv. Only live LLM runs need a key:

```sh
export SOCLAAS_API_KEY="your-api-key"
```

Provider/model settings are in `config/llm.json`; `.env` files are not loaded automatically.

## Layout

- `rostering/`: shared conversion, contracts, evaluation and JSON utilities.
- `rostering/classical/`: Solution A, a feasibility-only CSP solver.
- `rostering/llm/`: Solution B API client, direct generation and safeguards.
- `schemas/`, `converted/`, `inrc2/`: shared formats and inputs.
- `config/`, `prompts/`: LLM settings and experiment plans.
- `scripts/`, `tests/`, `reports/`: reporting, offline checks and recorded results.

## Shared input and evaluation

Both solutions can load the ready-made JSON files in [`converted/`](converted/README.md): all 690 combinations across 23 scenarios. [`converted/index.csv`](converted/index.csv) lists the files; the matched benchmark plan loads them directly.

```sh
uv run python -m rostering evaluate --instance converted/n005w4/h0_wd1.json --roster outputs/ROSTER.json
```

Each solution exports one record per nurse-day, including Off. Follow the [shared contract](docs/input_contract.md) and keep solver-specific metadata separate.

Rebuild the complete set with `uv run python scripts/convert_dataset.py`. For one new case: `uv run python -m rostering convert --history 0 --week-data 4 --out outputs/instances/h0_wd4.json`.

## Solution A

```sh
uv run python -m rostering.classical --instance converted/n005w4/h0_wd1.json --out outputs/classical/roster.json
uv run python -m rostering evaluate --instance converted/n005w4/h0_wd1.json --roster outputs/classical/roster.json
```

The solver uses required staffing slots as variables, qualified nurses as values, and depth-first backtracking with MRV, degree tie-break and LCV. Specialized AC-3, global capacity checks, identical-slot symmetry breaking and bitset domains reduce search. It enforces minimum coverage, qualified skills, single daily assignments and legal shift transitions, including history into Monday. Unused nurse-days are Off.

Defaults: stop at the first valid roster, with a 240-second search limit. Use `--time-limit SECONDS` to change the limit or `--exhaustive` to disable it. The roster is independently evaluated before return; runtime, search statistics and proof flags are saved separately in `roster.metadata.json`. A timeout returns `unknown`; exhaustive failure proves infeasibility. Soft penalties are not optimized, and no soft-cost optimality is claimed.

Run cases from the smallest scenario folders, or run all 690 inputs:

```sh
uv run python scripts/run_classical.py --folders 10 --cases-per-folder 30 --workers 4 --time-limit 420
uv run python scripts/run_classical.py --folders 23 --cases-per-folder 30 --workers 4 --time-limit 420
```

Runner defaults: 10 folders, 30 cases per folder, 4 workers and 420 seconds per case. Folders are selected by nurse count, then horizon; `--list-only` previews selection. Each run preserves previous outputs under `outputs/classical/runs/`, saving per-case rosters, metadata and evaluations, plus CSV/JSON summaries. The final summary reports correctness (hard-valid cases / cases tested), failed or unresolved cases, and shortest/longest recorded runtimes. Reported soft scores are diagnostic only.

## Solution B

```sh
uv run python -m rostering llm --instance converted/n005w4/h0_wd1.json --dry-run
uv run python -m rostering llm --instance converted/n005w4/h0_wd1.json --variant baseline
```

Variants: `baseline`, `structured`, `critique`, `combined`. A baseline/structured trial makes one call; critique/combined makes up to three. Defaults: requested high reasoning effort, 32,000 generation/revision tokens, 16,000 audit tokens and no imposed request or whole-trial time limit. Token caps include reasoning and answer tokens. Outputs are saved under ignored `outputs/`.

Run the frozen matched benchmark (15 classical runs, 180 LLM trials; up to 360 high-effort calls):

```sh
uv run python scripts/run_comparison.py --list-only
uv run python scripts/run_comparison.py
# Resume without replaying saved or interrupted requests:
uv run python scripts/run_comparison.py --resume outputs/comparison/RUN_DIRECTORY
```

See [safeguards](docs/safeguards.md) and [case selection](docs/benchmark.md).

## Checks and scope

```sh
uv run python -m unittest discover -s tests -v
```

Tests, conversion, evaluation, replay verification and dry runs are offline.

After a benchmark run, independently replay its records without model calls:

```sh
uv run python scripts/verify_comparison.py outputs/comparison/RUN_DIRECTORY
```

Evidence: [full 50-nurse outputs and thinking](reports/examples/n050w4_h2_wd6/README.md), [confirmed critique repair](reports/examples/critique_repair/README.md), and [verification record](reports/hard_only_parity_v1_verification.json). Full-suite raw traces stay under ignored `outputs/`; selected examples and portable all-trial metrics are included in `reports/`.

Both solutions seek **hard-constraint feasibility only**: minimum coverage, qualified skills, one working shift per nurse-day and legal successions including history into Monday. Complete nurse-day records and valid identifiers are mandatory. Surplus staffing is allowed; preferences, weekends, fairness, streak limits and total workload are not optimization targets or extra hard constraints. The shared evaluator may report soft scores as diagnostics. The comparison uses independent seven-day week-zero inputs; full-horizon scoring and automatic history advancement are not implemented. Exit codes: 0 valid/dry run, 2 evaluated but invalid/unresolved, 1 setup/API error.

<!-- parity-results:start -->
## Matched results

Same 15 inputs and four hard constraints; 1 classical run and 3 repetitions per LLM variant per case. Both seek feasibility only, without imposed time limits. B requests high reasoning effort, with 32,000 generation/revision tokens and 16,000 audit tokens. See [case selection](docs/benchmark.md) and [full results](reports/hard_only_parity_v1.md).

| Method | Cases tested | Hard-valid trials / attempted | Mean runtime (s) | API calls |
| --- | --- | --- | --- | --- |
| classical | 15 | 15/15 | 0.012 | 0 |
| baseline | 15 | 40/45 | 162.098 | 45 |
| structured | 15 | 38/45 | 165.944 | 45 |
| critique | 15 | 40/45 | 329.464 | 111 |
| combined | 15 | 43/45 | 344.471 | 111 |

All attempts remain in the denominator. Runtime includes local processing; LLM runtime also includes remote service and network time. The purposive sample supports descriptive comparisons, not a causal claim about nurse count or a full-horizon INRC2 result. Soft scores are not optimization targets.
<!-- parity-results:end -->
